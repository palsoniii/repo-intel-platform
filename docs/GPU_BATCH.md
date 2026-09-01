# Running the battery on a job-scheduled GPU

For an H100 reached through a job portal, where a container is submitted, runs, and
exits. Written for someone who has the portal open and wants the run started.

## Why the whole backend is not the container

The stack is four long-running services (Neo4j, Ollama, FastAPI, the dashboard). A job
portal runs a process that starts, works, and exits — that fits inference, not services.
And of the pipeline, only generation wants a GPU:

| Stage | Needs | Cost |
|---|---|---|
| clone, tree-sitter parse | network, CPU | seconds |
| Neo4j write, context render | a database, CPU | seconds |
| **generation** | **GPU** | **hours** |
| oracle scoring | CPU only | under a minute |

Putting the first two on the GPU node buys nothing and costs allocation — and compute
nodes frequently have no route to `github.com` and nowhere to run a database anyway.

So the split is: **render the prompts where the network and the database live, ship the
file, let the GPU do nothing but generate.**

A *context pack* is that file: for every repository, the parse plus all three rendered
contexts. Because it stores the rendered text rather than re-deriving it, a packed run
is also exactly reproducible — upstream repos move, and `main` today is not `main` last
week.

## Why Ollama and not PyTorch or vLLM

The image is built on `ollama/ollama`, not a `pytorch/` or `tensorflow/` base. Ollama
ships its own CUDA runtime, so a torch base would be several GB of unused layer.

The real reason is comparability. **Ollama serves 4-bit quantized weights.** Every
result reported so far came from those weights. vLLM or HF in fp16 would use an H100
far better and produce *different text from the same model* — a different experimental
condition, under which none of the existing 157 summaries remain comparable.

Keeping Ollama underuses the GPU and is still dramatically faster than the 4GB laptop
card the batteries were run on. If you later want native precision, add it as a separate
arm and report the quantization gap as a finding — do not silently swap the engine.

## One-time setup

**1. Build the pack** — needs network and Neo4j, so do it on a laptop or a login node:

```bash
cd backend
python -m scripts.build_context_pack $(cat ../18_repo_urls.txt) \
  --out evaluation_results/context_pack.json \
  --notes "18-repo candidate set"
```

It prints each repo and its three context sizes. A repo that fails to clone or parse is
skipped and reported, not fatal.

**2. Stage the model weights.** ~15GB, and the compute node may not be able to pull
them. Somewhere with network, against the directory you will mount:

```bash
OLLAMA_MODELS=/shared/ollama ollama pull qwen2.5-coder:7b
```

Repeat for `codellama:7b-instruct` and the judge `gemma2:9b`. Mount that directory at
`/root/.ollama` in the job. The entrypoint checks for each requested model up front and
exits before spending any allocation if one is missing.

**3. Build and push the image** — `--platform linux/amd64` is not optional:

```bash
docker build --platform linux/amd64 -f backend/Dockerfile.gpu -t <registry>/repo-intel-gpu:1 backend
```

The dev machines here are Apple Silicon (arm64) and every H100 host is x86_64. Without
the flag, `docker build` produces an arm64 image the cluster cannot execute — and the
failure appears only when the job finally starts, after the queue wait. Verify before
pushing:

```bash
docker image inspect <registry>/repo-intel-gpu:1 --format '{{.Architecture}}'
```

It must print `amd64`. On a Mac this cross-builds under emulation: slower to build,
native speed to run.

## Running a job

```bash
docker run --rm --gpus all \
  -v /shared/ollama:/root/.ollama \
  -v /shared/repo-intel/evaluation_results:/app/evaluation_results \
  -v /shared/repo-intel/annotations:/app/annotations:ro \
  -e CONTEXT_PACK=/app/evaluation_results/context_pack.json \
  -e MODEL=qwen2.5-coder:7b \
  -e JUDGE_MODEL=gemma2:9b \
  -e ANNOTATIONS_DIR=/app/annotations \
  <registry>/repo-intel-gpu:1
```

Outputs land in the mounted `evaluation_results` as `battery_<model>.csv` and `.db`.

**One generator per job.** Not a memory limit on an 80GB H100 — it keeps execution
conditions identical to the runs this will be pooled with. Submit three jobs, one per
generator, and combine the CSVs.

**The judge must not be the generator.** The entrypoint refuses when they match, and so
does `run_scored_ablation()`. Self-judging reverses the ranking of representations
(`REPORT.md` §6.2), and the resulting table looks entirely plausible.

## After the run

Bring the CSV/DB back and score locally — the deterministic oracle is pure CPU and needs
no GPU:

```bash
python -m scripts.run_oracle    # 10,062 fact-level decisions, under a minute
python -m scripts.stats_oracle
```

## Checks worth making on the first job

- `nvidia-smi` output appears at the top of the log. If it says the tool is missing, the
  job is not on a GPU and every latency figure is meaningless.
- The staged-model list shows both models before generation starts.
- Wall-clock from `time` roughly matches the summed per-row latencies. A large gap is
  scheduler overhead, which must not be reported as generation time.

## What is not solved here

- **Latency comparability.** Figures from this H100 cannot be pooled with the RTX 3050
  numbers in `REPORT.md` §5.7.1. Token counts are hardware-independent and can be.
- **The judge is still a model call**, so it runs inside the GPU job. Only the oracle is
  free to run anywhere.
- **`OLLAMA_NUM_CTX` is pinned to 8192** in the image, matching the study. Changing it
  changes what every arm sees and breaks comparability with everything already run.
