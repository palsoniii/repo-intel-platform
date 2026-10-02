"""
Small, dependency-free scanning helpers for JavaScript/TypeScript source text.

The product layer needs a handful of shallow facts the parsers don't emit (ORM model
fields, constructor injection, where a route is declared). Each is one bracket-matched
region away from a regex, so this module provides exactly that: bracket matching that
skips strings, template literals and comments, and splitting an object literal into
its top-level keys. It is not a parser and doesn't try to be one.
"""

from __future__ import annotations

import re

_PAIRS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = {v: k for k, v in _PAIRS.items()}


def _skip_string(text: str, i: int) -> int:
    """i points at a quote; returns the index just past the closing quote."""
    quote = text[i]
    i += 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        if quote == "`" and c == "$" and i + 1 < n and text[i + 1] == "{":
            end = match_bracket(text, i + 1)
            i = (end + 1) if end is not None else n
            continue
        i += 1
    return n


def _skip_comment(text: str, i: int) -> int | None:
    """If a comment starts at i, returns the index just past it; otherwise None."""
    if text.startswith("//", i):
        end = text.find("\n", i)
        return len(text) if end == -1 else end + 1
    if text.startswith("/*", i):
        end = text.find("*/", i + 2)
        return len(text) if end == -1 else end + 2
    return None


def match_bracket(text: str, open_idx: int) -> int | None:
    """Index of the bracket closing the one at open_idx, or None if unbalanced."""
    if open_idx >= len(text) or text[open_idx] not in _PAIRS:
        return None
    stack = [text[open_idx]]
    i = open_idx + 1
    n = len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            i = _skip_string(text, i)
            continue
        if c == "/":
            skipped = _skip_comment(text, i)
            if skipped is not None:
                i = skipped
                continue
        if c in _PAIRS:
            stack.append(c)
        elif c in _CLOSERS:
            if not stack or stack[-1] != _CLOSERS[c]:
                return None
            stack.pop()
            if not stack:
                return i
        i += 1
    return None


_KEY_RE = re.compile(r"""\s*(?:(['"])(?P<q>[^'"]+)\1|(?P<id>[A-Za-z_$][\w$]*))\s*:""")


def top_level_entries(obj_text: str) -> list[tuple[str, str]]:
    """Splits the inside of an object literal (without its outer braces) into
    (key, value_text) pairs at depth 0. Spreads, methods and computed keys are
    skipped rather than guessed at."""
    entries: list[tuple[str, str]] = []
    for chunk in _split_top_level(obj_text, ","):
        m = _KEY_RE.match(chunk)
        if not m:
            continue
        key = m.group("q") or m.group("id")
        entries.append((key, chunk[m.end():].strip()))
    return entries


def _split_top_level(text: str, sep: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            i = _skip_string(text, i)
            continue
        if c == "/":
            skipped = _skip_comment(text, i)
            if skipped is not None:
                i = skipped
                continue
        if c in _PAIRS:
            depth += 1
        elif c in _CLOSERS:
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return [p for p in (s.strip() for s in parts) if p]


def strip_comments(text: str) -> str:
    """Replaces comments with spaces of equal length, so offsets (and therefore line
    numbers) computed on the result still point at the right place in the original."""
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            i = _skip_string(text, i)
            continue
        if c == "/":
            skipped = _skip_comment(text, i)
            if skipped is not None:
                for j in range(i, skipped):
                    if out[j] != "\n":
                        out[j] = " "
                i = skipped
                continue
        i += 1
    return "".join(out)


def line_of(text: str, offset: int) -> int:
    """1-indexed line number of a character offset."""
    return text.count("\n", 0, offset) + 1
