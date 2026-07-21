"""
Thin Neo4j connection wrapper. Everything downstream (graph builder, context
builder) takes a `neo4j.Driver` rather than constructing its own connection, so
tests can inject a fake/mocked driver instead of needing a running Neo4j instance.
"""

from __future__ import annotations

import os

from neo4j import Driver, GraphDatabase

DEFAULT_URI = "bolt://localhost:7687"


def get_driver() -> Driver:
    uri = os.environ.get("NEO4J_URI", DEFAULT_URI)
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    return GraphDatabase.driver(uri, auth=(user, password))
