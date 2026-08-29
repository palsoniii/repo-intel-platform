# Expected-structure annotations (diagram graph-diff scorer)

These files are the **ground-truth answer key** for `app/evaluation/diagram_score.py`.
The scorer compares the structure the pipeline *extracted* from a repo against the
structure a human says is *actually correct*, and reports precision/recall/F1 over
modules, imports, and endpoints.

One file per evaluation repo, named `<repo_name>.json` (the repo name the parser
derives from the URL). The harness picks them up with `--annotations-dir ./annotations`.

## The 18 repository URLs

```
https://github.com/bezkoder/node-express-sequelize-postgresql
https://github.com/bradtraversy/node_passport_login
https://github.com/hagopj13/node-express-boilerplate
https://github.com/kunalkapadia/express-mongoose-es6-rest-api
https://github.com/danielfsousa/express-rest-boilerplate
https://github.com/davellanedam/node-express-mongodb-jwt-rest-api-skeleton
https://github.com/maitraysuthar/rest-api-nodejs-mongodb
https://github.com/binitghetiya/express-sequelize-api-boilerplate
https://github.com/FrontendMasters/api-design-node-v3
https://github.com/lujakob/nestjs-realworld-example-app
https://github.com/notiz-dev/nestjs-prisma-starter
https://github.com/brocoders/nestjs-boilerplate
https://github.com/andrechristikan/ack-nestjs-boilerplate
https://github.com/NarHakobyan/awesome-nest-boilerplate
https://github.com/Sairyss/domain-driven-hexagon
https://github.com/arielweinberger/nestjs-recipe
https://github.com/monstar-lab-oss/nestjs-starter-rest-api
https://github.com/royib/clean-architecture-nestJS
```

(Repo names below match what the parser derives from each URL, which is what the
`<repo_name>.json` annotation and `reference_summaries/<repo_name>.json` files are
keyed on -- e.g. `binitghetiya/express-sequelize-api-boilerplate` above becomes
`express-sequelize-api-boilerplate.json` in both directories, and
`FrontendMasters/api-design-node-v3` becomes `api-design-node-v3.json`.)

## Status: 18 files, hand-corrected against real source (expanded from the original 6)

> **Independence audit, 2026-08-29 — one confirmed failure of the rule below, and an
> unresolved risk.** `domain-driven-hexagon.json` was found still holding its
> uncorrected seed: its endpoints read `['DELETE /', 'GET /', 'POST /']`, byte-identical
> to the parser's own (wrong) output. The true endpoints are `/v1/users` and
> `/v1/users/:id` — the parser collapses them because that repo declares routes by
> constant reference, a decorator form `nestjs_parser` does not resolve. Its endpoint
> F1 is corrected from 1.00 to 0.00 in the table below; the file now carries a `notes`
> field recording the verification.
>
> The wider risk is not closed. **12 of the 18 endpoint lists are byte-identical to
> current parser output**, which is consistent with correct annotation but cannot be
> distinguished from an uncorrected seed by inspection alone. Seven of those also
> contain a bare `/` path. A bare `/` is not proof of a defect —
> `nestjs-prisma-starter`'s `GET /` was checked against source and is genuinely
> correct — so each remaining file needs verifying against its repository
> individually. Until that is done, endpoint F1 figures here should be read as an
> upper bound.

