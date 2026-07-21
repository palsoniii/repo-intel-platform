"""
Framework detection: cheap, file-signature-based checks (no parsing) to figure out
what kind of repo we're looking at before dispatching to a parser plugin.
"""

from __future__ import annotations

import json
from pathlib import Path


def detect_language_and_framework(repo_path: Path) -> tuple[str, str | None]:
    """Returns (detected_language, detected_framework_or_None).
    Framework detection here is a fast pre-check; the actual parser's own
    detect() method (BaseParser.detect) does the authoritative check."""

    pkg_json = repo_path / "package.json"
    pom_xml = repo_path / "pom.xml"
    build_gradle = repo_path / "build.gradle"

    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text())
        except (json.JSONDecodeError, OSError):
            return "javascript", None

        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        has_ts = (repo_path / "tsconfig.json").exists()
        language = "typescript" if has_ts else "javascript"

        if "@nestjs/core" in deps:
            return language, "nestjs"
        if "express" in deps:
            return language, "express"
        return language, None

    if pom_xml.exists() or build_gradle.exists():
        # authoritative spring-boot-starter check happens in the Spring parser's
        # own detect() -- this is just a fast language-level signal
        return "java", "spring_boot" if _looks_like_spring(pom_xml, build_gradle) else None

    return "unknown", None


def _looks_like_spring(pom_xml: Path, build_gradle: Path) -> bool:
    for f in (pom_xml, build_gradle):
        if f.exists() and "spring-boot" in f.read_text(errors="ignore"):
            return True
    return False
