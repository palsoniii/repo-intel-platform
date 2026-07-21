"""
Express.js parser: walks a repo's .js/.ts files, uses tree-sitter to extract
functions, imports, and Express route definitions (app.get/post/... and
router.get/post/...), plus package.json for external dependencies.

This is the first parser implementation and establishes the pattern that the
NestJS parser (Phase 6) will follow.
"""

from __future__ import annotations

import json
from pathlib import Path

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from app.parsers.base import BaseParser
from app.schemas.parser_schema import (
    ApiEndpoint,
    ClassNode,
    ConfigFile,
    ConfigFileType,
    Dependencies,
    DependencyType,
    ExternalDependency,
    FunctionNode,
    HttpMethod,
    InternalDependencyEdge,
    ModuleNode,
    ParsedRepository,
    RepoMetadata,
)

JS_LANGUAGE = Language(tsjs.language())

SKIP_DIRS = {"node_modules", ".git", "dist", "build", "coverage", ".next"}
SOURCE_EXTENSIONS = {".js", ".mjs", ".cjs"}  # .ts handled by NestJS parser later
MAX_FILES = 3000

ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}

# Tree-sitter queries, compiled once at module load
CALL_QUERY = Query(JS_LANGUAGE, "(call_expression) @call")
FUNCTION_DECL_QUERY = Query(
    JS_LANGUAGE,
    """
    (function_declaration name: (identifier) @name) @func
    """,
)
REQUIRE_QUERY = Query(
    JS_LANGUAGE,
    """
    (call_expression
        function: (identifier) @fn_name
        arguments: (arguments (string (string_fragment) @path))
    ) @call
    """,
)


