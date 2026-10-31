"""
Ask-the-repo: answers a question about an analysed repository with the dashboard's
model (Groq or local, see llm.py), grounded in that repository's structure and source.

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
import re
from collections import Counter, defaultdict
from typing import Iterator

from app.product.insights import LAYER_LABELS, endpoint_module_id
from app.schemas.parser_schema import ParsedRepository

# Sized for an 8k-token window: ~4.5k tokens of context (overview plus file
# excerpts), the system prompt, up to four short history turns, and the answer.
CONTEXT_BUDGET_CHARS = 13_000
MAX_OVERVIEW_CHARS = 5_000
MAX_ANSWER_TOKENS = 700
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
open them. Only mention files that appear in the context. Only quote code that \
appears verbatim under "Relevant source files" -- never reconstruct or guess what a \
file contains from its name. If the context does not contain the answer, say so \
plainly and point to the file(s) most likely to hold it. Be concise: under 200 words, \
a short paragraph or a few bullet points."""


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


# A question names a concept ("authentication"); the code names its parts (auth.js,
# passport, jwt). Each concept expands to the identifiers it is usually built from.
CONCEPTS: dict[str, set[str]] = {
    "auth": {"auth", "authentication", "authenticate", "authorization", "authorize", "login",
             "logout", "jwt", "passport", "token", "session", "guard", "strategy", "password", "bcrypt"},
    "data": {"database", "db", "model", "entity", "schema", "repository", "mongoose", "sequelize",
             "typeorm", "prisma", "migration", "orm", "query", "persist", "store", "storage"},
    "error": {"error", "errors", "exception", "filter", "apierror", "catch", "handler", "fail"},
    "validation": {"validate", "validation", "validator", "dto", "joi", "pipe", "sanitize", "schema"},
    "config": {"config", "configuration", "env", "environment", "setting", "settings", "dotenv"},
    "mail": {"email", "mail", "mailer", "smtp", "nodemailer", "notification"},
    "test": {"test", "tests", "testing", "spec", "jest", "mocha", "e2e"},
    "route": {"route", "routes", "routing", "endpoint", "endpoints", "router", "controller", "api", "url"},
    "start": {"start", "entry", "bootstrap", "main", "server", "listen", "begin", "reading", "startup"},
    "upload": {"upload", "file", "multer", "storage", "s3"},
    "log": {"log", "logging", "logger", "winston", "morgan", "pino"},
}


def _expand(terms: set[str]) -> set[str]:
    out = set(terms)
    for group in CONCEPTS.values():
        if terms & group:
            out |= group
    return out


def _overlap(query: set[str], candidates: set[str]) -> int:
    """Exact matches, plus prefix matches of 4+ letters (auth ~ authentication)."""
    n = 0
    for c in candidates:
        if c in query or (len(c) >= 4 and any(q.startswith(c) or c.startswith(q) for q in query if len(q) >= 4)):
            n += 1
    return n


def _looks_like_identifier(tok: str) -> bool:
    return bool(re.search(r"[a-z][A-Z]|[/_.:]", tok)) and len(tok) > 3


def retrieve(parsed: ParsedRepository, insights: dict, files: dict[str, str], question: str) -> list[dict]:
    asked = set(_terms(question))
    terms = _expand(asked)
    raw_tokens = {t.strip(".,?!") for t in re.findall(r"[\w./:-]+", question)}
    raw_tokens = {t for t in raw_tokens if _looks_like_identifier(t)}
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

    orientation = bool(asked & {"start", "begin", "beginning", "reading", "overview", "architecture", "structure", "structured", "organised", "organized", "onboard", "onboarding"})
    imported_by = Counter(e.to_module_id for e in parsed.dependencies.internal)

    scored: list[tuple[float, str, str]] = []
    for m in parsed.modules:
        text = files.get(m.path)
        if not text:
            continue
        score = 0.0
        # Words the user actually typed count double over concept expansions.
        path_terms = set(_terms(m.path))
        score += 4 * _overlap(terms, path_terms) + 4 * _overlap(asked, path_terms)
        name_terms = set(_terms(" ".join(names_by_module.get(m.id, []))))
        score += 3 * _overlap(terms, name_terms) + 3 * _overlap(asked, name_terms)
        route_terms = set(_terms(" ".join(routes_by_module.get(m.id, []))))
        score += 3 * _overlap(terms, route_terms)
        # An identifier typed verbatim ("UsersService", "/auth/login") is a strong signal.
        exact = sum(1 for tok in raw_tokens if tok in text)
        score += 5 * exact
        body = Counter(_terms(text))
        score += sum(math.log1p(body[t]) for t in terms) + sum(math.log1p(body[t]) for t in asked)
        layer = insights.get("layers", {}).get(m.id)
        if orientation:
            # "Where do I start?" is answered by structure, not by matching words:
            # the entry point, the module wiring, and the files everything imports.
            score = score * 0.3 + (12 if layer == "entry" else 6 if layer == "module" and m.path.endswith("app.module.ts") else 0)
            score += 2.5 * math.log1p(imported_by.get(m.id, 0))
        if layer == "test":
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
        if s >= best * 0.2
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


def system_message(parsed: ParsedRepository, insights: dict, files: dict[str, str]) -> str:
    """Instructions plus the repository overview. Identical for every question about
    the same repository, which is the point: Ollama skips re-reading a prompt prefix
    it has just processed, so after prime() each question pays only for its own
    files."""
    return f"{SYSTEM_PROMPT}\n\nRepository overview:\n{_overview(parsed, insights, files)[:MAX_OVERVIEW_CHARS]}"


