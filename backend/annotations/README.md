# Expected-structure annotations (diagram graph-diff scorer)

These files are the **ground-truth answer key** for `app/evaluation/diagram_score.py`.
The scorer compares the structure the pipeline *extracted* from a repo against the
structure a human says is *actually correct*, and reports precision/recall/F1 over
modules, imports, and endpoints.

One file per evaluation repo, named `<repo_name>.json` (the repo name the parser
derives from the URL). The harness picks them up with `--annotations-dir ./annotations`.

## Status: all 6 files are hand-corrected against real source

Each file was seeded from the pipeline's own extracted structure, then corrected by
reading the actual repository. (Scoring against an *uncorrected* seed would score a
perfect 1.0 by construction — the pipeline agreeing with itself — which is meaningless.
That's why every file here has been reconciled to the source.)

Current diagram-scorer results against these annotations:

| repo | module F1 | import recall | endpoint F1 |
|------|:---------:|:-------------:|:-----------:|
| node-express-sequelize-postgresql | 1.00 | 1.00 | 1.00 |
| node_passport_login | 1.00 | 1.00 | 1.00 |
| node-express-boilerplate | 0.97 | 1.00 | 0.00 |
| nestjs-realworld-example-app | 1.00 | 1.00 | 1.00 |
| nestjs-prisma-starter | 1.00 | 1.00 | 1.00 |
| nestjs-boilerplate | 1.00 | 1.00 | 1.00 |

The single remaining endpoint failure is `hagopj13/node-express-boilerplate`, which
registers routes by iterating an array of `{ path, route }` objects
(`defaultRoutes.forEach(r => router.use(r.path, r.route))`). The mount path is a
*value*, not a literal, so it cannot be recovered without data-flow analysis. Its
routes keep their router-relative paths.

### Why import is reported as recall, not F1

Import **precision is only interpretable when the annotation is exhaustive.** The two
small Express repos are annotated completely, so their import F1 is meaningful (1.00).
The four larger repos list a verified *subset* (4–7 edges out of 63–414), so precision
there measures how few edges were annotated, not parser error — the parser finds every
annotated edge (recall 1.00) plus many more that are genuinely real. Report **recall**
for those repos, or annotate them exhaustively before quoting precision.

## Annotation conventions (so re-annotation stays consistent)

- **`modules`** — application source only. For repos that bury tests/scaffolding among
  source (hagopj13, brocoders), expected modules are the files under `src/`; the
  parser's inclusion of `tests/`, `test/`, and `.install-scripts/` files then shows up
  honestly as false-positive modules.
- **`imports`** — REAL internal edges verified from source (`["from/path", "to/path"]`).
  Annotate **exhaustively** where feasible (both small Express repos are), because
  precision is only interpretable against a complete list. Where exhaustive annotation
  isn't practical (63–414 edges), a verified subset is acceptable but then only
  **recall** may be quoted. An **empty** list would vacuously score 1.0, which is wrong.
- **`endpoints`** — the TRUE in-code route paths. Controller/router prefixes and mount
  paths (`app.use('/v1', ...)`, `@Controller('articles')`) are INCLUDED — the parser is
  meant to resolve these. App-bootstrap global prefixes (`setGlobalPrefix('api')`) and
  URI versioning are EXCLUDED — they're out of parser scope and applied uniformly.
  (If your team prefers to score against full external paths instead, add the global
  prefix/version back to every endpoint — it will lower the NestJS endpoint F1s.)

## Format

```json
{
  "modules": ["src/app.js", "src/routes/users.js"],
  "imports": [["src/app.js", "src/routes/users.js"]],
  "endpoints": ["GET /users", "POST /users"]
}
```

## Running the scorer

```bash
python -m app.evaluation.harness <url> [<url> ...] \
  --judge-model llama3.1:8b \
  --annotations-dir ./annotations \
  --out results.csv --sqlite results.db
```

Repos without a matching `<repo_name>.json` simply leave the diagram columns blank —
no error.