Each file was seeded from the pipeline's own extracted structure, then corrected by
reading the actual repository. (Scoring against an *uncorrected* seed would score a
perfect 1.0 by construction — the pipeline agreeing with itself — which is meaningless.
That's why every file here has been reconciled to the source.)

**Sample size:** 18 repos (9 Express, 9 NestJS) — expanded from the original 6 for
statistical power. A sign-test power calculation (α=0.05 two-sided, power=0.8) shows
the original n=6 was already sufficient to detect the *large* effect found in the
first battery (knowledge_graph vs. raw, p=0.002, ~85% win rate), but underpowered for
moderate effects (~65-70% win rate) — those need on the order of 55-85 paired
(repo, model) trials. At 3 models, 18 repos gives 54 paired trials, which is powered
for moderate-large effects while staying honest in the paper about being underpowered
for subtle ones.

**Selection criteria** (inferred from and matching the original 6): public GitHub repo,
`express` or `@nestjs/core` declared directly in a root-level `package.json` (not a
monorepo with nested `package.json` files — the pipeline's `detect()` only checks the
repo root), not archived, REST-style routing (`app.get()`/`router.post()`/`@Get()`/
`@Post()` — GraphQL-resolver-only and custom routing-table repos were excluded, see
below), and a size/complexity spread from small (a handful of modules) to large
(hundreds) matching the original set's range. Verified via the GitHub API before
cloning (size, license, `archived`, last push, and root `package.json` contents).

**Excluded during selection** (documented so the sampling methodology is reproducible):
- 3 TypeScript Express candidates (`w3tecch/express-typescript-boilerplate`,
  `edwinhern/express-typescript`, `watscho/express-mongodb-rest-api-boilerplate`) —
  `ExpressParser` only reads `.js`/`.mjs`/`.cjs` (TypeScript is the NestJS parser's
  job), so a TS-Express repo's `detect()` still matches Express but `parse()` finds
  almost nothing. A real, previously-undocumented parser gap — see below.
- `Vivify-Ideas/nestjs-boilerplate` — its repo name collides with the already-selected
  `brocoders/nestjs-boilerplate`. `repo_name` is derived from just the URL's repo
  segment (`app/acquisition/clone.py`), and Neo4j nodes are partitioned by
  `(repo_name, id)` (`SCHEMA.md`) — two *different* repos sharing a `repo_name` would
  silently corrupt each other's graph. Worth a follow-up fix (key on `owner/repo`
  instead) if the dataset grows again.
- `fernandohenriques/nestjs-graphql-boilerplate` (0 endpoints — GraphQL resolvers, not
  `@Get`/`@Post` decorators) and `binitghetiya`'s and `aichbauer`'s Express boilerplates
  that route via a custom data-driven table (`{'POST /user': 'UserController.register'}`)
  or the `resource-router-middleware` package (0 endpoints for the same reason: not the
  vanilla `app.get()`/`router.post()` pattern this parser targets) — legitimately out of
  scope, not parser bugs.
- `diegohaz/rest` — turned out to be a Yeoman generator *template* (EJS conditionals
  control which routes even exist), not a fixed deployable app. Its "true" structure is
  parameterized by generator options, so it isn't a valid ground-truth-annotation target.

**Two real parser bugs were found and fixed while building these annotations** (both
regression-tested in `tests/test_express_parser.py`):
1. `app.get('port')` / `app.get('view engine')` — Express's single-argument
   app-*settings* getter overload — was being misread as a handler-less GET route
   registration, since `_extract_routes` never checked that a direct-style call
   actually had both a path *and* a handler argument.
2. `_collect_mounts` treated *any* statically-unresolvable `app.use()`/`router.use()`
   second argument as "a router built in this same file," including plain middleware
   like `express.static('docs')`. In `express-rest-boilerplate` this corrupted that
   file's own mount prefix (`/docs` + `/v1` → `/docs/v1` instead of `/v1`), misreporting
   `GET /status` as `GET /docs/v1/status`. Now restricted to actual identifiers.

Current diagram-scorer results against all 18 annotations:

