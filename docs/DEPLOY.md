# Deploying the dashboard

The root `Dockerfile` builds the whole product into one container: the dashboard is
compiled to static files and served by the API on the same port. The summary and Ask
use Groq's hosted models, so the server needs no GPU, no Ollama and no Neo4j. A small
instance (1 vCPU, 1 GB RAM) is enough.

The research setup (`backend/Dockerfile`, `docker-compose.yml`, local Ollama, the
evaluation endpoints) is separate and unchanged.

## What you need

- A Groq API key from https://console.groq.com/keys. You enter it in the host's
  settings, never in the repository.
- A host that builds a Dockerfile from GitHub and can mount a persistent volume, for
  example Railway or Render. On Render, a persistent disk needs a paid instance.

## Settings

The image sets sensible defaults; only `GROQ_API_KEY` is required.

| Variable | Default in the image | Meaning |
|---|---|---|
| `GROQ_API_KEY` | (none) | Required. Groq API key |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Any model id from Groq's models page |
| `LLM_PROVIDER` | `groq` | `ollama` to use a local Ollama instead |
| `LLM_FALLBACK` | `none` | `ollama` retries a failed Groq call on `OLLAMA_HOST` |
| `PUBLIC_MODE` | `true` | Per-visitor hourly limits, no delete or re-analyse, research endpoints off |
| `RATE_LIMIT_ANALYSES_PER_HOUR` | `10` | New repositories per visitor per hour |
| `RATE_LIMIT_ASKS_PER_HOUR` | `40` | Questions (and summary retries) per visitor per hour. Replayed answers are free |
| `MAX_REPO_SIZE_MB` | `60` | Larger repositories are refused before cloning finishes |
| `NEO4J_ENABLED` | `false` | `true` plus `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD` to also store the graph in Neo4j (e.g. AuraDB) |
| `PRODUCT_DB_PATH` | `/data/product.db` | SQLite store. Keep `/data` on a persistent volume |
| `CORS_ORIGINS` | (none) | Only if the dashboard is hosted on a different origin than the API |

## Railway

1. New project, then "Deploy from GitHub repo". Pick this repository and the `product`
   branch. Railway finds the root `Dockerfile`.
2. Variables: add `GROQ_API_KEY`.
3. Add a volume to the service, mounted at `/data`.
4. Settings, then Networking: generate a domain. Railway sets `PORT`; the image
   listens on it.

## Render

1. New, then Web Service. Connect the repository, branch `product`, runtime Docker.
2. Environment: add `GROQ_API_KEY`.
3. Add a disk mounted at `/data` (paid instance types only).
4. Health check path: `/health`.

## Checking a deployment

- `https://<your-domain>/api/system` should report `"provider": "groq"`,
  `"reachable": true` and `"model_available": true`. `model_available: false` means
  Groq no longer offers `GROQ_MODEL`; pick another id from Groq's models page.
- Open the site and analyse one of the example repositories. The summary should
  arrive within a few seconds.

## Running the image locally

```bash
docker build -t repointel .
docker run -p 8090:8000 -v repointel-data:/data -e GROQ_API_KEY=... repointel
```

Then open http://localhost:8090. To try it against the local model instead, add
`-e LLM_PROVIDER=ollama -e OLLAMA_HOST=http://host.docker.internal:11434`.

## Limits worth knowing

- Groq's free tier has per-minute and per-day request and token limits, and they
  change. When one is hit, the dashboard says the service is busy and to try again in
  a minute. A paid Groq plan raises them.
- Repository code is sent to Groq when a summary is written or a question is
  answered. Set `LLM_PROVIDER=ollama` on a machine with Ollama to keep it local.
- Rate limits are kept in memory, per instance. They reset on restart, and running
  several instances would multiply them.
