"""
Unit tests for the failure taxonomy: categorization of missing facts (precise,
prefix-matched) and unsupported claims (heuristic), plus aggregation.
"""

from app.evaluation.failure_analysis import (
    FailureTag,
    aggregate_by_group,
    aggregate_failure_frequencies,
    analyze_failures,
    categorize_missing_fact,
    categorize_unsupported_claim,
)


def test_categorize_missing_fact_matches_known_prefixes():
    assert categorize_missing_fact("Endpoint: GET /users") == FailureTag.MISSED_ENDPOINT
    assert categorize_missing_fact("Dependency: express") == FailureTag.MISSED_DEPENDENCY
    assert categorize_missing_fact("Framework: express") == FailureTag.MISSED_FRAMEWORK_OR_LANGUAGE
    assert categorize_missing_fact("Language: javascript") == FailureTag.MISSED_FRAMEWORK_OR_LANGUAGE
    assert categorize_missing_fact("Class/Service: UserController") == FailureTag.MISSED_CLASS_OR_SERVICE
    assert categorize_missing_fact("Database entity: User") == FailureTag.MISSED_DATABASE_ENTITY


def test_categorize_missing_fact_returns_none_for_unknown_prefix():
    assert categorize_missing_fact("Something unexpected") is None


def test_categorize_unsupported_claim_detects_endpoint_pattern():
    assert categorize_unsupported_claim("Defines a GET /api/orders endpoint") == FailureTag.FABRICATED_ENDPOINT
    assert categorize_unsupported_claim("Has a POST/users route") == FailureTag.FABRICATED_ENDPOINT


def test_categorize_unsupported_claim_falls_back_to_technology():
    assert categorize_unsupported_claim("Uses MongoDB for storage") == FailureTag.FABRICATED_TECHNOLOGY
    assert categorize_unsupported_claim("Built with GraphQL and Redis") == FailureTag.FABRICATED_TECHNOLOGY


def test_analyze_failures_tags_malformed_output_when_unjudged():
    analysis = analyze_failures(
        repo_name="r", model="m", context_variant="raw",
        unsupported_claims=[], missing_facts=[], generated_overview="A specific Express API.",
        known_terms=["Express"], hallucination_judged=False, coverage_judged=True,
    )
    assert FailureTag.MALFORMED_OUTPUT in analysis.tags


def test_analyze_failures_combines_all_signal_sources():
    analysis = analyze_failures(
        repo_name="r", model="m", context_variant="knowledge_graph",
        unsupported_claims=["Uses MongoDB", "Defines GET /weird"],
        missing_facts=["Endpoint: GET /users", "Dependency: sequelize"],
        generated_overview="A REST API built with Express and Sequelize for creating, listing, and managing tutorials.",
        known_terms=["Express", "Sequelize"],
        hallucination_judged=True, coverage_judged=True,
    )
    assert FailureTag.FABRICATED_TECHNOLOGY in analysis.tags
    assert FailureTag.FABRICATED_ENDPOINT in analysis.tags
    assert FailureTag.MISSED_ENDPOINT in analysis.tags
    assert FailureTag.MISSED_DEPENDENCY in analysis.tags
    assert FailureTag.OVER_GENERIC not in analysis.tags  # names Express/Sequelize specifically
    assert FailureTag.MALFORMED_OUTPUT not in analysis.tags


def test_analyze_failures_flags_short_overview_as_over_generic():
    analysis = analyze_failures(
        repo_name="r", model="m", context_variant="raw",
        unsupported_claims=[], missing_facts=[], generated_overview="A web app.",
        known_terms=["Express"], hallucination_judged=True, coverage_judged=True,
    )
    assert FailureTag.OVER_GENERIC in analysis.tags


def test_analyze_failures_flags_long_overview_missing_known_terms_as_over_generic():
    generic = "This project provides a set of endpoints that allow clients to interact with data over HTTP using standard methods."
    analysis = analyze_failures(
        repo_name="r", model="m", context_variant="raw",
        unsupported_claims=[], missing_facts=[], generated_overview=generic,
        known_terms=["Express", "Sequelize"], hallucination_judged=True, coverage_judged=True,
    )
    assert FailureTag.OVER_GENERIC in analysis.tags


def test_aggregate_failure_frequencies_counts_across_analyses():
    analyses = [
        analyze_failures("r1", "m", "raw", ["Uses MongoDB"], [], "Express API for tutorials with real detail here.", ["Express"], True, True),
        analyze_failures("r2", "m", "raw", ["Uses Redis"], [], "Express API for tutorials with real detail here.", ["Express"], True, True),
    ]
    freq = aggregate_failure_frequencies(analyses)
    assert freq[FailureTag.FABRICATED_TECHNOLOGY.value] == 2


def test_aggregate_by_group_splits_by_grouping_key():
    analyses = [
        analyze_failures("r1", "m", "raw", ["Uses MongoDB"], [], "Express API for tutorials with real detail here.", ["Express"], True, True),
        analyze_failures("r1", "m", "knowledge_graph", [], [], "Express API for tutorials with real detail here.", ["Express"], True, True),
    ]
    by_variant = aggregate_by_group(analyses, lambda a: a.context_variant)
    assert by_variant["raw"][FailureTag.FABRICATED_TECHNOLOGY.value] == 1
    assert FailureTag.FABRICATED_TECHNOLOGY.value not in by_variant.get("knowledge_graph", {})
