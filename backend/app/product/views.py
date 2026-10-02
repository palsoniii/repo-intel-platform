"""
Builds every dashboard view from a stored analysis (ParsedRepository + insights).
Pure functions of their inputs: no Neo4j, no Ollama, no filesystem.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from app.product.dependency_catalog import describe_dependency
from app.product.insights import LAYER_LABELS, endpoint_module_id
from app.schemas.parser_schema import ParsedRepository

LAYER_ORDER = ["entry", "module", "route", "middleware", "service", "data", "contract", "config", "util", "other", "test"]


def _method(ep) -> str:
    return ep.method.value if hasattr(ep.method, "value") else str(ep.method)


# ---------------------------------------------------------------------------
# Knowledge graph (Cytoscape elements)
# ---------------------------------------------------------------------------


def knowledge_graph(parsed: ParsedRepository, insights: dict) -> dict:
    layers = insights.get("layers", {})
    nodes: list[dict] = []
    edges: list[dict] = []
    module_paths = {m.id: m.path for m in parsed.modules}

    def node(id_: str, kind: str, label: str, **data):
        nodes.append({"data": {"id": id_, "kind": kind, "label": label, **data}})

    def edge(src: str, dst: str, kind: str):
        edges.append({"data": {"id": f"{kind}:{src}->{dst}", "source": src, "target": dst, "kind": kind}})

    for m in parsed.modules:
        node(m.id, "file", m.path.rsplit("/", 1)[-1], path=m.path, layer=layers.get(m.id, "other"))
    for e in parsed.dependencies.internal:
        if e.from_module_id in module_paths and e.to_module_id in module_paths:
            edge(e.from_module_id, e.to_module_id, "imports")

    class_ids = set()
    for c in parsed.classes:
        class_ids.add(c.id)
        node(c.id, "class", c.name, path=module_paths.get(c.module_id), layer=layers.get(c.module_id, "other"))
        edge(c.module_id, c.id, "defines")
    for c in parsed.classes:
        for iface in c.interfaces_implemented:
            if iface in class_ids:
                edge(c.id, iface, "implements")

    function_ids = set()
    for f in parsed.functions:
        # Free functions that nothing routes to add noise without structure; keep
        # methods (owned by a class) and route handlers.
        if f.class_id is None and not f.is_api_handler:
            continue
        function_ids.add(f.id)
        node(f.id, "function", f.name, path=module_paths.get(f.module_id), layer=layers.get(f.module_id, "other"))
        edge(f.class_id or f.module_id, f.id, "has_method" if f.class_id else "defines")

    for ep in parsed.api_endpoints:
        label = f"{_method(ep)} {ep.path}"
        node(ep.id, "endpoint", label, method=_method(ep), route=ep.path, layer="route")
        if ep.handler_function_id and ep.handler_function_id in function_ids:
            edge(ep.id, ep.handler_function_id, "handled_by")
        else:
            module_id = endpoint_module_id(parsed, ep)
            if module_id in module_paths:
                edge(ep.id, module_id, "declared_in")

    entity_ids: dict[str, str] = {}
    for i, ent in enumerate(insights.get("entities", [])):
        eid = f"entity_{i}"
        entity_ids[ent["name"]] = eid
        node(eid, "entity", ent["name"], orm=ent["orm"], path=ent["source_path"], layer="data")
        if ent.get("module_id"):
            edge(ent["module_id"], eid, "defines")
    for ent in insights.get("entities", []):
        for r in ent["relations"]:
            if r["target"] in entity_ids and r["target"] != ent["name"]:
                edge(entity_ids[ent["name"]], entity_ids[r["target"]], "relates_to")

    for inj in insights.get("injections", []):
        target = inj["to_class_id"] if inj["to_kind"] == "class" else entity_ids.get(inj["to_name"])
        if target:
            edge(inj["from_class_id"], target, "injects")

    # Edges may repeat (e.g. a class defined and also re-exported); keep one of each.
    unique = {e["data"]["id"]: e for e in edges}
    return {"nodes": nodes, "edges": list(unique.values())}


# ---------------------------------------------------------------------------
# Architecture diagram (Mermaid)
# ---------------------------------------------------------------------------

_MAX_FILE_NODES = 45


def _mermaid_id(raw: str) -> str:
    return "n_" + re.sub(r"\W", "_", raw)


def _mermaid_label(text: str) -> str:
    return text.replace('"', "'")


def architecture_diagram(parsed: ParsedRepository, insights: dict, include_tests: bool = False) -> dict:
    """Layered flowchart: one subgraph per architectural layer. Small repos show one
    node per file; larger ones collapse each layer's files by directory so the
    diagram stays readable, with edge labels counting the imports they stand for."""
    layers = insights.get("layers", {})
    modules = [m for m in parsed.modules if include_tests or layers.get(m.id) != "test"]
    if not modules:
        return {"mermaid": 'graph LR\n  empty["No source files found"]', "grouped": False, "node_count": 0,
                "edge_count": 0, "graph": {"nodes": [], "links": []}}

    grouped = len(modules) > _MAX_FILE_NODES

    def group_key(m) -> str:
        layer = layers.get(m.id, "other")
        if not grouped:
            return m.id
        directory = m.path.rsplit("/", 1)[0] if "/" in m.path else "(root)"
        return f"{layer}:{directory}"

    group_of = {m.id: group_key(m) for m in modules}
    members: dict[str, list] = defaultdict(list)
    for m in modules:
        members[group_of[m.id]].append(m)

    by_layer: dict[str, list[str]] = defaultdict(list)
    for key, ms in members.items():
        by_layer[layers.get(ms[0].id, "other")].append(key)

    lines = ["graph LR"]
    for layer in LAYER_ORDER:
        keys = by_layer.get(layer)
        if not keys:
            continue
        lines.append(f'  subgraph L_{layer}["{LAYER_LABELS[layer]}"]')
        for key in sorted(keys):
            ms = members[key]
            if grouped:
                directory = key.split(":", 1)[1]
                label = f"{directory}/ ({len(ms)} file{'s' if len(ms) != 1 else ''})"
            else:
                label = ms[0].path
            lines.append(f'    {_mermaid_id(key)}["{_mermaid_label(label)}"]')
        lines.append("  end")

    counts: Counter = Counter()
    for e in parsed.dependencies.internal:
        a, b = group_of.get(e.from_module_id), group_of.get(e.to_module_id)
        if a and b and a != b:
            counts[(a, b)] += 1
    for (a, b), n in sorted(counts.items()):
        arrow = f"-->|{n}|" if grouped and n > 1 else "-->"
        lines.append(f"  {_mermaid_id(a)} {arrow} {_mermaid_id(b)}")

    for layer in (l for l in LAYER_ORDER if l in by_layer):
        lines.append(f"  style L_{layer} fill:transparent,stroke-dasharray:4 3")

    layer_index = {l: i for i, l in enumerate(LAYER_ORDER)}
    nodes = []
    for key, ms in members.items():
        layer = layers.get(ms[0].id, "other")
        label = (key.split(":", 1)[1] + "/") if grouped else ms[0].path.rsplit("/", 1)[-1]
        nodes.append({
            "id": key, "label": label, "layer": layer, "files": len(ms),
            "path": None if grouped else ms[0].path,
            "title": key.split(":", 1)[1] if grouped else ms[0].path,
        })
    nodes.sort(key=lambda n: (layer_index.get(n["layer"], 99), n["title"]))
    links = [{"source": a, "target": b, "count": n} for (a, b), n in sorted(counts.items())]
    return {
        "mermaid": "\n".join(lines),
        "grouped": grouped,
        "node_count": len(members),
        "edge_count": len(counts),
        "graph": {"nodes": nodes, "links": links},
    }


def nest_module_map(parsed: ParsedRepository, insights: dict) -> dict | None:
    """NestJS-only: how the app's @Module files import each other -- the closest thing
    a Nest app has to a declared architecture."""
    if (parsed.metadata.detected_framework or "").lower() != "nestjs":
        return None
    module_files = {m.id: m for m in parsed.modules if m.path.endswith(".module.ts")}
    if not module_files:
        return None
    lines = ["graph TD"]
    for mid, m in sorted(module_files.items(), key=lambda kv: kv[1].path):
        name = m.path.rsplit("/", 1)[-1].replace(".module.ts", "")
        label = name[:1].upper() + name[1:] + "Module"
        shape = f'(["{_mermaid_label(label)}"])' if name == "app" else f'["{_mermaid_label(label)}"]'
        lines.append(f"  {_mermaid_id(mid)}{shape}")
    edges = 0
    for e in parsed.dependencies.internal:
        if e.from_module_id in module_files and e.to_module_id in module_files:
            lines.append(f"  {_mermaid_id(e.from_module_id)} --> {_mermaid_id(e.to_module_id)}")
            edges += 1
    return {"mermaid": "\n".join(lines), "modules": len(module_files), "edges": edges}


# ---------------------------------------------------------------------------
# Data models (Mermaid ER diagram)
# ---------------------------------------------------------------------------


def _er_word(text: str) -> str:
    return re.sub(r"\W", "_", text).strip("_") or "x"


def er_diagram(insights: dict) -> dict:
    entities = insights.get("entities", [])
    if not entities:
        return {"mermaid": None, "entities": []}
    names = {e["name"] for e in entities}
    lines = ["erDiagram"]
    for e in entities:
        lines.append(f"  {_er_word(e['name'])} {{")
        for f in e["fields"][:25]:
            lines.append(f"    {_er_word(f['type'])} {_er_word(f['name'])}")
        if not e["fields"]:
            lines.append("    _ unknown_fields")
        lines.append("  }")
    seen = set()
    for e in entities:
        for r in e["relations"]:
            if r["target"] not in names:
                continue
            key = (e["name"], r["target"], r["field"])
            if key in seen:
                continue
            seen.add(key)
            # "one": many of this entity point at one target; "many": this one owns many.
            arrow = "||--o{" if r["kind"] == "many" else "}o--||"
            label = r["field"] or "relates"
            lines.append(f'  {_er_word(e["name"])} {arrow} {_er_word(r["target"])} : "{_mermaid_label(label)}"')
    return {"mermaid": "\n".join(lines), "entities": entities}


# ---------------------------------------------------------------------------
# API explorer + request-flow trace
# ---------------------------------------------------------------------------


def endpoints_view(parsed: ParsedRepository, insights: dict) -> list[dict]:
    functions = {f.id: f for f in parsed.functions}
    classes = {c.id: c for c in parsed.classes}
    locations = insights.get("endpoint_locations", {})
    out = []
    for ep in parsed.api_endpoints:
        fn = functions.get(ep.handler_function_id or "")
        cls = classes.get(fn.class_id) if fn and fn.class_id else None
        loc = locations.get(ep.id, {})
        out.append(
            {
                "id": ep.id,
                "method": _method(ep),
                "path": ep.path,
                "handler": fn.name if fn else None,
                "controller": cls.name if cls else None,
                "file": loc.get("path"),
                "line": loc.get("line"),
                "annotation": ep.framework_annotation,
                "trace": trace_endpoint(parsed, insights, ep),
            }
        )
    out.sort(key=lambda e: (e["path"], e["method"]))
    return out


def trace_endpoint(parsed: ParsedRepository, insights: dict, ep) -> list[dict]:
    """The request's path through the code, as far as static structure shows it:
    endpoint -> handler -> its class/file -> injected services (and what they inject)
    -> data models. Express has no injection, so after the handler's file this
    follows imports into service/data-layer files instead."""
    functions = {f.id: f for f in parsed.functions}
    classes = {c.id: c for c in parsed.classes}
    modules = {m.id: m for m in parsed.modules}
    layers = insights.get("layers", {})
    injections: dict[str, list[dict]] = defaultdict(list)
    for inj in insights.get("injections", []):
        injections[inj["from_class_id"]].append(inj)
    entity_by_module: dict[str, list[str]] = defaultdict(list)
    for ent in insights.get("entities", []):
        if ent.get("module_id"):
            entity_by_module[ent["module_id"]].append(ent["name"])

    steps: list[dict] = [{"kind": "endpoint", "label": f"{_method(ep)} {ep.path}", "depth": 0}]
    fn = functions.get(ep.handler_function_id or "")
    module_id = fn.module_id if fn else endpoint_module_id(parsed, ep)
    if fn:
        cls = classes.get(fn.class_id) if fn.class_id else None
        steps.append({
            "kind": "handler",
            "label": f"{cls.name}.{fn.name}()" if cls else f"{fn.name}()",
            "file": modules[fn.module_id].path if fn.module_id in modules else None,
            "depth": 1,
        })
        if cls:
            seen = {cls.id}
            frontier = [(cls.id, 2)]
            while frontier:
                cid, depth = frontier.pop(0)
                for inj in injections.get(cid, []):
                    if inj["to_kind"] == "entity":
                        steps.append({"kind": "entity", "label": inj["to_name"], "depth": depth})
                        continue
                    tid = inj["to_class_id"]
                    if tid in seen or tid not in classes or depth > 4:
                        continue
                    seen.add(tid)
                    target = classes[tid]
                    steps.append({
                        "kind": "service",
                        "label": target.name,
                        "file": modules[target.module_id].path if target.module_id in modules else None,
                        "depth": depth,
                    })
                    frontier.append((tid, depth + 1))
            if len(steps) > 2:
                return steps
    elif module_id in modules:
        loc = insights.get("endpoint_locations", {}).get(ep.id, {})
        for mw in loc.get("middleware", []):
            steps.append({"kind": "middleware", "label": mw, "file": modules[module_id].path, "depth": 1})
        handler_module = loc.get("handler_module_id")
        steps.append({
            "kind": "handler",
            "label": loc.get("handler_expr") or "inline handler",
            "file": modules[handler_module].path if handler_module in modules else modules[module_id].path,
            "depth": 1,
        })
        if handler_module in modules:
            module_id = handler_module

    # Import-following fallback (Express, or a Nest class with nothing injected).
    if module_id not in modules:
        return steps
    imports = defaultdict(list)
    for e in parsed.dependencies.internal:
        imports[e.from_module_id].append(e.to_module_id)
    found: list[dict] = []
    seen_mod = {module_id}
    frontier = [(module_id, 2)]
    while frontier:
        mid, depth = frontier.pop(0)
        if depth > 4:
            continue
        for nxt in imports.get(mid, []):
            if nxt in seen_mod or nxt not in modules:
                continue
            layer = layers.get(nxt, "other")
            # Routes files import each other to mount sub-routers; following those
            # would list every route in the app. Controllers are the exception.
            is_controller = "controller" in modules[nxt].path.lower()
            is_barrel = re.search(r"(^|/)index\.[jt]s$", modules[nxt].path) is not None
            if layer not in ("service", "data") and not is_controller and not is_barrel:
                continue
            seen_mod.add(nxt)
            frontier.append((nxt, depth + (0 if is_barrel else 1)))
            if is_barrel:
                continue  # pass through re-export files without listing them
            if entity_by_module.get(nxt):
                for ent in entity_by_module[nxt]:
                    found.append({"kind": "entity", "label": ent, "file": modules[nxt].path, "depth": depth})
                continue
            kind = "handler" if is_controller else "service" if layer == "service" else "data"
            found.append({"kind": kind, "label": modules[nxt].path.rsplit("/", 1)[-1],
                          "file": modules[nxt].path, "depth": depth})

    # Barrel files fan out to everything; keep the steps that look related to this
    # endpoint (shared words with the handler name or route), then the nearest ones.
    loc = insights.get("endpoint_locations", {}).get(ep.id, {})
    focus = set(_words(f"{loc.get('handler_expr') or ''} {ep.path} {fn.name if fn else ''}"))
    def relevance(step: dict) -> tuple:
        overlap = len(focus & set(_words(step["file"] or step["label"])))
        return (-overlap, step["depth"], step["kind"] == "entity")
    found.sort(key=relevance)
    picked = found[:6]
    picked.sort(key=lambda st: (st["depth"], st["kind"] == "entity"))
    return steps + picked


def _words(text: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    stop = {"js", "ts", "src", "app", "index", "api", "v1", "controller", "controllers", "route", "routes", "service", "services", "model", "models"}
    out = []
    for w in re.findall(r"[A-Za-z]{3,}", spaced):
        w = w.lower()
        if w in stop:
            continue
        out.append(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


# ---------------------------------------------------------------------------
# Dependencies, files, overview
# ---------------------------------------------------------------------------


def dependencies_view(parsed: ParsedRepository) -> list[dict]:
    out = []
    for d in parsed.dependencies.external:
        info = describe_dependency(d.name)
        out.append(
            {
                "name": d.name,
                "version": d.version,
                "dep_type": d.dep_type.value if hasattr(d.dep_type, "value") else str(d.dep_type),
                "category": info["category"],
                "description": info["description"],
            }
        )
    out.sort(key=lambda d: (d["dep_type"] != "runtime", d["category"] == "Other", d["category"], d["name"]))
    return out


def files_view(parsed: ParsedRepository, insights: dict, sizes: dict[str, int]) -> list[dict]:
    layers = insights.get("layers", {})
    classes_by_module = defaultdict(list)
    for c in parsed.classes:
        classes_by_module[c.module_id].append(c.name)
    imported_by = Counter(e.to_module_id for e in parsed.dependencies.internal)
    out = [
        {
            "id": m.id,
            "path": m.path,
            "layer": layers.get(m.id, "other"),
            "size": sizes.get(m.path, 0),
            "imports": len(m.imports),
            "imported_by": imported_by.get(m.id, 0),
            "classes": classes_by_module.get(m.id, []),
        }
        for m in parsed.modules
    ]
    # Non-module files that were stored for viewing (package.json, schema.prisma).
    module_paths = {m.path for m in parsed.modules}
    for path, size in sizes.items():
        if path not in module_paths:
            out.append({"id": f"extra:{path}", "path": path, "layer": "config", "size": size,
                        "imports": 0, "imported_by": 0, "classes": []})
    out.sort(key=lambda f: f["path"])
    return out


def layer_breakdown(parsed: ParsedRepository, insights: dict) -> list[dict]:
    layers = insights.get("layers", {})
    counts = Counter(layers.get(m.id, "other") for m in parsed.modules)
    return [
        {"layer": l, "label": LAYER_LABELS[l], "files": counts[l]}
        for l in LAYER_ORDER if counts.get(l)
    ]


def hotspots(parsed: ParsedRepository, limit: int = 8) -> list[dict]:
    """Most-imported files: the ones a newcomer should read first."""
    imported_by = Counter(e.to_module_id for e in parsed.dependencies.internal)
    paths = {m.id: m.path for m in parsed.modules}
    return [
        {"id": mid, "path": paths[mid], "imported_by": n}
        for mid, n in imported_by.most_common(limit) if mid in paths
    ]