def build_prompt(parsed: ParsedRepository, insights: dict, files: dict[str, str], question: str) -> tuple[str, list[dict]]:
    """The per-question part: the most relevant source excerpts, then the question."""
    sources = retrieve(parsed, insights, files, question)
    terms = _expand(set(_terms(question)))
    # The overview now lives in the system message, but it still shares the budget.
    overview_len = len(_overview(parsed, insights, files)[:MAX_OVERVIEW_CHARS])
    budget = max(2000, CONTEXT_BUDGET_CHARS - overview_len)
    per_file = budget // max(1, len(sources)) if sources else 0
    blocks = [f"--- {s['path']} ---\n{_excerpt(files[s['path']], terms, per_file)}" for s in sources]
    context = "Relevant source files:\n" + "\n\n".join(blocks) if blocks else "No source file matched the question."
    return f"{context}\n\nQuestion: {question}", sources


def prime(parsed: ParsedRepository, insights: dict, files: dict[str, str]) -> None:
    """Has the local model read this repository's overview now, while the user is
    still choosing a question, so the first answer starts sooner. Groq reads a prompt
    fast enough not to need it."""
    from app.product import llm

    if llm.provider() == "ollama":
        llm.ollama_prime([
            {"role": "system", "content": system_message(parsed, insights, files)},
            {"role": "user", "content": "Ready."},
        ])


def max_tokens() -> int:
    """A cap on the answer, not its length: the prompt asks for under 200 words
    (~300 tokens). Reasoning models on Groq think inside the same budget, so they get
    more room to keep that thinking from cutting the answer off."""
    from app.product import llm

    return MAX_ANSWER_TOKENS if llm.provider() == "ollama" else 2000


def question_key(question: str) -> str:
    return " ".join(re.findall(r"[a-z0-9/:._-]+", question.lower()))


def _replay(cached: dict) -> Iterator[str]:
    """Streams a stored answer back in the same event shape as a live one."""
    yield json.dumps({
        "type": "sources", "sources": cached["sources"], "model": cached["model"],
        "provider": cached.get("provider", "ollama"), "cached": True,
    }) + "\n"
    text = cached["answer"]
    for i in range(0, len(text), 24):
        yield json.dumps({"type": "token", "text": text[i : i + 24]}) + "\n"
    yield json.dumps({"type": "done", "cached": True, **cached.get("stats", {})}) + "\n"


def stream_answer(
    parsed: ParsedRepository,
    insights: dict,
    files: dict[str, str],
    question: str,
    history: list[dict] | None = None,
    analysis_id: str | None = None,
    use_cache: bool = True,
) -> Iterator[str]:
    """Yields NDJSON lines: one {"type":"sources"}, many {"type":"token"}, then
    {"type":"done"} or {"type":"error"}.

    A first question (no history) that was asked before about the same analysis is
    replayed from the store instantly; follow-ups always go to the model, because
    their answer depends on the conversation."""
    from app.product import llm, store

    cacheable = analysis_id is not None and not history
    if cacheable and use_cache:
        cached = store.get_cached_answer(analysis_id, question_key(question))
        if cached:
            yield from _replay(cached)
            return

    user_prompt, sources = build_prompt(parsed, insights, files, question)
    yield json.dumps({"type": "sources", "sources": sources, "model": llm.model(), "provider": llm.provider()}) + "\n"

    messages = [{"role": "system", "content": system_message(parsed, insights, files)}]
    for turn in (history or [])[-4:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": str(turn["content"])[:1200]})
    messages.append({"role": "user", "content": user_prompt})

    answer: list[str] = []
    result = llm.StreamResult()
    try:
        for text in llm.stream(messages, max_tokens(), result):
            answer.append(text)
            yield json.dumps({"type": "token", "text": text}) + "\n"
        # Who actually answered: a Groq failure before the first word falls back to
        # the local model.
        done = {**result.stats, "model": result.model, "provider": result.provider}
        if cacheable and answer:
            store.save_cached_answer(
                analysis_id, question_key(question),
                {"answer": "".join(answer), "sources": sources, "model": result.model,
                 "provider": result.provider, "stats": result.stats},
            )
        yield json.dumps({"type": "done", **done}) + "\n"
    except Exception as e:  # noqa: BLE001
        yield json.dumps({"type": "error", "message": str(e)}) + "\n"


def suggested_questions(parsed: ParsedRepository, insights: dict) -> list[str]:
    qs: list[str] = ["Where should a new developer start reading this codebase?"]
    services = [c.name for c in parsed.classes if c.name.endswith("Service")]
    if services:
        qs.append(f"What does {services[0]} do?")
    posts = [ep for ep in parsed.api_endpoints if getattr(ep.method, "value", ep.method) == "POST"]
    ep = posts[0] if posts else (parsed.api_endpoints[0] if parsed.api_endpoints else None)
    if ep:
        qs.append(f"What happens when a request hits {getattr(ep.method, 'value', ep.method)} {ep.path}?")
    paths = " ".join(m.path.lower() for m in parsed.modules)
    if any(k in paths for k in ("auth", "passport", "jwt", "login")):
        qs.append("How does authentication work?")
    if insights.get("entities"):
        qs.append("Which data models exist and how are they related?")
    if any(k in paths for k in ("middleware", "error", "exception", "filter")):
        qs.append("How are errors handled?")
    return qs[:5]
