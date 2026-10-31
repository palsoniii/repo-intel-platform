# Why the project is built the way it is

Every significant decision in the project, why it was made, and what it cost. Three
parts: the research, the product built on it, and the deployment. For figures, the
sources of truth are `docs/paper.tex` (research) and the code (product).

---

## Part A: The research

### A1. The question

**Decision:** test whether giving a model a structured representation of a repository
(a dependency graph, or a full knowledge graph) instead of raw source produces a more
complete and more faithful summary, and at what token cost.

**Why:** a model handed raw source has to do two jobs at once: static analysis (what
calls what, which routes exist) and writing. The analysis half is where it invents
frameworks, endpoints and dependencies. A parser does that half deterministically, so
the question is whether handing the model the parser's output fixes the inventions.

### A2. Scope: Express.js and NestJS only

**Why:** the two most common Node.js backend styles, and deliberately different ones:
Express wires routes by function calls (`router.get(...)`), NestJS by decorators
(`@Controller`, `@Get`). Covering both shows the approach isn't tied to one style.
Two frameworks were what could be parsed properly in the time available; Spring Boot
was in the original proposal and cut.

**Cost:** results are about Node.js backends only. The parser layer is pluggable, so
this is a scope limit, not a design limit.

### A3. Scope: Neo4j only, not NetworkX

**Why:** a knowledge graph of code is naturally a graph database: typed nodes (modules,
classes, endpoints) and typed edges (imports, defines, handles). Neo4j stores it
persistently, lets several repositories share one instance, and can be queried with
Cypher and inspected visually in Neo4j Browser. Supporting two graph backends would
have doubled the graph code for no research benefit.

### A4. Scope: free local models only, no paid APIs

**Why:** reproducibility (anyone can rerun the study; a hosted model can change or
disappear), zero cost, and code never leaving the machine. The study compares
representations, not models, so it didn't need the strongest model available.

**Cost:** smaller models with smaller context windows (8,192 tokens), and slow
generation, which is why the final battery ran on a GPU cluster.

### A5. Three representations, not five

**Decision:** raw source, dependency graph, full knowledge graph, all rendered from the
same clone and the same parse.

**Why:** these three form a clean ladder: no structure, some structure (imports only),
full structure (imports plus classes, functions, endpoints, dependencies, configs).
Rendering all three from one parse means representation is the only thing that
changes between arms. A larger original design was cut to keep the study finishable
and the statistics manageable (each extra arm adds comparisons to correct for).

### A6. tree-sitter for parsing

**Why:** fast, error-tolerant (parses files with syntax errors instead of failing),
handles JavaScript and TypeScript with the same API, and gives a real syntax tree, so
routes and decorators are found structurally rather than by fragile regular
expressions.

### A7. One parser output contract (`ParsedRepository`)

**Why:** every parser emits the same structure and everything downstream (graph
builder, context renderers, diagrams, evaluation) reads only that. A new framework
needs only a new parser. NestJS is checked before Express because NestJS projects
usually list `express` too, which would otherwise be misdetected.

### A8. Raw source capped to fit, structured arms not capped

**Why:** raw source for most repositories is far bigger than the window, so it's cut to
the model's window minus the prompt and room for the answer; otherwise the model would
silently drop the start of the prompt, where the instructions are. The structured
renderings were compact enough to fit uncapped (largest 7,877 tokens).

**Cost:** an asymmetry between arms, disclosed in the paper.

### A9. Generator models

**Decision (final battery):** codellama:13b-instruct, qwen2.5-coder:14b,
qwen2.5-coder:32b, all 4-bit quantized.

**Why:** two separate checks in one roster. codellama:13b vs qwen 14b compares two
organizations (Meta vs Alibaba) at matched size; qwen 14b vs qwen 32b changes only size
within one family. If the representation effect survives both an organization change
and a size change, it isn't a quirk of one model. All three are code-specialized and
instruction-tuned. An earlier 7B roster was superseded because it didn't separate these
factors and ran on the uncorrected parser.

### A10. Deterministic decoding

**Decision:** temperature 0, fixed seed (42), an 8,192-token context set explicitly.

