"""T2 -- parser-grounded oracle. No LLM, no GPU, no network.

WHY THIS EXISTS
Coverage is not, for the most part, a judgment call. "Does this summary mention
`GET /tasks`?" is string matching with alias handling. The LLM judge was introduced to
credit *indirect* mention, but the harness bug (see coverage.py `_canon`) showed the
judge's score was dominated by its string-formatting compliance rather than its reading.
This module computes coverage deterministically so the judges can be measured AGAINST a
fixed reference instead of against each other.

It scores the SAME fact list the judges saw -- build_coverable_facts() is imported, not
reimplemented -- so oracle and judge numbers are directly comparable per row.

TWO TIERS, both always reported:
  STRICT  -- normalised exact identifier match only.
  LENIENT -- adds camelCase splitting, path-parameter wildcards, scope-stripped packages.
The STRICT/LENIENT gap is itself a measurement of how much surface-form variation there is.

VALIDITY LIMITS -- these belong in the results section, not a footnote:
  1. The coverage oracle CANNOT credit genuine paraphrase. "Manages the app's tasks" does
     not match `GET /tasks`. It is a LOWER BOUND and it systematically under-credits
     abstraction: a summary that lists identifiers outscores one that explains them
     better. This narrows the question from "does the summary convey the repository" to
     "does it contain the identifiers". Say so explicitly.
  2. The hallucination oracle OVER-flags (generic words surviving the stoplist) and
     UNDER-flags (false claims made in prose that carry no identifier).
  3. Therefore the oracle<->judge gap is NOT pure judge error -- part of it is paraphrase
     the oracle cannot see. Quantify it by sampling disagreements (plan T7 item 6).
"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, "/app")

from pydantic import BaseModel

from app.evaluation.coverage import build_coverable_facts
from app.schemas.parser_schema import ParsedRepository

# --------------------------------------------------------------------------- models


class FactMatch(BaseModel):
    fact: str
    category: str
    strict: bool
    lenient: bool
    rule: str  # which rule fired; "" if uncovered


class OracleCoverage(BaseModel):
    repo_name: str
    total_facts: int
    covered_strict: int
    covered_lenient: int
    coverage_strict: float
    coverage_lenient: float
    per_category_strict: dict[str, float]
    per_category_lenient: dict[str, float]
    rule_histogram: dict[str, int]
    missing_strict: list[str]
    missing_lenient: list[str]
    matches: list[FactMatch]


class OracleHallucination(BaseModel):
    repo_name: str
    total_candidates: int
    supported: int
    unsupported: int
    unsupported_identifier_rate: float
    unsupported_samples: list[str]


# ---------------------------------------------------------------------- primitives


def _wb(term: str, cs: bool = False) -> re.Pattern:
    """Word-boundary match. \\b fails next to '@', '/', '.', so use lookarounds on a
    code-identifier character class instead."""
    flags = 0 if cs else re.IGNORECASE
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])", flags)


def _camel_split(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return re.sub(r"[_\-]+", " ", s).lower().strip()


_PARAM = re.compile(r":[A-Za-z_]\w*|\{[^}]+\}|<[^>]+>")


def _path_regex(path: str) -> re.Pattern:
    """Route path -> regex with parameters wildcarded. '/users/:id' matches
    '/users/123' and '/users/{id}'. Trailing slash optional."""
    pieces, last = [], 0
    for m in _PARAM.finditer(path):
        pieces.append(re.escape(path[last:m.start()]))
        pieces.append(r"[^/\s`'\"]+")
        last = m.end()
    pieces.append(re.escape(path[last:]))
    body = "".join(pieces) if pieces else re.escape(path)
    return re.compile(body.rstrip("/") + r"/?(?![A-Za-z0-9_])", re.IGNORECASE)


# --------------------------------------------------------------------- fact matching


def match_fact(fact: str, summary: str) -> FactMatch:
    """Decide whether `summary` mentions `fact`, at both tiers."""
    category, _, value = fact.partition(":")
    category = category.strip()
    value = value.strip()
    strict = lenient = False
    rule = ""

    if category == "Framework":
        # "Express 4.18.2" -> match the name; version optional.
        name = value.split()[0] if value else ""
        if name and _wb(name).search(summary):
            strict = lenient = True
            rule = "framework_name"

    elif category == "Language":
        if value and _wb(value).search(summary):
            strict = lenient = True
            rule = "language_exact"
        elif value.lower() == "typescript" and _wb("ts").search(summary):
            lenient = True
            rule = "language_abbrev"
        elif value.lower() == "javascript" and _wb("js").search(summary):
            lenient = True
            rule = "language_abbrev"

    elif category == "Dependency":
        pkg = value
        if _wb(pkg).search(summary):
            strict = lenient = True
            rule = "dep_exact"
        elif pkg.startswith("@") and "/" in pkg:
            scope, sub = pkg[1:].split("/", 1)
            if _wb(scope + "/" + sub).search(summary):
                strict = lenient = True
                rule = "dep_unprefixed_scope"
            # LENIENT may strip the '@' but MUST still require the sub-name. Matching
            # bare 'nestjs' would fire on every NestJS summary and false-positive
            # essentially the entire corpus.
            elif _wb(scope).search(summary) and _wb(sub).search(summary):
                lenient = True
                rule = "dep_scope_and_sub"

    elif category == "Endpoint":
        parts = value.split(None, 1)
        if len(parts) == 2:
            method, path = parts[0].strip(), parts[1].strip()
            preg = _path_regex(path)
            m = preg.search(summary)
            if m:
                # STRICT wants the method adjacent to the path (allowing quoting/markup).
                window = summary[max(0, m.start() - 24):m.start()]
                if _wb(method).search(window):
                    strict = lenient = True
                    rule = "endpoint_method_path"
                else:
                    lenient = True
                    rule = "endpoint_path_only"

    elif category == "Class/Service":
        if _wb(value, cs=True).search(summary):
            strict = lenient = True
            rule = "class_exact_cs"
        elif _wb(value).search(summary):
            lenient = True
            rule = "class_exact_ci"
        else:
            split = _camel_split(value)
            if split and split != value.lower() and re.search(
                r"(?<![A-Za-z0-9_])" + re.escape(split) + r"(?![A-Za-z0-9_])",
                summary, re.IGNORECASE
            ):
                lenient = True
                rule = "class_camel_split"

    elif category == "Database entity":
        # Case-SENSITIVE: 'User' lowercased is far too generic to be evidence.
        if _wb(value, cs=True).search(summary):
            strict = lenient = True
            rule = "entity_exact_cs"
        elif _wb(value + "s", cs=True).search(summary):
            lenient = True
            rule = "entity_plural_cs"

    return FactMatch(fact=fact, category=category, strict=strict, lenient=lenient, rule=rule)


def score_coverage_oracle(parsed: ParsedRepository, summary_text: str) -> OracleCoverage:
    facts = build_coverable_facts(parsed)  # SAME list the judges scored
    if not facts:
        return OracleCoverage(
            repo_name=parsed.metadata.name, total_facts=0, covered_strict=0,
            covered_lenient=0, coverage_strict=1.0, coverage_lenient=1.0,
            per_category_strict={}, per_category_lenient={}, rule_histogram={},
            missing_strict=[], missing_lenient=[], matches=[],
        )

    matches = [match_fact(f, summary_text or "") for f in facts]
    cs = sum(1 for m in matches if m.strict)
    cl = sum(1 for m in matches if m.lenient)

    cat_s: dict[str, list[int]] = {}
    cat_l: dict[str, list[int]] = {}
    hist: dict[str, int] = {}
    for m in matches:
        cat_s.setdefault(m.category, []).append(1 if m.strict else 0)
        cat_l.setdefault(m.category, []).append(1 if m.lenient else 0)
        if m.rule:
            hist[m.rule] = hist.get(m.rule, 0) + 1

    return OracleCoverage(
        repo_name=parsed.metadata.name,
        total_facts=len(facts),
        covered_strict=cs,
        covered_lenient=cl,
        coverage_strict=round(cs / len(facts), 4),
        coverage_lenient=round(cl / len(facts), 4),
        per_category_strict={k: round(sum(v) / len(v), 4) for k, v in cat_s.items()},
        per_category_lenient={k: round(sum(v) / len(v), 4) for k, v in cat_l.items()},
        rule_histogram=hist,
        missing_strict=[m.fact for m in matches if not m.strict],
        missing_lenient=[m.fact for m in matches if not m.lenient],
        matches=matches,
    )


# ------------------------------------------------------------- hallucination oracle

# Generic vocabulary that looks like an identifier but is not evidence of a specific
# claim. Without this the candidate extractor is pure noise. Size is reported in the
# paper; every addition is a deliberate, documented decision.
STOPLIST = {
    "api", "apis", "http", "https", "https", "json", "xml", "yaml", "yml", "html", "css",
    "url", "urls", "uri", "rest", "restful", "crud", "sql", "nosql", "orm", "jwt", "auth",
    "oauth", "cors", "csrf", "xss", "ssl", "tls", "tcp", "ip", "dns", "cdn", "cli", "sdk",
    "ide", "ci", "cd", "cicd", "mvc", "dto", "dtos", "acl", "rbac", "uuid", "id", "ids",
    "get", "post", "put", "patch", "delete", "head", "options", "readme", "license",
    "dockerfile", "docker", "kubernetes", "k8s", "node", "nodejs", "npm", "yarn", "pnpm",
    "javascript", "typescript", "js", "ts", "python", "java", "go", "rust", "database",
    "db", "server", "client", "backend", "frontend", "middleware", "controller",
    "controllers", "service", "services", "module", "modules", "repository",
    "repositories", "model", "models", "schema", "schemas", "entity", "entities",
    "config", "configuration", "env", "environment", "test", "tests", "testing", "spec",
    "build", "dist", "src", "lib", "app", "apps", "main", "index", "utils", "util",
    "helpers", "helper", "types", "interfaces", "interface", "class", "classes",
    "function", "functions", "method", "methods", "endpoint", "endpoints", "route",
    "routes", "router", "routers", "request", "response", "error", "errors", "exception",
    "logger", "logging", "user", "users", "admin", "login", "logout", "register",
    "password", "token", "tokens", "session", "sessions", "cache", "queue", "worker",
    "project", "application", "package", "dependency", "dependencies", "library",
    "framework", "structure", "architecture", "documentation", "overview", "summary",
}


_CAND_PATTERNS = [
    (re.compile(r"`([^`\n]{2,60})`"), "backticked"),
    (re.compile(r"(?<![A-Za-z0-9_])(/[A-Za-z0-9_\-{}:./]{2,60})"), "path"),
    (re.compile(r"(?<![A-Za-z0-9_])(@[A-Za-z0-9_\-]+/[A-Za-z0-9_\-.]+)"), "scoped_pkg"),
    (re.compile(r"(?<![A-Za-z0-9_])([A-Za-z0-9_\-]+\.(?:ts|js|tsx|jsx|json|yml|yaml))"), "file"),
    (re.compile(r"(?<![A-Za-z0-9_])((?:[A-Z][a-z0-9]+){2,})(?![A-Za-z0-9_])"), "pascal"),
]


_EXT = re.compile(r"\.(ts|js|tsx|jsx|json|yml|yaml)$", re.IGNORECASE)
# "Node.js", "Nest.js", "Next.js", "Vue.js" -- a capitalised single word plus a JS
# extension. By convention real source files in these repos are lowercase or
# lowerCamelCase ("app.js", "userModel.ts"), so a leading capital marks prose.
_PRODUCT_JS = re.compile(r"^[A-Z][a-z]+\.(js|ts)$")


def _stoplisted(tok: str) -> bool:
    """Stoplist check, extended to reject product names written in `Name.js` style.

    Without this the `file` candidate pattern read "Node.js" as a source filename and
    flagged it as an unsupported identifier. That single gap produced 68 of 89
    hallucination flags (76%) in the first run -- the metric was measuring a stoplist
    omission rather than hallucination.

    We deliberately do NOT stoplist bare framework names ("Vue", "Nest"): a summary
    claiming the wrong framework IS a hallucination worth flagging. Only the
    `Name.js` prose form is excluded.
    """
    t = tok.lower()
    if t in STOPLIST:
        return True
    if _PRODUCT_JS.match(tok):
        return True
    stem = _EXT.sub("", t)
    return stem != t and stem in STOPLIST


def extract_candidates(summary: str) -> list[str]:
    out, seen = [], set()
    for pat, _kind in _CAND_PATTERNS:
        for m in pat.finditer(summary or ""):
            tok = m.group(1).strip().strip("`'\"").rstrip(".,;:)")
            if not tok or len(tok) < 2:
                continue
            if _stoplisted(tok):
                continue
            if tok.lower() not in seen:
                seen.add(tok.lower())
                out.append(tok)
    return out


def known_identifiers(parsed: ParsedRepository) -> set[str]:
    known: set[str] = set()

    def add(x):
        if x:
            known.add(str(x).lower())
            known.add(str(x).lower().lstrip("@"))

    md = parsed.metadata
    add(md.name)
    add(getattr(md, "detected_framework", None))
    add(getattr(md, "detected_language", None))

    for m in parsed.modules:
        add(m.path)
        add(m.path.rsplit("/", 1)[-1])
        add(m.path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        add(m.id)
    for c in parsed.classes:
        add(c.name)
        add(_camel_split(c.name))
    for f in parsed.functions:
        add(getattr(f, "name", None))
    for e in parsed.api_endpoints:
        add(e.path)
        add(e.path.rstrip("/"))
    for d in parsed.database_entities:
        add(d.name)
        add(getattr(d, "source_path", None))
    for d in parsed.dependencies.external:
        add(d.name)
        if d.name.startswith("@") and "/" in d.name:
            scope, sub = d.name[1:].split("/", 1)
            add(scope)
            add(sub)
    for cf in parsed.config_files:
        p = getattr(cf, "path", None)
        add(p)
        if p:
            add(str(p).rsplit("/", 1)[-1])
    return known


def score_hallucination_oracle(
    parsed: ParsedRepository, summary_text: str
) -> OracleHallucination:
    cands = extract_candidates(summary_text or "")
    known = known_identifiers(parsed)

    unsupported = []
    for c in cands:
        cl = c.lower()
        if cl in known or cl.lstrip("@") in known:
            continue
        # a path that is a suffix/prefix of a known route or module path still counts
        if any(cl in k or k in cl for k in known if len(k) > 3):
            continue
        unsupported.append(c)

    total = len(cands)
    return OracleHallucination(
        repo_name=parsed.metadata.name,
        total_candidates=total,
        supported=total - len(unsupported),
        unsupported=len(unsupported),
        unsupported_identifier_rate=round(len(unsupported) / total, 4) if total else 0.0,
        unsupported_samples=unsupported[:10],
    )
