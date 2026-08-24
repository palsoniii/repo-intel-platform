"""
Unit tests for the text-overlap metrics module. BERTScore is always exercised via
an injected mock scorer -- these tests never download a model or need network
access, matching the project's offline-by-default testing convention.
"""

import json

from app.evaluation.text_overlap import extract_overview, score_text_overlap
from app.schemas.llm_result import ContextVariant


def test_extract_overview_from_clean_json():
    text = json.dumps({"overview": "A REST API for tutorials.", "tech_stack": []})
    overview, extracted = extract_overview(text)
    assert overview == "A REST API for tutorials."
    assert extracted is True


def test_extract_overview_tolerates_prose_wrapped_json():
    text = 'Here is the summary:\n```json\n{"overview": "An auth starter."}\n```\nHope that helps!'
    overview, extracted = extract_overview(text)
    assert overview == "An auth starter."
    assert extracted is True


def test_extract_overview_falls_back_to_raw_text_when_unparseable():
    text = "This is not JSON at all, just prose about the repo."
    overview, extracted = extract_overview(text)
    assert overview == text
    assert extracted is False


def test_extract_overview_falls_back_when_overview_field_missing():
    text = json.dumps({"tech_stack": ["Express"]})
    overview, extracted = extract_overview(text)
    assert extracted is False
    assert "tech_stack" in overview  # fell back to the raw text


def test_identical_text_scores_near_perfect():
    summary = json.dumps({"overview": "A REST API for managing tutorials with Express and Sequelize."})
    result = score_text_overlap(
        repo_name="sample-repo",
        context_variant=ContextVariant.KNOWLEDGE_GRAPH,
        summary_text=summary,
        reference_overview="A REST API for managing tutorials with Express and Sequelize.",
    )
    assert result.bleu4 > 0.9
    assert result.rouge_l > 0.9
    assert result.meteor > 0.9
    assert result.bertscore_f1 is None  # no bert_scorer injected -> skipped, not crashed


def test_unrelated_text_scores_low():
    summary = json.dumps({"overview": "A GraphQL server for weather forecasts using Apollo and Redis."})
    result = score_text_overlap(
        repo_name="sample-repo",
        context_variant=ContextVariant.RAW,
        summary_text=summary,
        reference_overview="A REST API for managing tutorials with Express and Sequelize.",
    )
    assert result.bleu4 < 0.3
    assert result.rouge_l <= 0.3  # a few stopwords ("A", "for") still overlap


def test_bertscore_uses_injected_scorer_not_the_real_model():
    calls = []

    def fake_scorer(references, hypotheses):
        calls.append((references, hypotheses))
        return [0.87]

    summary = json.dumps({"overview": "Some overview text."})
    result = score_text_overlap(
        repo_name="sample-repo",
        context_variant=ContextVariant.DEPENDENCY_GRAPH,
        summary_text=summary,
        reference_overview="Reference overview text.",
        bert_scorer=fake_scorer,
    )
    assert result.bertscore_f1 == 0.87
    assert calls == [(["Reference overview text."], ["Some overview text."])]


def test_empty_generated_overview_does_not_crash():
    # An empty "overview" field isn't a usable extraction, so this falls back to the
    # raw text (extracted=False) rather than scoring against an empty string -- the
    # important thing is that it produces valid, non-crashing scores either way.
    result = score_text_overlap(
        repo_name="sample-repo",
        context_variant=ContextVariant.RAW,
        summary_text=json.dumps({"overview": ""}),
        reference_overview="A REST API for tutorials.",
    )
    assert result.extracted is False
    assert 0.0 <= result.bleu4 <= 1.0
    assert 0.0 <= result.meteor <= 1.0


def test_truly_empty_text_scores_zero_not_crash():
    result = score_text_overlap(
        repo_name="sample-repo",
        context_variant=ContextVariant.RAW,
        summary_text="   ",
        reference_overview="A REST API for tutorials.",
    )
    assert result.bleu4 == 0.0
    assert result.meteor == 0.0