**Why:** without these, each model ran at its own default temperature with no seed, so
results weren't repeatable and cross-model comparisons carried extra hidden variance.
The window is set explicitly because Ollama otherwise defaults to 2-4K tokens and
silently truncates.

### A11. Two metrics, always reported together

**Decision:** hallucination (share of the summary's checkable claims not supported by
the parser's facts) and coverage (share of the parser's facts the summary mentions).

**Why:** each can be gamed alone. A summary that says almost nothing scores perfectly on
hallucination and terribly on coverage; one that lists everything scores well on
coverage but risks inventing things. Precision-like and recall-like together are what
"quality" means here.

### A12. An independent judge, never a generator

**Decision:** gemma2:9b judges every summary; it is never one of the models being
compared. The code refuses to run a scored comparison if the judge is a generator.

**Why:** in pilot work, the same summaries changed ranking under a different judge, and
a model judging its own summaries reversed the ranking of representations. A fixed,
independent judge removes that bias.

### A13. Human validation of the judge, and a deterministic oracle

**Decision:** a human scored 552 judge decisions by hand; coverage is also scored by a
deterministic matcher (`app/evaluation/oracle.py`) with no model involved.

**Why:** an LLM judge is a measuring instrument, and nobody had checked it. The check
was decisive: the human was 96% accurate, the judge 83%, agreement only κ = 0.26, and a
simple string matcher agreed with the human better than the judge did. So the paper
claims the *direction* of the result, not the absolute scores, and recommends
deterministic grading wherever ground truth is a list of literal strings. That finding
became one of the paper's main contributions.

### A14. Dataset: 18 repositories, 9 Express and 9 NestJS

