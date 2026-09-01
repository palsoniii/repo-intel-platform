# Evaluation battery results (Week 4 / Phase 7)

First complete run of the representation ablation across the 6-repo candidate
evaluation set. **These are candidate-set results — the team has not yet ratified the
6 fixed repos or the 2 held-back repos, so treat this as the first full battery, not
the final reported study.**

> ## ⚠️ SUPERSEDED — THIS FILE IS A HISTORICAL RECORD, NOT CURRENT RESULTS
>
> These 54 rows are the **6-repo pilot**, run before the parser fixes. Everything below
> is retained for provenance only. **Do not quote any figure from this file.**
>
> The re-run it called for has since happened three times, on **18 repositories**:
>
> | Battery | Writers | Judge | Rows |
> |---|---|---|---|
> | `battery.db` | qwen2.5-coder:7b, codellama:7b-instruct | gemma2:9b | 108 / 108 |
> | `battery_v2.db` | qwen2.5-coder:7b, codellama:7b-instruct, gemma2:9b | mistral:7b-instruct | 162 / 157 |
> | `battery_v3_granite_gemma2judge.db` | granite-code:8b-instruct | gemma2:9b | 54 / 53 |
>
> **Current results live in `../../docs/REPORT.md`** (§5.5 onward), with per-battery
> summaries in `BATTERY_V2_RESULTS.txt`, `GRANITE_ARM_RESULTS.txt`, `ORACLE_STATS.txt`
> and `T7_META_EVALUATION.txt`.
>
> Three specific claims below are now known false:
> - **The headline "knowledge_graph > raw, p = 0.002" does not replicate.** Later runs
>   report a faithfulness null; the coverage effect survives only under the
>   deterministic oracle, and the paper's headline is now the judge-disagreement
>   finding (`REPORT.md` §5.6).
> - **"Raw is capped at 8000 chars"** — `DEFAULT_MAX_RAW_CHARS` is **24,000**. The
>   efficiency arithmetic in this file is against a value 3x off.
> - **"Import F1 0.00 on every repo / recovers no internal imports"** — the
>   path-normalisation fix landed; the parse now yields 3,861 import edges across 18
>   repos.

## Setup

- **Generators (3):** `qwen2.5-coder:7b`, `llama3.1:8b`, `mistral:7b`
- **Judge:** `gemma2:9b` — a **4th, independent** model, not one of the generators, so
  no arm is self-judged and the judge is constant across all arms.
- **Repos (6):** bezkoder/node-express-sequelize-postgresql,
  bradtraversy/node_passport_login, hagopj13/node-express-boilerplate,
  lujakob/nestjs-realworld-example-app, notiz-dev/nestjs-prisma-starter,
  brocoders/nestjs-boilerplate
- **Design:** 3 models x 3 representations x 6 repos = **54 rows, 0 failures.**
- Run one generator at a time (never 3 models resident at once) on a 16GB laptop.
  Latency figures are therefore *not* from a designated evaluation machine and should
  be re-measured there before being reported as headline numbers.

Raw data: `clean_qwen.csv`, `clean_llama.csv`, `clean_mistral.csv`, and `study_clean.db`
(all three arms accumulated).

## Headline result: knowledge_graph produces more faithful summaries than raw code

Because between-repo variance is large, the meaningful test is **paired** — each
(repo, model) pair sees all three representations. Sign test over those pairs,
excluding 2 rows where the judge's output failed to parse:

| comparison | better | worse | tied | mean diff | p |
|---|:---:|:---:|:---:|:---:|:---:|
| **knowledge_graph vs raw** | **15** | 2 | 0 | **-0.206** | **0.002** |
| knowledge_graph vs dependency_graph | 10 | 5 | 2 | -0.096 | 0.302 |
| dependency_graph vs raw | 10 | 6 | 0 | -0.071 | 0.454 |

**knowledge_graph beats raw in 15 of 17 pairs (p = 0.002)** — consistent across models
and repos. The other two comparisons are **not** significant: `dependency_graph` is not
demonstrably better than raw, and knowledge_graph's edge over dependency_graph only
trends. So the defensible claim is specifically *full knowledge graph > raw code*, not
a general "more structure is monotonically better."

## Mean hallucination score by model x representation (lower = better)

Excludes the 2 unjudged rows; n = 6 per cell unless noted.

