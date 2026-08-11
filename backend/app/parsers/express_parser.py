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
# Test trees are not application architecture -- counting them as modules inflates the
# module set with files that don't describe the running service. Unlike SKIP_DIRS these
# are *recorded* in files_skipped rather than dropped silently, so the exclusion stays
# auditable (SKIP_DIRS would drown that list in node_modules noise).
TEST_DIRS = {"test", "tests", "__tests__", "__mocks__", "spec", "e2e", "cypress"}
# Test files living beside source (user.test.js, user.spec.js) -- same rationale.
TEST_FILE_SUFFIXES = (".test.js", ".spec.js", ".test.mjs", ".spec.mjs", ".test.cjs", ".spec.cjs")
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
        routes_by_module: dict[str, list[ApiEndpoint]] = {}
        mount_prefixes: dict[str, str] = {}  # module_id -> prefix its router is mounted at

        # Keyed on the RESOLVED path: _resolve_imports() resolves its candidates, and on
        # macOS a clone under /var/folders resolves to /private/var/folders, so keying on
        # the unresolved path made every internal-import lookup miss silently.
        for i, file_path in enumerate(source_files):
            module_id = f"mod_{i}"
            path_to_module_id[file_path.resolve()] = module_id

        for file_path in source_files:
            module_id = path_to_module_id[file_path.resolve()]
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

            # Routes are held back rather than appended immediately: a router's mount
            # prefix (app.use('/api/tutorials', router)) may be declared in a *different*
            # file than the routes themselves, so prefixes can only be applied once every
            # file has been scanned. See _apply_mount_prefixes below.
            routes_by_module[module_id] = self._extract_routes(
                root, source_bytes, module_id, func_name_to_id
            )
            self._collect_mounts(
                root,
                source_bytes,
                module_id,
                file_path,
                repo_path,
                path_to_module_id,
                mount_prefixes,
            )

        api_endpoints = self._apply_mount_prefixes(routes_by_module, mount_prefixes)

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
            rel_parts = f.relative_to(repo_path).parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            # Hidden directories (.husky, .install-scripts, .github, ...) hold tooling
            # and scaffolding, not the service being described.
            if any(part.startswith(".") for part in rel_parts[:-1]):
                continue
            if f.suffix in SOURCE_EXTENSIONS:
                if f.name.endswith(TEST_FILE_SUFFIXES) or any(
                    part in TEST_DIRS for part in rel_parts
                ):
                    files_skipped.append(
                        str(f.relative_to(repo_path)) + " (test file, skipped)"
                    )
                    continue
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

    def _collect_mounts(
        self,
        root: Node,
        source: bytes,
        module_id: str,
        current_file: Path,
        repo_path: Path,
        path_to_module_id: dict[Path, str],
        mount_prefixes: dict[str, str],
    ) -> None:
        """Records where routers get mounted, so router-relative paths can be resolved
        into the real external paths. Two forms are handled, both common in real apps:

            app.use('/api/tutorials', router)        -- router declared in THIS file
            app.use('/users', require('./routes/users'))  -- router lives in ANOTHER file

        The second argument may also be an identifier bound earlier to a require()
        (`const routes = require('./routes/v1'); app.use('/v1', routes)`), which is
        resolved via the file's identifier -> require-path bindings.

        Not handled: mounts whose path comes from data rather than a literal, e.g.
        iterating an array of {path, route} objects and calling router.use(r.path,
        r.route). Those routes keep their router-relative paths."""
        local_requires = self._identifier_require_bindings(root, source)

        for call_node in QueryCursor(CALL_QUERY).captures(root).get("call", []):
            func_node = call_node.child_by_field_name("function")
            if func_node is None or func_node.type != "member_expression":
                continue
            obj_node = func_node.child_by_field_name("object")
            prop_node = func_node.child_by_field_name("property")
            if obj_node is None or prop_node is None:
                continue
            if source[prop_node.start_byte:prop_node.end_byte] != b"use":
                continue
            obj_name = source[obj_node.start_byte:obj_node.end_byte].decode("utf-8", "replace")
            if obj_name not in {"app", "router"}:
                continue

            args = call_node.child_by_field_name("arguments")
            if args is None or args.named_child_count < 2:
                continue  # app.use(middleware) with no path mounts nothing routable

            prefix = self._string_literal(args.named_children[0], source)
            if prefix is None:
                continue  # non-literal mount path -- can't resolve statically

            target = args.named_children[1]
            required_path = self._require_path(target, source)
            if required_path is None and target.type == "identifier":
                name = source[target.start_byte:target.end_byte].decode("utf-8", "replace")
                required_path = local_requires.get(name)

            if required_path is not None:
                target_id = self._resolve_single_import(
                    required_path, current_file, path_to_module_id
                )
                if target_id is not None:
                    mount_prefixes[target_id] = self._join_paths(
                        mount_prefixes.get(target_id, ""), prefix
                    )
            else:
                # Router object mounted in the same file it was built in.
                mount_prefixes[module_id] = self._join_paths(
                    mount_prefixes.get(module_id, ""), prefix
                )

    def _identifier_require_bindings(self, root: Node, source: bytes) -> dict[str, str]:
        """Maps `const routes = require('./routes/v1')` -> {'routes': './routes/v1'}."""
        bindings: dict[str, str] = {}
        for declarator in self._find_all(root, "variable_declarator"):
            name_node = declarator.child_by_field_name("name")
            value_node = declarator.child_by_field_name("value")
            if name_node is None or value_node is None or name_node.type != "identifier":
                continue
            required = self._require_path(value_node, source)
            if required is not None:
                name = source[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace")
                bindings[name] = required
        return bindings

    def _find_all(self, node: Node, type_: str):
        if node.type == type_:
            yield node
        for child in node.children:
            yield from self._find_all(child, type_)

    @staticmethod
    def _string_literal(node: Node, source: bytes) -> str | None:
        if node.type != "string":
            return None
        fragment = next((c for c in node.named_children if c.type == "string_fragment"), None)
        if fragment is None:
            return ""
        return source[fragment.start_byte:fragment.end_byte].decode("utf-8", "replace")

    def _require_path(self, node: Node, source: bytes) -> str | None:
        """Returns the path string of a `require('...')` call node, else None. Also
        unwraps the immediately-invoked form `require('./routes')(app)`."""
        if node.type != "call_expression":
            return None
        func = node.child_by_field_name("function")
        if func is None:
            return None
        if func.type == "call_expression":  # require('./routes')(app)
            return self._require_path(func, source)
        if source[func.start_byte:func.end_byte] != b"require":
            return None
        args = node.child_by_field_name("arguments")
        if args is None or args.named_child_count == 0:
            return None
        return self._string_literal(args.named_children[0], source)

    @staticmethod
    def _resolve_single_import(
        import_path: str, current_file: Path, path_to_module_id: dict[Path, str]
    ) -> str | None:
        if not import_path.startswith("."):
            return None
        candidate = (current_file.parent / import_path).resolve()
        for suffix in ("", ".js", "/index.js", ".mjs", ".cjs"):
            probe = Path(str(candidate) + suffix)
            if probe in path_to_module_id:
                return path_to_module_id[probe]
        return None

    @staticmethod
    def _join_paths(*parts: str) -> str:
        joined = "/".join(p.strip("/") for p in parts if p and p.strip("/"))
        return "/" + joined if joined else "/"

    def _apply_mount_prefixes(
        self, routes_by_module: dict[str, list[ApiEndpoint]], mount_prefixes: dict[str, str]
    ) -> list[ApiEndpoint]:
        """Rewrites router-relative paths into external paths using the mount prefixes
        gathered across every file. Routes registered directly on `app` are already
        absolute and are left alone."""
        endpoints: list[ApiEndpoint] = []
        for module_id, routes in routes_by_module.items():
            prefix = mount_prefixes.get(module_id, "")
            for route in routes:
                if prefix and (route.framework_annotation or "").startswith("router."):
                    route.path = self._join_paths(prefix, route.path)
                endpoints.append(route)
        return endpoints

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
