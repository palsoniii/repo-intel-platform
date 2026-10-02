"""
Derived structure computed once per analysis and stored with it: which architectural
layer each file belongs to, which classes inject which (NestJS constructor injection),
where each endpoint is declared, and the ORM models (entities.py).

Everything here is computed from the ParsedRepository plus stored source text, so the
views can be served without Neo4j and without re-parsing.
"""

from __future__ import annotations

import re
from collections import defaultdict

from app.product.entities import extract_entities
from app.product.jsscan import line_of, match_bracket, strip_comments
from app.schemas.parser_schema import ParsedRepository

# Ordered: the first rule that matches wins, so the more specific ones come first.
LAYERS: list[tuple[str, str]] = [
    ("test", r"(^|/)(tests?|__tests__|spec|e2e)/|\.(spec|test|e2e-spec)\.[jt]s$"),
    ("module", r"\.module\.ts$"),
    ("route", r"(^|/)routes?/|\.routes?\.[jt]s$|(^|/)routers?/|\.router\.[jt]s$|controllers?(/|\.)|resolvers?(/|\.)"),
    ("middleware", r"middlewares?(/|\.)|guards?(/|\.)|interceptors?(/|\.)|(^|/)pipes?/|\.pipe\.[jt]s$|filters?(/|\.)|strateg(y|ies)(/|\.)|(^|/)auth/|passport"),
    ("data", r"models?(/|\.)|entit(y|ies)(/|\.)|schemas?(/|\.)|repositor(y|ies)(/|\.)|migrations?(/|\.)|seeders?(/|\.)|(^|/)db/|database|prisma|\.dao\.[jt]s$"),
    ("service", r"services?(/|\.)|providers?(/|\.)|use-?cases?(/|\.)|(^|/)domain/|(^|/)application/|handlers?(/|\.)|jobs?(/|\.)|workers?(/|\.)|queues?(/|\.)"),
    ("contract", r"dtos?(/|\.)|interfaces?(/|\.)|(^|/)types?/|\.types?\.[jt]s$|validations?(/|\.)|validators?(/|\.)"),
    ("config", r"config(/|\.)|(^|/)env|settings|constants?(/|\.)"),
    ("entry", r"(^|/)(main|server|app|index|www)\.[cm]?[jt]s$|(^|/)bin/"),
    ("util", r"utils?(/|\.)|helpers?(/|\.)|(^|/)lib/|(^|/)common/|(^|/)shared/|(^|/)core/"),
]
_LAYER_PATTERNS = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in LAYERS]

LAYER_LABELS = {
    "entry": "Entry points",
    "module": "Modules",
    "route": "Routes & controllers",
    "middleware": "Middleware & auth",
    "service": "Services & business logic",
    "data": "Data access & models",
    "contract": "DTOs & types",
    "config": "Configuration",
    "util": "Utilities",
    "test": "Tests",
    "other": "Other",
}


def classify_layer(path: str) -> str:
    for name, rx in _LAYER_PATTERNS:
        if rx.search(path):
            return name
    return "other"


_CLASS_DECL_RE = re.compile(r"\bclass\s+(?P<name>\w+)")
_CONSTRUCTOR_RE = re.compile(r"\bconstructor\s*\(")
_PARAM_TYPE_RE = re.compile(r":\s*(?P<type>[A-Z]\w*)")
_INJECT_TOKEN_RE = re.compile(r"@Inject(?P<kind>\w*)\s*\(\s*(?P<arg>\w+)")


