# Likely questions, and answers

Prep for the final presentation. Answers describe what the product does today; where
something isn't built, they say so. Each "what would you change" answer names the
change and why it isn't done yet, so it reads as a plan rather than an excuse.

## 1. Applications: who is this for?

**Q: Who would actually use this?**
A developer joining a team, who needs to understand an unfamiliar backend in an
afternoon instead of a week. Also: a tech lead reviewing a codebase before an
acquisition or an outsourcing handover, a consultant auditing a client's API, and
students reading open-source code to learn how real projects are structured.

**Q: What problem does it solve that reading the code doesn't?**
Reading code answers "what does this file do". It doesn't show how the 200 files
connect: which routes call which services, which services touch which data models,
what the request path is. The dashboard extracts that structure in seconds and makes it
browsable; the AI then explains it in plain English.

**Q: Why not just paste the code into ChatGPT?**
A large repository doesn't fit in a prompt, and a model handed raw source has to do
static analysis and writing at once. Our research measured what that costs: with the
knowledge graph instead of raw source, coverage of the real structure rose up to 4.4×
for the weakest model, hallucinated claims fell by more than half for all three models,
and the prompt was 1.3–2× smaller. The product applies exactly that finding.

**Q: Could a company use this internally?**
Yes, with two changes: private-repository access (a GitHub token or app install) and
running the model locally or on their own server, so code never leaves their network.
The second already works: set `LLM_PROVIDER=ollama` and nothing is sent anywhere.

**Q: Where else could the same idea apply?**
Onboarding documentation that stays current (regenerate on every merge), API
inventories for security reviews ("list every endpoint without auth middleware"),
migration planning ("which files depend on the old ORM?"), and code review bots that
explain a change in terms of the architecture it touches.

## 2. How it works: design choices

**Q: Which parts use AI, and which don't?**
Only two: the summary on the Overview tab and Ask. Both are labelled with the model
that wrote them. The knowledge graph, architecture diagram, endpoints, request flows,
data models and dependency groups are extracted directly from the code by a parser:
the same commit always gives the same result, and nothing there can be hallucinated.

**Q: How does the parsing work?**
tree-sitter builds a syntax tree for every JavaScript and TypeScript file. Framework
parsers (one for Express, one for NestJS) walk those trees for routes, controllers,
classes, imports, decorators and ORM models, and produce one common structure that
everything downstream reads.

**Q: Why a knowledge graph?**
Code is a graph: files import files, controllers inject services, endpoints are
handled by methods, models relate to models. Storing it as a graph makes those
questions direct lookups, and it's the representation our research showed gives the
best summaries. It's written to Neo4j, and the dashboard serves every view from a
stored copy of the same parse in SQLite, so the views stay fast.

**Q: Is Neo4j actually used?**
Yes, on the demo machine: every analysis is written to it, and it can be explored and
queried with Cypher in Neo4j Browser. The dashboard itself reads from SQLite, so the
public deployment runs without Neo4j and shows identical results. Turning it on there
is configuration only.

**Q: Are the Mermaid diagrams AI-generated?**
No. They're produced by code from the extracted graph: the ER diagram from ORM model
definitions, the NestJS module map from `.module.ts` imports.

**Q: How does Ask find the right code?**
Lexical and structural retrieval: the question's words are matched against file paths,
class and method names, endpoint paths and source text, with concepts expanded
("authentication" also matches `jwt`, `passport`, `guard`). The five best files are
sent with a structural overview of the repository, and the answer lists the files it
read so you can check it. The prompt forbids quoting code it wasn't shown.

**Q: Why not embeddings / a vector database?**
Code questions are mostly about named things ("what does UsersService do?"), where
exact identifier matching beats semantic similarity, and lexical retrieval needs no
extra model, index or service. Embeddings would help with vague questions; that's on
the improvement list.

**Q: Which model does it use?**
Deployed: Groq's hosted `openai/gpt-oss-120b` (configurable), so summaries take seconds.
On the demo machine without a key: `qwen2.5-coder:7b` locally through Ollama, the
model family from the research. If Groq fails, the local model takes over.

**Q: How is it hosted?**
One Docker container: the React dashboard is built to static files and served by the
FastAPI backend on the same port. Analyses are stored in SQLite. It deploys to Render from GitHub.

## 3. Limits: what it can't do yet

