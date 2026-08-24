# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# git: required by acquisition/clone.py (GitPython shells out to it) to clone
# evaluation repos. build-essential: some pinned deps (e.g. tree-sitter builds)
# need a compiler on slim base images.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# BuildKit cache mount: on a slow/flaky connection, a killed `RUN` normally loses
# the entire layer's download and restarts from zero (unlike Ollama's blob-resuming
# pulls). Mounting pip's cache directory as a persistent BuildKit cache survives a
# killed/retried build, so a stalled attempt only re-downloads what didn't finish,
# not everything -- this matters a lot for torch (bert-score's dependency, easily
# the single largest download in this image).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# nltk's BLEU/METEOR need these corpora downloaded once, not at every container
# start -- baked into the image so a fresh container is immediately usable offline.
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab'); nltk.download('wordnet'); nltk.download('omw-1.4')"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
