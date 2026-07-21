"""
Shared intermediate schema emitted by every framework parser (Express, NestJS).
This is the contract between the Parser layer and everything downstream
(Graph Builder, Context Builder). A new framework parser only needs to populate this
schema correctly -- it never needs to know about Neo4j, LLM prompts, or the dashboard.

Design notes:
- Every entity has a stable `id` (string) so the Graph Builder can wire edges by id
  reference instead of re-resolving names.
- Fields that a given framework can't reliably determine should be left as None / empty
  list rather than guessed -- downstream consumers should treat missing data as
  "unknown", not "absent".
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"
    UNKNOWN = "UNKNOWN"


class DependencyType(str, Enum):
    RUNTIME = "runtime"
    DEV = "dev"
    UNKNOWN = "unknown"


class ConfigFileType(str, Enum):
    ENV = "env"
    BUILD = "build"
    FRAMEWORK_CONFIG = "framework_config"
    OTHER = "other"


class RepoMetadata(BaseModel):
    name: str
    source_url: str
    commit_sha: Optional[str] = None
    detected_language: str
    detected_framework: Optional[str] = None
    framework_version: Optional[str] = None
    files_scanned: int = 0
    files_skipped: list[str] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)
    parsed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModuleNode(BaseModel):
    id: str
    path: str  # relative to repo root
    kind: str = "module"  # "module" | "package"
    imports: list[str] = Field(default_factory=list)  # module ids
    exports: list[str] = Field(default_factory=list)  # symbol ids (class/function ids)


class ClassNode(BaseModel):
    id: str
    name: str
    module_id: str
    interfaces_implemented: list[str] = Field(default_factory=list)  # class/interface ids
    methods: list[str] = Field(default_factory=list)  # function ids
    is_interface: bool = False


class FunctionNode(BaseModel):
    id: str
    name: str
    module_id: str
    class_id: Optional[str] = None  # None if a free function / not a method
    calls: list[str] = Field(default_factory=list)  # function ids this one calls
    is_api_handler: bool = False


class ApiEndpoint(BaseModel):
    id: str
    method: HttpMethod
    path: str
    handler_function_id: Optional[str] = None
    framework_annotation: Optional[str] = None  # e.g. "@GetMapping", "router.get"


class DatabaseEntity(BaseModel):
    id: str
    name: str
    source_path: str  # file the ORM model / entity was defined in
    fields: list[str] = Field(default_factory=list)
    related_function_ids: list[str] = Field(default_factory=list)


class InternalDependencyEdge(BaseModel):
    from_module_id: str
    to_module_id: str


class ExternalDependency(BaseModel):
    name: str
    version: Optional[str] = None
    dep_type: DependencyType = DependencyType.UNKNOWN


class Dependencies(BaseModel):
    internal: list[InternalDependencyEdge] = Field(default_factory=list)
    external: list[ExternalDependency] = Field(default_factory=list)


class ConfigFile(BaseModel):
    path: str
    config_type: ConfigFileType = ConfigFileType.OTHER


class ParsedRepository(BaseModel):
    """
    The single object every BaseParser.parse() implementation must return.
    This is what the Graph Builder consumes to build the Neo4j knowledge graph.
    """

    metadata: RepoMetadata
    modules: list[ModuleNode] = Field(default_factory=list)
    classes: list[ClassNode] = Field(default_factory=list)
    functions: list[FunctionNode] = Field(default_factory=list)
    api_endpoints: list[ApiEndpoint] = Field(default_factory=list)
    database_entities: list[DatabaseEntity] = Field(default_factory=list)
    dependencies: Dependencies = Field(default_factory=Dependencies)
    config_files: list[ConfigFile] = Field(default_factory=list)

    def entity_counts(self) -> dict[str, int]:
        """Quick summary used for logging and for the hallucination-check heuristic
        in the evaluation harness (ground truth counts to compare LLM claims against)."""
        return {
            "modules": len(self.modules),
            "classes": len(self.classes),
            "functions": len(self.functions),
            "api_endpoints": len(self.api_endpoints),
            "database_entities": len(self.database_entities),
        }