def _injections(parsed: ParsedRepository, files: dict[str, str], entity_names: set[str]) -> list[dict]:
    """Constructor-injected dependencies, e.g. UsersController -> UsersService, and
    @InjectRepository(User) / @InjectModel(Cat.name) -> entity. Only classes the parser
    knows about (or known entities) count as targets, so framework types like
    ConfigService from a package don't produce edges to nowhere."""
    class_ids_by_name: dict[str, str] = {}
    for c in parsed.classes:
        class_ids_by_name.setdefault(c.name, c.id)
    modules_by_id = {m.id: m for m in parsed.modules}

    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    classes_by_module: dict[str, list] = defaultdict(list)
    for c in parsed.classes:
        classes_by_module[c.module_id].append(c)

    for module_id, classes in classes_by_module.items():
        module = modules_by_id.get(module_id)
        text = files.get(module.path) if module else None
        if not text or "constructor" not in text:
            continue
        clean = strip_comments(text)
        decls = [(m.start(), m.group("name")) for m in _CLASS_DECL_RE.finditer(clean)]
        for cm in _CONSTRUCTOR_RE.finditer(clean):
            owner = next((name for pos, name in reversed(decls) if pos < cm.start()), None)
            owner_id = class_ids_by_name.get(owner or "")
            if owner_id is None:
                continue
            close = match_bracket(clean, cm.end() - 1)
            if close is None:
                continue
            params = clean[cm.end() : close]
            targets: list[tuple[str, str]] = []
            for inj in _INJECT_TOKEN_RE.finditer(params):
                if inj.group("arg") in entity_names:
                    targets.append(("entity", inj.group("arg")))
            for pm in _PARAM_TYPE_RE.finditer(params):
                t = pm.group("type")
                if t in class_ids_by_name and t != owner:
                    targets.append(("class", t))
            for kind, name in targets:
                key = (owner_id, f"{kind}:{name}")
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    {
                        "from_class_id": owner_id,
                        "to_kind": kind,
                        "to_class_id": class_ids_by_name.get(name) if kind == "class" else None,
                        "to_name": name,
                    }
                )
    return edges


_VERB_CALL_RE = re.compile(r"\.(?P<method>get|post|put|patch|delete|options|head|all)\s*\(", re.IGNORECASE)
_ROUTE_CALL_RE = re.compile(r"""\.route\s*\(\s*(?P<q>['"`])(?P<path>[^'"`]*)(?P=q)\s*\)""")
_STRING_ARG_RE = re.compile(r"""\s*(?P<q>['"`])(?P<path>[^'"`]*)(?P=q)""")
_REQUIRE_BINDING_RE = re.compile(
    r"""(?:const|let|var)\s+(?P<name>\w+)\s*=\s*require\(\s*['"](?P<src>\.[^'"]+)['"]\s*\)"""
    r"""|import\s+(?:\*\s+as\s+)?(?P<iname>\w+)\s+from\s+['"](?P<isrc>\.[^'"]+)['"]"""
)


def _express_route_calls(text: str) -> list[dict]:
    """Every `x.get(...)`-style registration in a file, in source order, with its
    path (direct, or from an enclosing `.route('/p')` chain), its middleware
    arguments and its handler expression."""
    from app.product.jsscan import _split_top_level

    clean = strip_comments(text)
    route_marks = [(m.end(), m.group("path")) for m in _ROUTE_CALL_RE.finditer(clean)]
    calls = []
    for m in _VERB_CALL_RE.finditer(clean):
        close = match_bracket(clean, m.end() - 1)
        if close is None:
            continue
        args = _split_top_level(clean[m.end() : close], ",")
        lit = _STRING_ARG_RE.match(clean, m.end())
        if lit and args and args[0].strip()[:1] in "'\"`":
            path, rest = lit.group("path"), args[1:]
        else:
            # Chained: the nearest preceding .route('/p') whose chain this call continues
            # (only whitespace and other verb calls between them).
            prior = [(pos, p) for pos, p in route_marks if pos <= m.start()]
            if not prior:
                continue
            pos, path = prior[-1]
            between = clean[pos : m.start()]
            if re.search(r";|\brouter\b\s*\.|\bapp\b\s*\.", between):
                continue
            rest = args
        if not rest:
            continue
        calls.append(
            {
                "offset": m.start(),
                "method": m.group("method").lower(),
                "path": path,
                "handler_expr": " ".join(rest[-1].split())[:80],
                "middleware": [" ".join(a.split())[:60] for a in rest[:-1]],
            }
        )
    return calls


def _resolve_relative(from_path: str, src: str, known: set[str]) -> str | None:
    base = from_path.rsplit("/", 1)[0] if "/" in from_path else ""
    parts = [p for p in base.split("/") if p]
    for seg in src.split("/"):
        if seg == "..":
            if parts:
                parts.pop()
        elif seg and seg != ".":
            parts.append(seg)
    candidate = "/".join(parts)
    for suffix in ("", ".js", ".ts", ".mjs", ".cjs", "/index.js", "/index.ts"):
        if candidate + suffix in known:
            return candidate + suffix
    return None