| model | raw | dependency_graph | knowledge_graph |
|---|:---:|:---:|:---:|
| qwen2.5-coder:7b | 0.370 | 0.404 | **0.261** |
| llama3.1:8b | 0.463 | 0.269 | **0.045** |
| mistral:7b | **0.334** (n=5) | 0.354 (n=5) | 0.390 |
| **pooled** | 0.392 | 0.341 | **0.232** |

**Mistral dissents:** it is the one generator that scores best on raw and worst on
knowledge_graph. The pooled effect is driven by Qwen and (especially) Llama. Worth
reporting honestly rather than averaging away — a per-model breakdown belongs in the
paper, not just the pooled mean.

## Efficiency

Pooled across models (n=18 per representation):

| | raw | dependency_graph | knowledge_graph |
|---|:---:|:---:|:---:|
| avg input tokens | 2210 | 1094 | 1172 |
| avg latency | 46.8s | 40.6s | 40.1s |

Structured representations use roughly **half the input tokens** and run modestly
faster. Note this partly reflects a design choice: raw context is capped at
`DEFAULT_MAX_RAW_CHARS` (8000 chars), so raw's token count is pinned near that ceiling
while the graph contexts scale with repo size. On the largest repo
(`nestjs-boilerplate`) the structured contexts are *bigger and slower* than capped raw
(~3300 tokens vs ~2100). An earlier one-repo pilot suggested "raw is ~4x slower"; that
does **not** hold across the 6-repo set.

## Threats to validity / caveats

1. **Judge choice changes conclusions.** A pilot using `llama3.1:8b` as judge ranked
   `dependency_graph` best (0.061); with the independent `gemma2:9b` judge the same
   Qwen generations rank it *worst* (0.404). The metric is not stable across judges —
   this is why the independent judge was adopted, and it is itself a finding.
2. **Self-judging masked the effect.** Llama judging its own output showed no clear
   structure benefit (raw 0.732 / dep 0.743 / kg 0.515); cross-judged by gemma2 the
   same generations show a clean gradient (0.463 / 0.269 / 0.045).
3. **The judge over-flags.** In a smoke test, gemma2 scored a *faithful* summary 0.286,
   flagging claims the parser data actually supports. Absolute scores therefore carry a
   positive bias and should not be read as "N% of claims were fabricated"; only
   relative comparisons between representations are meaningful.
4. **2 of 54 rows were unjudged** (judge output failed to parse; both mistral). The
   harness records those as score 0.0 with `hallucination_judged=False`, which biases
   means downward if not filtered — all figures above exclude them. Filtering on that
   flag matters.
5. **n=6 repos**, high variance (per-cell sd up to 0.48). Only the paired knowledge_graph
   vs raw comparison survives significance testing.
6. **Latency measured on a 16GB dev laptop**, not the designated evaluation machine,
   with thermal throttling likely during long runs.

## Diagram graph-diff scores (per repo, model-independent)

From the hand-corrected annotations in `../annotations/`:

| repo | module F1 | import F1 | endpoint F1 | overall |
|---|:---:|:---:|:---:|:---:|
| node-express-sequelize-postgresql | 1.00 | 0.00 | 0.13 | 0.38 |
| node_passport_login | 1.00 | 0.00 | 0.29 | 0.43 |
| node-express-boilerplate | 0.86 | 0.00 | 0.00 | 0.29 |
| nestjs-realworld-example-app | 1.00 | 0.00 | 1.00 | 0.67 |
| nestjs-prisma-starter | 1.00 | 0.00 | 1.00 | 0.67 |
| nestjs-boilerplate | 0.94 | 0.00 | 0.05 | 0.33 |

Parser recovers modules well and NestJS string-literal decorator routes perfectly, but
recovers **no** internal imports on any repo, and misses Express router-mount prefixes
and NestJS object-form `@Controller({ path })` prefixes. See `../annotations/README.md`.

## Reproducing

```bash
python -m app.evaluation.harness \
  <the 6 repo URLs> \
  --models qwen2.5-coder:7b \
  --judge-model gemma2:9b \
  --annotations-dir ./annotations \
  --out clean_qwen.csv --sqlite study_clean.db
```

Repeat with `--models llama3.1:8b` and `--models mistral:7b`, appending to the same
`--sqlite`. Running one generator at a time keeps only 2 models resident, which matters
on a 16GB machine.
