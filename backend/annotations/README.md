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

| repo | module F1 | import F1 | endpoint F1 | overall |
|------|:---------:|:---------:|:-----------:|:-------:|
| node-express-sequelize-postgresql | 1.00 | 0.00 | 0.13 | 0.38 |
| node_passport_login | 1.00 | 0.00 | 0.29 | 0.43 |
| node-express-boilerplate | 0.86 | 0.00 | 0.00 | 0.29 |
| nestjs-realworld-example-app | 1.00 | 0.00 | 1.00 | 0.67 |
| nestjs-prisma-starter | 1.00 | 0.00 | 1.00 | 0.67 |
| nestjs-boilerplate | 0.94 | 0.00 | 0.05 | 0.33 |

What the numbers say: the parser discovers modules well (module F1 near 1.0; the two
dips are the Express parser counting test files and the boilerplate's scaffolding as
modules), extracts NestJS string-literal decorator routes perfectly (endpoint F1 1.0),
but recovers **no** internal imports on any repo, misses Express router-mount prefixes,
and misses NestJS object-form `@Controller({ path })` prefixes.

## Annotation conventions (so re-annotation stays consistent)

- **`modules`** — application source only. For repos that bury tests/scaffolding among
  source (hagopj13, brocoders), expected modules are the files under `src/`; the
  parser's inclusion of `tests/`, `test/`, and `.install-scripts/` files then shows up
  honestly as false-positive modules.
- **`imports`** — a *representative* set of REAL internal edges, verified from source
  (`["from/path", "to/path"]`). The parser recovers 0 internal imports on every repo
  (it only resolves relative `require()`, not ES `import`/path aliases — a known gap),
  so import F1 is 0.0 regardless of how many are listed. A representative set is enough
  to score that honestly; an **empty** list would vacuously score 1.0, which is wrong.
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
