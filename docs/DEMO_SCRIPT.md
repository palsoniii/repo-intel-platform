# Demo runbook (2026-10-25)

## The day before

1. `./demo.sh --seed`: pre-analyses every repo in `demo_repos.txt` and pre-answers
   each repo's suggested questions. Each repo line should end `summary=done`, and each
   question gets an `answered:` line.
2. Open every seeded repository once and click through all eight tabs.
3. Ask each repository one of its suggested questions, so you know the answers.
4. Plug in the charger. The model is much slower on battery with low-power mode on.

## Thirty minutes before

- Quit everything heavy (browsers with many tabs, Docker images you don't need). The
  7B model needs ~5 GB of the 16 GB.
- `./demo.sh`, then open http://localhost:5180. All three dots under the search box
  (Ollama, qwen2.5-coder:7b, Neo4j) should be green.
- Ask one throwaway question so the model is loaded. The API also warms it on start
  and keeps it resident for 45 minutes after each use.

## The flow (about 8 minutes)

1. **Home.** "Paste a GitHub link to an Express or NestJS repo." Click a pre-analysed
   card (NestJS RealWorld) rather than typing, so nothing waits on the network.
2. **Overview.** The AI summary, then the point: *every number on this page comes from
   the parser, not the model.* Mention "Start reading here", the most-imported files.
3. **Knowledge graph.** Search `ArticleService`, click it: its methods, the controller
   that injects it, and the entities it injects. "This is the graph the summary is
   written from, and it's stored in Neo4j."
4. **Architecture.** Swimlanes from entry point to data. Hover a service to light up
   what depends on it. Scroll down to the NestJS module map.
5. **API.** Open `POST /articles`: the request flow (controller → service → entities)
   and the handler's source, highlighted.
6. **Data models.** The ER diagram, extracted from the TypeORM decorators.
7. **Ask.** Click a suggested question: it was answered during seeding, so it appears
   instantly. Point at "Read", the files it was given: "it's told not to quote code it
   wasn't shown." Then type a new question live: about 6 s to the first word, ~12 s total.
8. **Research.** The paper's result in one chart: a knowledge graph beats raw source on
   coverage and hallucination, with 1.3–2× fewer input tokens. "That's why the product
   works the way it does."
9. **Live (if time and nerve allow).** Paste a fresh small repo, e.g.
   `https://github.com/bezkoder/node-express-sequelize-postgresql`. The dashboard opens
   in a few seconds while the summary keeps writing.

## If something goes wrong

| Symptom | Fix |
|---|---|
| Red Ollama dot | Open the Ollama app; `ollama list` should show the model |
| Red Neo4j dot | Start Docker Desktop. Everything still works without it, except the "Stored in Neo4j" badge |
| Summary stuck on "writing" | It's slow, not broken (30–60 s). Click through other tabs meanwhile |
| Summary failed | "Try again" on the Overview card |
| Answer is wrong | Say so: it's a 7B local model. The structural tabs don't depend on it |
| Fresh repo rejected | Only Express.js/NestJS with `package.json` at the root. Monorepos are rejected |

## Likely questions

- **Why local models?** Code never leaves the machine, and running costs nothing. Both
  were project constraints.
- **Why not just paste the code into ChatGPT?** Raw source makes the model do static
  analysis and writing at once; the paper measures how much worse that is.
- **Other languages?** The parser layer is pluggable (`app/parsers/`). Two frameworks
  were the agreed scope.
- **How accurate is it?** The structural tabs are deterministic. Endpoint extraction has
  known gaps, e.g. routes mounted from runtime values (see README, "Known gaps").