def endpoint_module_id(parsed: ParsedRepository, endpoint) -> str | None:
    if endpoint.handler_function_id:
        fn = next((f for f in parsed.functions if f.id == endpoint.handler_function_id), None)
        if fn:
            return fn.module_id
    if "_ep_" in endpoint.id:
        return endpoint.id.rsplit("_ep_", 1)[0]
    return None


def _endpoint_locations(parsed: ParsedRepository, files: dict[str, str]) -> dict[str, dict]:
    modules_by_id = {m.id: m for m in parsed.modules}
    functions_by_id = {f.id: f for f in parsed.functions}
    used: dict[str, set[int]] = defaultdict(set)
    out: dict[str, dict] = {}
    calls_cache: dict[str, list[dict]] = {}
    bindings_cache: dict[str, dict[str, str]] = {}
    known_paths = {m.path for m in parsed.modules}
    path_to_id = {m.path: m.id for m in parsed.modules}

    for ep in parsed.api_endpoints:
        module_id = endpoint_module_id(parsed, ep)
        module = modules_by_id.get(module_id or "")
        if module is None:
            continue
        text = files.get(module.path, "")
        line = None
        extra: dict = {}
        handler = functions_by_id.get(ep.handler_function_id or "")
        if ep.framework_annotation and ep.framework_annotation.startswith("@") and handler:
            # NestJS: the decorated method's own name, at the start of a member line.
            m = re.search(rf"^\s*(?:public\s+|private\s+|protected\s+)?(?:async\s+)?{re.escape(handler.name)}\s*\(", text, re.MULTILINE)
            if m:
                line = line_of(text, m.start())
        else:
            method = ep.method.value.lower() if hasattr(ep.method, "value") else str(ep.method).lower()
            if module.path not in calls_cache:
                calls_cache[module.path] = _express_route_calls(text)
            best, best_score = None, 0
            for call in calls_cache[module.path]:
                literal = call["path"]
                if call["method"] not in (method, "all") or call["offset"] in used[module.path]:
                    continue
                # Exact path, then a non-root suffix (router mounted under a prefix),
                # then a root route ('/' mounted somewhere) -- best match wins.
                stripped = literal.rstrip("/")
                score = 3 if ep.path == literal else 2 if stripped and ep.path.endswith(stripped) else 1 if not stripped else 0
                if call["method"] == "all":
                    score -= 0.5
                if score > best_score:
                    best, best_score = call, score
            if best is not None:
                call = best
                used[module.path].add(call["offset"])
                line = line_of(text, call["offset"])
                extra["handler_expr"] = call["handler_expr"]
                extra["middleware"] = call["middleware"]
                obj = call["handler_expr"].split(".", 1)[0]
                binding = bindings_cache.setdefault(module.path, _bindings(text))
                if obj in binding:
                    target = _resolve_relative(module.path, binding[obj], known_paths)
                    if target:
                        extra["handler_module_id"] = path_to_id[target]
        out[ep.id] = {"module_id": module.id, "path": module.path, "line": line, **extra}
    return out


def _bindings(text: str) -> dict[str, str]:
    out = {}
    for m in _REQUIRE_BINDING_RE.finditer(text):
        name, src = (m.group("name"), m.group("src")) if m.group("name") else (m.group("iname"), m.group("isrc"))
        out[name] = src
    return out


def compute_insights(parsed: ParsedRepository, files: dict[str, str]) -> dict:
    entities = extract_entities(files)
    entity_names = {e["name"] for e in entities}
    path_to_module = {m.path: m.id for m in parsed.modules}
    for e in entities:
        e["module_id"] = path_to_module.get(e["source_path"])

    return {
        "layers": {m.id: classify_layer(m.path) for m in parsed.modules},
        "entities": entities,
        "injections": _injections(parsed, files, entity_names),
        "endpoint_locations": _endpoint_locations(parsed, files),
        "stats": {
            "files": len(parsed.modules),
            "classes": len(parsed.classes),
            "functions": len(parsed.functions),
            "endpoints": len(parsed.api_endpoints),
            "entities": len(entities),
            "internal_imports": len(parsed.dependencies.internal),
            "external_dependencies": len(parsed.dependencies.external),
            "lines_of_code": sum(t.count("\n") + 1 for p, t in files.items() if p in path_to_module),
        },
    }