**Why:** enough for paired statistics while still hand-annotatable. Selection rules were
explicit and reproducible: public, not archived, the framework declared in a root
`package.json`, REST-style routing, a range of sizes. Excluded repositories were
recorded with reasons (GraphQL-only, custom routing languages, TypeScript Express that
the Express parser doesn't read, a generator template).

**Held-back repositories:** two repositories were to be kept untouched until the end to
show the system generalizes rather than being tuned to the dataset. Repositories used
during development are disqualified from that role.

### A15. Statistics: paired Wilcoxon, Holm, rank-biserial r

**Why paired:** repositories differ from each other far more than the arms do, so each
repository is compared with itself across arms.

**Why Wilcoxon:** no normality assumption (n = 18, scores bunched at 0 and 1), and it uses
the size of each difference, so it's more powerful than the sign test the pilot used.

**Why Holm:** three comparisons per model and metric would give about a 15% chance of a
false positive; Holm keeps it at 5% while being less harsh than Bonferroni. Applied
within each model's three comparisons, not across models, since each model is a
replication of the same question.

**Why rank-biserial r and tie counts:** with 18 repositories a p-value doesn't say how
big the effect is, and ties (from the best arm hitting a perfect score) explain why some
comparisons are underpowered.

### A16. Running on a GPU cluster, one model per job

**Why:** 3 models × 3 arms × 18 repositories plus judging is days of work on a laptop.
One generator per job means one model's failure doesn't block the others.

**Cost:** jobs ran under different load, so latency isn't compared between models;
token counts are unaffected.

### A17. Reporting what didn't work

**Why:** the paper states the claims it declines to make: the dependency graph alone
doesn't reduce hallucination in two of three models, coverage saturates for the winning
arm, codellama:13b shows an unexplained context-window anomaly (14 of 53 generations at
exactly 4,098 input tokens), and absolute scores rest on an unreliable judge. Reviewers
trust a paper that shows its limits.

### A18. The revision (after review)

**Decision:** reviewers accepted the paper after minor revision. In response, a
retrieval (BM25) baseline was added at a matched token budget, repeat runs with
different seeds measure run-to-run variance, and secondary judges re-score the same
summaries.

**Why:** the obvious objection to "structure beats raw source" is "a retrieval system
would pick the relevant raw code just as well". A matched-budget retrieval arm answers
it directly, and the variance runs address run-to-run instability.

---

## Part B: The product

### B1. Purpose

**Decision:** turn the research pipeline into a dashboard: paste a GitHub link, get the
architecture, API, data models, a plain-English summary and a question-answering tab.

**Why:** the paper shows the approach works; the product shows it's useful. It reuses the
research parsers, graph builder and model provider unchanged, and writes nothing the
evaluation reads, so the published results can't be disturbed by product work.

### B2. Analyse once, serve every view from storage

**Decision:** clone and parse once, store the parse, file contents and derived insights
in SQLite, and serve every tab from that.

**Why:** cloning takes seconds and the clone is deleted after parsing; re-cloning per tab
would be slow and wasteful. SQLite needs no server, ships with Python, and is plenty for
one machine. The stored copy also lets the file viewer and Ask read source code long
after the clone is gone.

### B3. Staged background jobs; the dashboard opens early

**Decision:** cloning → parsing → indexing (the dashboard becomes usable here, about
two seconds after the clone) → Neo4j write → summary, in background threads.

**Why:** the structural tabs don't depend on the model, so nobody should wait 30-60
seconds for a summary to see the architecture. Structural work and model calls run on
separate worker pools; the model pool has one worker because two 7B generations at once
on a 16 GB laptop are slower than two in a row.

### B4. Surviving a restart

**Decision:** each in-progress row records the process running it; on start-up, rows
owned by a dead process are marked failed.

**Why:** otherwise a server restart left summaries showing "writing…" forever, and the
seeding command's rows were clobbered by a restarting server.

### B5. Product-only insights

**Decision:** the product layer adds:
- layer classification (setup, routes, middleware, services, data, tests);
- NestJS constructor injection (which service is injected into which controller);
- Express route locations, including chained `.route()` calls;
- ORM data models (Mongoose, TypeORM, Sequelize, sequelize-typescript, Prisma).

**Why:** these power the swimlanes, request-flow traces and data-model diagrams. They're
kept out of the research parse on purpose: populating the research schema's
`database_entities` would change the paper's ground truth.

### B6. Every structural view is deterministic

**Why:** the research showed models invent structure. So the graph, architecture,
endpoints, request flows, data models and dependencies come only from the parser. The
same commit always gives the same result, and nothing on those tabs can be hallucinated.
That's also the product's strongest claim to visitors.

### B7. Cytoscape for big diagrams, Mermaid for small ones

**Decision:** the knowledge graph and architecture swimlanes are interactive Cytoscape
views; the ER diagram and NestJS module map are Mermaid.

**Why:** a Mermaid architecture diagram of a 200-file repository was unreadable, with no
way to zoom, filter or click. Cytoscape allows a fixed swimlane layout, hover to light up
dependencies, and click to open a file. Mermaid stays where diagrams are small and its
notation fits (ER diagrams).

### B8. Knowledge graph grouped by feature, with coloured arrows

**Decision:** nodes sit inside a labelled box per feature folder (auth, users, files…);
each box is laid out separately and boxes are placed by how much they link to each
other; links between features are faint until a node is clicked; edges are coloured by
relationship, with bigger arrowheads.

**Why:** one force layout over 300+ nodes produced a hairball, and with one layout
over everything, links between features dragged the boxes over each other. Developers
think in features, so grouping by folder matches how they read code. Colour tells
imports apart from dependency injection and endpoint links without a click.

### B9. Summary written from the knowledge graph

**Why:** that's the paper's result. When a repository's graph is too big for the
window, detail is shed in order of least value to a summary (tests first, then most
import lists, then DTO/type files) instead of letting the model drop the start of the
prompt.

### B10. Ask: lexical and structural retrieval, not embeddings

**Decision:** the question's words are matched against file paths, class/method names,
endpoint paths and source text, with concept expansion ("authentication" also matches
`jwt`, `passport`, `guard`); the top five files go to the model with a structural
overview.

**Why:**
- Code questions are mostly about named things, where exact identifier matching works best.
- It needs no embedding model or vector database.
- The answer can list exactly which files it read.

Concept expansion was added after a question about authentication retrieved the wrong
files.

### B11. "Never quote code you weren't shown"

**Why:** when retrieval missed the right file, the model fabricated a plausible excerpt
of a file it had never seen (invented passport.js code). The prompt now forbids quoting
anything not in the context, and the UI shows the files used so the answer is checkable.

### B12. Making Ask fast on a laptop

**Decision:**
- The repository overview is a fixed system-prompt prefix, which Ollama reuses between
  questions.
- That prefix is read ahead of time when the Ask tab opens.
- First questions are cached per analysis and replay instantly.
- Answers stream word by word.
- Suggested questions are pre-answered during seeding.

**Why:** the local model reads about 160 tokens/s and writes about 17 tokens/s. Reusing the
prefix cut the wait for the first word from ~30 s to ~6 s.

**What we kept:** answer length (~200 words) and five files were kept at the
user's request, rather than traded for speed.

### B13. Local model on the demo machine

**Decision:** qwen2.5-coder:7b through Ollama, running natively, not in Docker; kept
loaded for 45 minutes; context window passed explicitly.

**Why:**
- Fits in 16 GB alongside everything else, and is the research's model family.
- On a Mac, Docker can't use the GPU, so Ollama in Docker would be several times slower.
- Keeping the model loaded, and always requesting the same context size, avoids
  reloads that cost seconds each.

### B14. Interface

**Decision:**
- One colour per architectural layer, used identically in every view.
- Shape shows the kind of node.
- Light and dark themes.
- A status line for Ollama, the model and Neo4j.
- Every summary and answer labelled with the model that wrote it.

**Why:** a visitor learns the colour code once and reads every tab with it. Status dots
say what's missing instead of failing mysteriously. Model labels keep it honest about
which parts are AI.

### B15. Demo operations

**Decision:** `demo.sh` starts everything and stops it on Ctrl-C; a seed command
pre-analyses the demo repositories and pre-answers their suggested questions; a written
runbook (`docs/DEMO_SCRIPT.md`).

**Why:** a live demo shouldn't depend on network speed or model speed at the moment
someone is watching.

---

## Part C: Deployment

### C1. Groq for the deployed product

**Decision:** with a Groq key the summary and Ask use Groq (`openai/gpt-oss-120b` by
default); without one, the local model. Locally, a failed Groq call falls back to the
local model.

**Why:** the paper is submitted and its constraints no longer bind the product. A
deliverable has to run where there's no GPU: a hosted model needs only a small CPU
server, answers in seconds instead of 10-60 s, and is a much larger model.

**What stays the same:**
- The research pipeline still uses only local models, so nothing the paper measured
  changes.
- Groq is reached over plain HTTP (its API is OpenAI-compatible), so no extra SDK was
  added.

**Cost:** repository code is sent to Groq. Keep it local with `LLM_PROVIDER=ollama`.

### C2. One container

**Decision:** the dashboard is built to static files and served by the API on the same
port, from a slim image with only the product's dependencies.

**Why:**
- One service to deploy, and no CORS configuration.
- The research image carries torch and the evaluation stack the product never uses.

### C3. Public-mode protections

**Decision:** per-visitor hourly limits (10 new repositories, 40 questions; replaying a
stored answer is free); delete and re-analyse disabled; research endpoints switched off;
repositories capped at 60 MB.

**Why:** there are no accounts, so anyone with the link could otherwise use up the Groq
quota, delete stored analyses, or start long research runs. Limits are kept in memory,
which is right for one instance.

### C4. Neo4j off in the deployment

**Why:** every dashboard view is served from SQLite, so Neo4j adds nothing a visitor
sees. It's one setting to turn back on (e.g. with a free AuraDB), and the demo machine
keeps writing every analysis to Neo4j.

### C5. Shipping stored analyses with the image

**Decision:** the 9 repositories analysed on the demo Mac (with their summaries and
answers) are copied into a new deployment's store on first start.

**Why:** the free hosting tier has no persistent disk, so stored analyses vanish when it
sleeps. Seeding brings the examples back instantly with no model calls.

### C6. Render

**Why:** Railway (the first choice) wasn't accepting sign-ups. Render builds the same
Dockerfile from GitHub and has a free tier.

**Cost:** the free tier sleeps after about 15 minutes without visitors (about a minute to
wake), so open the site a few minutes before presenting.
