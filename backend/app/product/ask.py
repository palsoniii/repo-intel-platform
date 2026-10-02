"""
Ask-the-repo: answers a question about an analysed repository with the local model,
grounded in that repository's structure and source.

Retrieval is lexical and structural, not embedding-based: the question's terms are
matched against file paths, class/function names, endpoint paths and source text,
and the best files are sent with a compact structural overview (the same knowledge
graph the summary is written from). Exact identifier matching is what code questions
need most ("what does UsersService do?"), it needs no extra model or index, and the
UI can show exactly which files the answer was based on.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from typing import Iterator

from app.product.insights import LAYER_LABELS, endpoint_module_id
from app.schemas.parser_schema import ParsedRepository

CONTEXT_BUDGET_CHARS = 14_000
MAX_SOURCE_FILES = 5

STOPWORDS = set(
    """a an and are as at be by can do does for from has have how i in is it its me
    my of on or so that the their them then there these this to use used uses using
    was what when where which who why will with you your show tell explain about
    repo repository code project app application file files work works""".split()
)

SYSTEM_PROMPT = """You are a senior engineer explaining a codebase to a colleague. \
Answer the question using ONLY the repository context provided. Reference files by \
their path in backticks (for example `src/users/users.service.ts`) so the reader can \
open them. If the context does not contain the answer, say so plainly and say which \
part of the codebase would be the place to look -- never invent files, functions, \
endpoints or behaviour. Be concise: a short paragraph or a few bullet points, with a \
small code excerpt only when it genuinely helps."""


def _terms(text: str) -> list[str]:
    # Split identifiers too: "UsersService" -> users, service; "user_id" -> user, id.
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    words = re.findall(r"[A-Za-z][A-Za-z0-9]+", spaced)
    out = []
    for w in words:
        w = w.lower()
        if w in STOPWORDS or len(w) < 3:
            continue
        out.append(w)
        if w.endswith("s") and len(w) > 4:
            out.append(w[:-1])
    return out


def retrieve(parsed: ParsedRepository, insights: dict, files: dict[str, str], question: str) -> list[dict]:
    terms = set(_terms(question))
    raw_tokens = {t for t in re.findall(r"[\w./:-]+", question) if len(t) > 2}
    if not terms and not raw_tokens:
        return []

    names_by_module: dict[str, list[str]] = defaultdict(list)
    for c in parsed.classes:
        names_by_module[c.module_id].append(c.name)
    for f in parsed.functions:
        names_by_module[f.module_id].append(f.name)
    routes_by_module: dict[str, list[str]] = defaultdict(list)
    for ep in parsed.api_endpoints:
        mid = endpoint_module_id(parsed, ep)
        if mid:
            routes_by_module[mid].append(ep.path)
    for ent in insights.get("entities", []):
        if ent.get("module_id"):
            names_by_module[ent["module_id"]].append(ent["name"])

    scored: list[tuple[float, str, str]] = []
    for m in parsed.modules:
        text = files.get(m.path)
        if not text:
            continue
        score = 0.0
        path_terms = set(_terms(m.path))
        score += 4 * len(terms & path_terms)
        name_terms = set(_terms(" ".join(names_by_module.get(m.id, []))))
        score += 3 * len(terms & name_terms)
        route_terms = set(_terms(" ".join(routes_by_module.get(m.id, []))))
        score += 3 * len(terms & route_terms)
        # An identifier typed verbatim ("UsersService", "/auth/login") is a strong signal.
        exact = sum(1 for tok in raw_tokens if tok in text)
        score += 5 * exact
        body = Counter(_terms(text))
        score += sum(math.log1p(body[t]) for t in terms)
        if insights.get("layers", {}).get(m.id) == "test":
            score *= 0.4
        if score > 0:
            scored.append((score, m.id, m.path))

    scored.sort(reverse=True)
    if not scored:
        return []
    best = scored[0][0]
    return [
        {"module_id": mid, "path": path, "score": round(s, 2)}
        for s, mid, path in scored[:MAX_SOURCE_FILES]
        if s >= best * 0.25
    ]


def _excerpt(text: str, terms: set[str], budget: int) -> str:
    if len(text) <= budget:
        return text
    lines = text.splitlines()
    hits = [i for i, line in enumerate(lines) if terms & set(_terms(line))]
    if not hits:
        return text[:budget] + "\n// ... (truncated)"
    keep: set[int] = set()
    for i in hits:
        keep.update(range(max(0, i - 6), min(len(lines), i + 12)))
    out, size, last = [], 0, -2
    for i in sorted(keep):
        if i != last + 1:
            out.append("// ...")
        out.append(f"{lines[i]}")
        size += len(lines[i]) + 1
        last = i
        if size > budget:
            break
    return "\n".join(out)


def _overview(parsed: ParsedRepository, insights: dict, files: dict[str, str]) -> str:
    md = parsed.metadata
    layers = insights.get("layers", {})
    lines = [
        f"Repository: {md.name} ({md.detected_framework or 'unknown framework'}, {md.detected_language})",
        f"Files: {len(parsed.modules)}, classes: {len(parsed.classes)}, endpoints: {len(parsed.api_endpoints)}",
    ]
    by_layer: dict[str, list[str]] = defaultdict(list)
    for m in parsed.modules:
        by_layer[layers.get(m.id, "other")].append(m.path)
    lines.append("Files by layer:")
    for layer, paths in by_layer.items():
        if layer == "test":
            continue
        shown = ", ".join(sorted(paths)[:25]) + (f", ... (+{len(paths) - 25})" if len(paths) > 25 else "")
        lines.append(f"- {LAYER_LABELS.get(layer, layer)}: {shown}")
    if parsed.api_endpoints:
        functions = {f.id: f.name for f in parsed.functions}
        lines.append("Endpoints:")
        for ep in parsed.api_endpoints[:60]:
            method = ep.method.value if hasattr(ep.method, "value") else ep.method
            handler = functions.get(ep.handler_function_id or "", "inline handler")
            lines.append(f"- {method} {ep.path} -> {handler}")
    ents = insights.get("entities", [])
    if ents:
        lines.append("Data models: " + ", ".join(f"{e['name']} ({e['orm']}, {e['source_path']})" for e in ents[:30]))
    inj = insights.get("injections", [])
    if inj:
        classes = {c.id: c.name for c in parsed.classes}
        pairs = [f"{classes.get(i['from_class_id'], '?')} -> {i['to_name']}" for i in inj[:40]]
        lines.append("Dependency injection: " + "; ".join(pairs))
    runtime = [d.name for d in parsed.dependencies.external if getattr(d.dep_type, "value", d.dep_type) != "dev"]
    if runtime:
        lines.append("Runtime packages: " + ", ".join(runtime[:40]))
    readme = files.get("README.md") or files.get("readme.md") or files.get("README")
    if readme:
        lines.append("README (start):\n" + readme[:1200])
    return "\n".join(lines)


def build_prompt(parsed: ParsedRepository, insights: dict, files: dict[str, str], question: str) -> tuple[str, list[dict]]:
    sources = retrieve(parsed, insights, files, question)
    overview = _overview(parsed, insights, files)
    budget = max(2000, CONTEXT_BUDGET_CHARS - len(overview))
    terms = set(_terms(question))
    blocks = []
    per_file = budget // max(1, len(sources)) if sources else 0
    for s in sources:
        blocks.append(f"--- {s['path']} ---\n{_excerpt(files[s['path']], terms, per_file)}")
    context = overview + ("\n\nRelevant source files:\n" + "\n\n".join(blocks) if blocks else "")
    user = f"Repository context:\n{context}\n\nQuestion: {question}"
    return user, sources


def stream_answer(
    parsed: ParsedRepository,
    insights: dict,
    files: dict[str, str],
    question: str,
    history: list[dict] | None = None,
    model: str | None = None,
) -> Iterator[str]:
    """Yields NDJSON lines: one {"type":"sources"}, many {"type":"token"}, then
    {"type":"done"} or {"type":"error"}."""
    import ollama

    from app.product.jobs import summary_model

    model = model or summary_model()
    user_prompt, sources = build_prompt(parsed, insights, files, question)
    yield json.dumps({"type": "sources", "sources": sources, "model": model}) + "\n"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-4:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": str(turn["content"])[:2000]})
    messages.append({"role": "user", "content": user_prompt})

    client = ollama.Client(host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"), timeout=600)
    options = {"temperature": 0.2, "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "8192").split("#")[0])}
    try:
        stats = {}
        for chunk in client.chat(model=model, messages=messages, options=options, stream=True):
            text = chunk.message.content or ""
            if text:
                yield json.dumps({"type": "token", "text": text}) + "\n"
            if chunk.done:
                stats = {
                    "input_tokens": chunk.prompt_eval_count,
                    "output_tokens": chunk.eval_count,
                    "duration_ms": int((chunk.total_duration or 0) / 1e6),
                }
        yield json.dumps({"type": "done", **stats}) + "\n"
    except Exception as e:  # noqa: BLE001
        from app.product.jobs import _friendly_model_error

        yield json.dumps({"type": "error", "message": _friendly_model_error(str(e), model)}) + "\n"
