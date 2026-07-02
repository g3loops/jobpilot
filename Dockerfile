# JobPilot — Cloud Run container (FastAPI + 50k corpus + embeddings baked in).
# BUILD CONTEXT = the JobPilot/ project root (so both code/ and data/ are available).
#   gcloud run deploy jobpilot --source .   (run from JobPilot/)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.hf \
    JOBPILOT_DATA_DIR=/app/data

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*

# Python deps first (layer caching).
# Install CPU-only torch FIRST from PyTorch's CPU wheel index. sentence-transformers pulls
# torch, and pip's default is the CUDA build (~2-3 GB of unusable NVIDIA libs on a GPU-less
# Cloud Run VM). Satisfying torch up-front with the CPU wheel keeps the image small + build fast.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY code/requirements.txt .
RUN pip install -r requirements.txt

# Pre-bake the embedding model so the app starts fast and offline
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# App code
COPY code/jobpilot ./jobpilot
COPY code/server.py .
COPY code/web ./web

# Data — ship the enriched 50k snapshot AND the prebuilt 384-d embeddings.
# Shipping the vectors (vs regenerating at build) skips the slow ~30-min embed-on-CPU step
# and locks the deployed app to the exact vectors validated locally. The MiniLM model above
# still embeds the live query profile (and any future live-fetched jobs) at runtime.
COPY data/jobs_snapshot.csv ./data/jobs_snapshot.csv
COPY data/artifacts ./data/artifacts

# Fail-fast: confirm the shipped vectors load + align to the snapshot (cache hit, ~seconds).
# If they were missing/misaligned the app would silently re-embed at first request — assert instead.
RUN python -c "import warnings; warnings.filterwarnings('ignore'); from jobpilot import store, embeddings; df = store.load_corpus(); v = embeddings.load_cached_embeddings(df); assert v is not None and len(v) == len(df), 'shipped embeddings missing or misaligned'; print(f'OK: {len(v):,} prebuilt embeddings loaded + aligned')"

EXPOSE 8080
# Cloud Run injects $PORT; default to 8080 locally. exec form so uvicorn is PID 1 (clean SIGTERM).
CMD exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}
