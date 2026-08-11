# Expected-structure annotations (diagram graph-diff scorer)

These files are the **ground-truth answer key** for `app/evaluation/diagram_score.py`.
The scorer compares the structure the pipeline *extracted* from a repo against the
structure a human says is *actually correct*, and reports precision/recall/F1 over
modules, imports, and endpoints.

One file per evaluation repo, named `<repo_name>.json` (the repo name the parser
derives from the URL). The harness picks them up with `--annotations-dir ./annotations`.

## ⚠️ These are AUTO-GENERATED DRAFTS — you must correct them by hand

Each file was seeded with the pipeline's **own** extracted structure. That makes them
a fast starting point, **not** ground truth: if you score against an uncorrected draft
it will score a perfect 1.0 by construction (the pipeline agrees with itself). That
number is meaningless.

To turn a draft into real ground truth, open the repo and edit the JSON so it reflects
what the architecture *truly* is:

- **`modules`** — remove files that aren't real app modules (tests, configs, build
  scripts) if you don't want them counted; add any the parser missed.
- **`imports`** — currently `[]` for every repo, because the parser only resolves
  relative `require()` paths (not ES `import` or path aliases) — a known gap. Fill in
  the real internal import edges as `["from/path.js", "to/path.js"]` pairs by reading
  the source. This is where the parser is weakest, so it's the most valuable column to
  annotate.
- **`endpoints`** — verify each `"METHOD /path"` against the repo's routes; add missed
  ones (e.g. routes behind mounted sub-routers) and remove spurious ones.

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