class ExpressParser(BaseParser):
    framework_name = "express"

    def detect(self, repo_path: Path) -> bool:
        pkg_json = repo_path / "package.json"
        if not pkg_json.exists():
            return False
        try:
            data = json.loads(pkg_json.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        return "express" in deps

    def parse(self, repo_path: Path) -> ParsedRepository:
        warnings: list[str] = []
        files_skipped: list[str] = []

        pkg_json = repo_path / "package.json"
        pkg_data = json.loads(pkg_json.read_text()) if pkg_json.exists() else {}
        framework_version = (
            pkg_data.get("dependencies", {}).get("express")
            or pkg_data.get("devDependencies", {}).get("express")
        )

        modules: list[ModuleNode] = []
        functions: list[FunctionNode] = []
        classes: list[ClassNode] = []
        api_endpoints: list[ApiEndpoint] = []
        internal_deps: list[InternalDependencyEdge] = []

        source_files = self._collect_source_files(repo_path, files_skipped)

        if len(source_files) > MAX_FILES:
            warnings.append(
                f"Repo has {len(source_files)} source files, exceeding MAX_FILES={MAX_FILES}. "
                f"Only the first {MAX_FILES} were parsed."
            )
            source_files = source_files[:MAX_FILES]

        parser = Parser(JS_LANGUAGE)
        path_to_module_id: dict[Path, str] = {}

        for i, file_path in enumerate(source_files):
            module_id = f"mod_{i}"
            path_to_module_id[file_path] = module_id

        for file_path in source_files:
            module_id = path_to_module_id[file_path]
            rel_path = str(file_path.relative_to(repo_path))
            try:
                source_bytes = file_path.read_bytes()
            except OSError as e:
                warnings.append(f"Could not read {rel_path}: {e}")
                continue

            try:
                tree = parser.parse(source_bytes)
            except Exception as e:  # tree-sitter parse failures are rare but possible
                warnings.append(f"Failed to parse {rel_path}: {e}")
                continue

            root = tree.root_node

            imports, import_warnings = self._extract_requires(root, source_bytes)
            resolved_import_ids = self._resolve_imports(
                imports, file_path, repo_path, path_to_module_id
            )
            for target_id in resolved_import_ids:
                internal_deps.append(
                    InternalDependencyEdge(from_module_id=module_id, to_module_id=target_id)
                )

            module = ModuleNode(
                id=module_id,
                path=rel_path,
                imports=resolved_import_ids,
            )
            modules.append(module)

            file_functions = self._extract_functions(root, source_bytes, module_id)
            functions.extend(file_functions)
            func_name_to_id = {f.name: f.id for f in file_functions}

            file_routes = self._extract_routes(root, source_bytes, module_id, func_name_to_id)
            api_endpoints.extend(file_routes)

        external_deps = [
            ExternalDependency(name=name, version=version, dep_type=DependencyType.RUNTIME)
            for name, version in pkg_data.get("dependencies", {}).items()
        ] + [
            ExternalDependency(name=name, version=version, dep_type=DependencyType.DEV)
            for name, version in pkg_data.get("devDependencies", {}).items()
        ]

        config_files = self._find_config_files(repo_path)

        metadata = RepoMetadata(
            name=repo_path.name,
            source_url="",  # filled in by caller (acquisition layer knows the URL)
            detected_language="javascript",
            detected_framework="express",
            framework_version=framework_version,
            files_scanned=len(source_files),
            files_skipped=files_skipped,
            parse_warnings=warnings,
        )

        return ParsedRepository(
            metadata=metadata,
            modules=modules,
            classes=classes,
            functions=functions,
            api_endpoints=api_endpoints,
            database_entities=[],  # Express has no standard ORM; left empty by design
            dependencies=Dependencies(internal=internal_deps, external=external_deps),
            config_files=config_files,
        )

    # -- helpers --------------------------------------------------------

    def _collect_source_files(self, repo_path: Path, files_skipped: list[str]) -> list[Path]:
        results = []
        for f in repo_path.rglob("*"):
            if not f.is_file():
                continue
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            if f.suffix in SOURCE_EXTENSIONS:
                results.append(f)
            elif f.suffix in {".ts", ".tsx", ".jsx"}:
                files_skipped.append(str(f.relative_to(repo_path)) + " (non-.js source, skipped)")
        return sorted(results)

    def _extract_requires(
        self, root: Node, source: bytes
    ) -> tuple[list[str], list[str]]:
        """Returns list of string arguments passed to require(...) calls."""
        requires = []
        warnings: list[str] = []
        cursor = QueryCursor(REQUIRE_QUERY)
        matches = cursor.captures(root)
        fn_nodes = matches.get("fn_name", [])
        path_nodes = matches.get("path", [])
        # naive pairing by matching call node ranges; good enough for require() extraction
        for fn_node in fn_nodes:
            if source[fn_node.start_byte:fn_node.end_byte] != b"require":
                continue
            call_node = fn_node.parent
            for path_node in path_nodes:
                if call_node and call_node.start_byte <= path_node.start_byte <= call_node.end_byte:
                    requires.append(source[path_node.start_byte:path_node.end_byte].decode("utf-8", "replace"))
        return requires, warnings

    def _resolve_imports(
        self,
        raw_imports: list[str],
        current_file: Path,
        repo_path: Path,
        path_to_module_id: dict[Path, str],
    ) -> list[str]:
        """Resolves relative require() paths ('./routes/users') to module ids.
        External package requires ('express') are not resolved to module ids --
        they show up in `dependencies.external` via package.json instead."""
        resolved = []
        for imp in raw_imports:
            if not imp.startswith("."):
                continue  # external package, not an internal module edge
            candidate = (current_file.parent / imp).resolve()
            for suffix in ("", ".js", "/index.js", ".mjs", ".cjs"):
                probe = Path(str(candidate) + suffix)
                if probe in path_to_module_id:
                    resolved.append(path_to_module_id[probe])
                    break
        return resolved

    def _extract_functions(
        self, root: Node, source: bytes, module_id: str
    ) -> list[FunctionNode]:
        functions = []
        cursor = QueryCursor(FUNCTION_DECL_QUERY)
        matches = cursor.captures(root)
        for i, name_node in enumerate(matches.get("name", [])):
            name = source[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace")
            functions.append(
                FunctionNode(
                    id=f"{module_id}_fn_{i}",
                    name=name,
                    module_id=module_id,
                )
            )
        return functions

    def _extract_routes(
        self,
        root: Node,
        source: bytes,
        module_id: str,
        func_name_to_id: dict[str, str],
    ) -> list[ApiEndpoint]:
        """Matches app.<method>(path, handler) and router.<method>(path, handler)."""
        routes = []
        cursor = QueryCursor(CALL_QUERY)
        matches = cursor.captures(root)
        route_index = 0
        for call_node in matches.get("call", []):
            func_node = call_node.child_by_field_name("function")
            if func_node is None or func_node.type != "member_expression":
                continue
            obj_node = func_node.child_by_field_name("object")
            prop_node = func_node.child_by_field_name("property")
            if obj_node is None or prop_node is None:
                continue

            obj_name = source[obj_node.start_byte:obj_node.end_byte].decode("utf-8", "replace")
            method_name = source[prop_node.start_byte:prop_node.end_byte].decode("utf-8", "replace")

            if obj_name not in {"app", "router"} or method_name not in ROUTE_METHODS:
                continue

            args_node = call_node.child_by_field_name("arguments")
            if args_node is None or args_node.named_child_count == 0:
                continue
            path_arg = args_node.named_children[0]
            if path_arg.type != "string":
                continue
            fragment = next(
                (c for c in path_arg.named_children if c.type == "string_fragment"), None
            )
            if fragment is None:
                continue
            route_path = source[fragment.start_byte:fragment.end_byte].decode("utf-8", "replace")

            handler_id = self._resolve_handler_id(args_node, source, func_name_to_id)

            routes.append(
                ApiEndpoint(
                    id=f"{module_id}_ep_{route_index}",
                    method=HttpMethod(method_name.upper()) if method_name.upper() in HttpMethod.__members__ else HttpMethod.UNKNOWN,
                    path=route_path,
                    handler_function_id=handler_id,
                    framework_annotation=f"{obj_name}.{method_name}",
                )
            )
            route_index += 1
        return routes

    def _resolve_handler_id(
        self, args_node: Node, source: bytes, func_name_to_id: dict[str, str]
    ) -> str | None:
        """Handler is usually the last argument. If it's a named identifier
        (e.g. router.post('/x', createUser)), resolve it to a known function id.
        If it's an inline arrow/anonymous function, we don't have a stable id for it."""
        if args_node.named_child_count < 2:
            return None
        last_arg = args_node.named_children[-1]
        if last_arg.type == "identifier":
            name = source[last_arg.start_byte:last_arg.end_byte].decode("utf-8", "replace")
            return func_name_to_id.get(name)
        return None  # inline anonymous handler -- no stable function id to point to

    def _find_config_files(self, repo_path: Path) -> list[ConfigFile]:
        configs = []
        candidates = {
            "package.json": ConfigFileType.BUILD,
            ".env": ConfigFileType.ENV,
            ".env.example": ConfigFileType.ENV,
            "Procfile": ConfigFileType.FRAMEWORK_CONFIG,
            "docker-compose.yml": ConfigFileType.FRAMEWORK_CONFIG,
            "Dockerfile": ConfigFileType.FRAMEWORK_CONFIG,
        }
        for filename, ctype in candidates.items():
            if (repo_path / filename).exists():
                configs.append(ConfigFile(path=filename, config_type=ctype))
        return configs