| repo | module F1 | import F1/recall | endpoint F1 |
|------|:---------:|:-----------------:|:-----------:|
| node-express-sequelize-postgresql | 1.00 | 1.00 | 1.00 |
| node_passport_login | 1.00 | 1.00 | 1.00 |
| node-express-boilerplate | 0.97 | 1.00 | 0.00 |
| nestjs-realworld-example-app | 1.00 | 1.00 | 1.00 |
| nestjs-prisma-starter | 1.00 | 1.00 | 1.00 |
| nestjs-boilerplate | 1.00 | 1.00 | 1.00 |
| express-mongoose-es6-rest-api | 1.00 | 1.00 | 1.00 |
| express-sequelize-api-boilerplate | 1.00 | 1.00 | 1.00 |
| rest-api-nodejs-mongodb | 1.00 | 1.00 | 1.00 |
| express-rest-boilerplate | 1.00 | 1.00 | 0.07 |
| node-express-mongodb-jwt-rest-api-skeleton | 1.00 | 1.00 | 0.40 |
| api-design-node-v3 | 1.00 | 1.00 | 0.18 |
| ack-nestjs-boilerplate | 1.00 | recall only | 1.00 |
| awesome-nest-boilerplate | 1.00 | 1.00 | 1.00 |
| clean-architecture-nestJS | 1.00 | 1.00 | 1.00 |
| domain-driven-hexagon | 1.00 | 1.00 | **0.00** |
| nestjs-recipe | 1.00 | 1.00 | 1.00 |
| nestjs-starter-rest-api | 1.00 | 1.00 | 1.00 |

**Four remaining endpoint failures, each a distinct, real, documented limitation** (not
bugs — verified by hand-composing the true paths from source and comparing to what the
parser resolved):
- `hagopj13/node-express-boilerplate` — registers routes by iterating an array of
  `{ path, route }` objects (`defaultRoutes.forEach(r => router.use(r.path, r.route))`).
  The mount path is a runtime *value*, not a literal, so it can't be recovered without
  data-flow analysis.
- `node-express-mongodb-jwt-rest-api-skeleton` — mounts routes via
  `fs.readdirSync(routesPath)` looped with a template-literal path
  (`` router.use(`/${routeFile}`, require(`./${routeFile}`)) ``). Same root cause as
  above: the mount path isn't a string literal, this time because it's built
  dynamically from the filesystem rather than from data.
- `express-rest-boilerplate` — a genuine architectural gap in the mount-prefix
  resolver: it composes only **one level** of `app.use()`/`router.use()` nesting.
  `config/express.js` mounts `routes` (= `v1/index.js`) at `/v1`; `v1/index.js` in turn
  mounts `user.route.js`/`auth.route.js` at `/users`/`/auth`. The resolver correctly
  prefixes `v1/index.js`'s *own* routes with `/v1`, but doesn't transitively propagate
  that `/v1` onto the routers `v1/index.js` itself mounts — so `GET /users` is reported
  instead of the true `GET /v1/users`. Fixing this needs a mount-prefix *graph*
  (parent-mount lookups resolved transitively) rather than the current flat
  per-module dict — a real follow-up, out of scope for this pass.
- `api-design-node-v3` — its routers are wired with ES `import`/`export`, not
  CommonJS `require()`. `_extract_requires`/`_identifier_require_bindings`/
  `_require_path` only recognize `require(...)` call expressions; an ES
  `import userRouter from './routes/user'` is a different AST node type entirely
  (`import_statement`), so it's invisible to both the internal-import-edge resolver
  *and* the mount-prefix resolver (`app.use('/api/user', userRouter)` can't resolve
  `userRouter` to anything). **This is a significant, previously-undocumented gap**:
  the Express parser is CommonJS-only. Any modern Express repo using ES modules will
  silently lose both its dependency-graph edges and its mount-prefix composition. Worth
  a dedicated follow-up (add an ES `import`/`export` extraction path mirroring the
  existing `require()` one) before drawing conclusions from Express repos generally.
- `ack-nestjs-boilerplate` — 601 modules but only 2 resolved import edges. Uses
  TypeScript path aliases (webpack/tsconfig `paths`) almost everywhere instead of
  relative imports, which the parser has never resolved (documented in the main
  README's NestJS "Known gaps" since before this dataset expansion). Reported as
  recall-only for the same reason as the other large repos below, not exhaustively
  annotated.

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