**Q: Why only Express and NestJS?**
That was the agreed scope for the research, and they are the two most common Node.js
backend styles (minimal routing vs. decorator-based). The parser layer is pluggable:
a new framework is one class implementing `detect()` and `parse()` that produces the
same structure, and every tab works unchanged.

**Q: Does it work on any Express or NestJS repo?**
It needs `package.json` at the repository root, so monorepos (Nx, Turborepo, a
`backend/` subfolder) are rejected today. Repositories must be public, and the
deployment caps them at 60 MB.

**Q: How accurate is the endpoint list?**
High for conventional code, with known, documented gaps: Express routes whose mount
path is a runtime value (a loop over an array of routes) keep router-relative paths;
NestJS routes declared with constants (`@Controller(routes.users)`) lose their path;
GraphQL resolvers aren't counted; TypeScript path aliases aren't resolved. Each is
written up in the README with the repository that exposed it.

**Q: Does it show which function calls which?**
Not yet. The graph has file imports, class membership, dependency injection,
endpoint-to-handler links and model relations, but not function-level calls. The
schema has a `CALLS` relationship reserved for it.

**Q: Can the AI summary be wrong?**
Yes, and the dashboard says so: it's the one model-written part of the Overview page.
It's written from the extracted graph rather than raw code, which our research showed
roughly halves hallucinated claims, but it isn't zero. Everything structural around it
is extracted, not generated.

**Q: What about private code and privacy?**
In the deployed version, repository code is sent to Groq when a summary is written or
a question is answered. For private code, run it with the local model: nothing leaves
the machine. Only public GitHub repositories can be analysed today.

**Q: Can many people use it at once?**
For a demo, yes. Each visitor is limited per hour (10 new repositories, 40 questions;
replayed answers are free), analysis jobs run in background threads, and the model
calls queue one at a time. It's a single instance with SQLite and in-memory limits, so
real scale would need a job queue, a shared database and limits kept in Redis.

## 4. What we'd change or build next

**Q: What would you build next, in order?**
1. Monorepo support: detect workspaces and analyse each backend package.
2. Function-level call graph, so request flows go method to method.
3. Private repositories through a GitHub App.
4. Re-analyse on push (webhook), with a diff view: "this PR added two endpoints and a
   new dependency on PaymentsService".
5. More frameworks: Fastify and Koa are close to Express; Spring Boot and Django would
   need new language grammars, which tree-sitter has.

**Q: How would you improve the AI answers?**
Hybrid retrieval (keep the identifier matching, add embeddings for vague questions),
following the graph from the best file to its neighbours rather than picking files
independently, and letting the user pin files to the context. Answers could also cite
line numbers, not just files.

**Q: How would you verify the AI's claims automatically?**
Check every identifier the summary mentions against the extracted graph and flag ones
that don't exist. The research already does this offline (a deterministic oracle that
scores summaries against parser-extracted facts); surfacing it in the product would put
a "checked against the code" mark on each claim.

**Q: How would you make it production-ready?**
User accounts, a proper job queue (Redis or a managed queue) instead of in-process
threads, Postgres instead of SQLite, rate limits in Redis, persistent storage, error
monitoring, and a cache keyed on commit SHA so a repository already analysed at that
commit is never parsed twice.

**Q: Could it generate documentation or diagrams for the repo itself?**
Yes, cheaply: the diagrams are already deterministic Mermaid, so exporting an
`ARCHITECTURE.md` with the module map, ER diagram, endpoint table and summary is mostly
formatting. Committing it back through a pull request would keep docs in sync.

**Q: What would you change about the research, given the chance?**
The ground truth leans on npm dependency names (about half of the facts), and the LLM
judge proved unreliable, which became the paper's main finding. We'd build a larger,
independently verified ground truth with more endpoints and data models, and score
with the deterministic oracle as the primary metric.

## 5. Questions about the research link

**Q: What did the research find, in one sentence?**
Giving a model a parsed knowledge graph instead of raw source makes its summaries
cover more of the real structure with fewer invented claims and fewer tokens, and
LLM-as-judge scoring is unreliable enough that it can hide or reverse such effects.

**Q: How does the product use that finding?**
The summary is written from the knowledge graph, never from raw source; every
structural view comes from the parser with no model involved; and Ask pairs the graph
overview with the most relevant files and shows which ones it read.

**Q: Why are the research models different from the product's model?**
The research compared small open models run locally, because the question was about
representations, not about which model is best. The product optimises for the user:
a faster, larger hosted model, with the research's local setup still available.
