# Reference summaries (text-overlap metrics ground truth)

These are the **reference/gold summaries** that `app/evaluation/text_overlap.py`
(BLEU-4, ROUGE-L, METEOR, BERTScore) scores generated summaries against. One file
per evaluation repo, `<repo_name>.json`, matching the exact shape
`providers/prompts.py`'s `SUMMARY_PROMPT_TEMPLATE` asks the model to produce:
`{overview, tech_stack, services, dependencies}`.

## Status: LLM-drafted, needs your review before being locked in as ground truth

**`overview`, `tech_stack`, and `services` were drafted by Claude**, reading each
repo's actual README and the parser's real extracted facts (framework, language,
endpoints) -- not fabricated. This mirrors arXiv:2501.07857's own methodology (the
closest matching paper in the lit review): they used GPT-4 to draft ground-truth
summaries, then had subject-matter experts validate them, explicitly *because*
hand-writing reference summaries for every repo from scratch doesn't scale. The same
disclosure applies here and belongs in the paper's methodology section: reference
summaries are LLM-drafted and human-reviewed, not independently human-authored.

**`dependencies` was NOT drafted** -- it's pulled directly from each repo's parsed
`ParsedRepository.dependencies.external`, i.e. deterministic static analysis, not
judgment. There's no ambiguity in "what packages does this package.json declare,"
so there's nothing for an LLM (or a human) to get wrong there.

**Before running the battery for the paper, read through these 18 files and correct
anything that misrepresents a repo** -- particularly `overview` (2-4 sentences) and
`services`, since those required the most judgment calls about what a repo is *for*,
not just what's in it.

## Why text-overlap metrics need these at all

BLEU/ROUGE/METEOR/BERTScore are reference-based: they need something to compare
the generated `overview` text against. Comparing against `dependencies` or
`tech_stack` (unordered fact lists) would be redundant with what
`coverage.py`/`hallucination.py` already measure far better (fact-grounded judge
scoring, not n-gram overlap) -- so `text_overlap.py` scores specifically against the
`overview` field, where prose fluency/content-overlap is the thing actually being
measured.

## Format

```json
{
  "overview": "2-4 sentence plain-English description of what the repo does.",
  "tech_stack": ["Language", "Framework", "NotableLibrary"],
  "services": ["Brief description of the main entry point(s)"],
  "dependencies": ["exact external dependency names from package.json"]
}
```
