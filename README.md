# JobPilot

**BAX-423 Big Data — Spring 2026 Final (Option B: Job Matcher + Resume Builder)**
UC Davis MSBA · Gayathri Valsalakumari · Instructor: Dr. Rahul Makhijani

JobPilot ingests ~50k job postings from a 47 GB public dump (plus live Adzuna postings),
matches them to a candidate profile using sentence embeddings, ranks them through a
multi-stage scorer, **learns from accept/reject feedback online**, and generates a tailored
résumé + cover letter — all behind a clean web UI with built-in analytics.

> **Live demo (Cloud Run):** https://jobpilot-230916539522.us-central1.run.app
> **Local run:** see below — one command, no API keys required.

---

## 1. Quick start (local)

```bash
cd code
pip install -r requirements.txt           # see §5 for the Python version used
uvicorn server:app --port 8000            # -> http://localhost:8000
```

On startup the app loads the 50,302-row snapshot, loads the prebuilt 384-d embeddings, loads
the MiniLM model, and (if Adzuna keys are set) pulls a batch of live postings — about 20–30 s.
Then open **http://localhost:8000** and click through **Matches → Feedback → Analytics → About**.
Pick a test persona (**Aisha / Marcus / Priya / Kenji**) to auto-fill a profile, or upload your
own résumé (PDF) to build one.

**No credentials are needed to run it.** Both optional keys live in `code/.env` (git-ignored,
**not** in the submission):
- `ANTHROPIC_API_KEY` → Claude-Haiku résumé/cover tailoring; without it a deterministic
  template backend is used (works fully offline).
- `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` → the live-postings fetch at startup + the **↻ Adzuna**
  refresh button; without them the app runs on the shipped 50k snapshot.

> ⚠️ The grading rubric scores **0 on dimensions 1–4 if the code does not run.** The single
> `uvicorn server:app` command above is the one supported entry point.

---

## 2. What's in `data/`

| File | Size | What it is |
|------|------|------------|
| `data/jobs_snapshot.csv` | 155 MB | **The deliverable snapshot: 50,302 enriched postings** (12-field canonical schema). This is the *output* of the streaming/dedup/enrich pipeline. |
| `data/artifacts/job_embeddings.npy` | 74 MB | Cached 384-d MiniLM embeddings (so a local run doesn't re-embed for ~9 min). |
| `data/artifacts/job_ids.npy` | 1.2 MB | Row-id alignment for the embeddings. |

> **If `data/artifacts/` is absent** (e.g. a size-trimmed submission), the app simply
> **regenerates the embeddings on first launch** (~9 min on CPU, one time) and caches them —
> the same single `uvicorn` command still works, it's just slower the first time.

> The original **47 GB Kaggle dump** (`techmap-jobs-dump-2021-09.json`, 3.47M records) is **not
> included** in the submission — it's the raw input the pipeline samples from, not a deliverable.

---

## 3. Rebuilding the snapshot (optional — already built)

```bash
cd code
python build_index.py --live --target 50000      # re-sample + stream + dedup + enrich + embed
# add  --pubsub on   to force streaming through real Google Pub/Sub instead of the in-process fallback
```

This re-runs the full offline pipeline: byte-offset sampling of the 47 GB dump → normalize to
the canonical schema → (optional) live Adzuna pull → streaming ingest → **Bloom-filter dedup** →
feature enrichment → MiniLM embedding → writes `jobs_snapshot.csv` + `artifacts/*.npy`.
You do **not** need to run this to use the app; the snapshot ships pre-built.

---

## 4. Environment variables (all optional)

Put these in `code/.env` (git-ignored; **not** in the submission). Everything works without them.

| Var | Used for | Default if unset |
|-----|----------|------------------|
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Live Adzuna postings when rebuilding the snapshot | Skips the live pull (uses the dump only) |
| `ANTHROPIC_API_KEY` | Optional Claude-generated résumé/cover text | Falls back to the offline template backend |
| `JOBPILOT_DATA_DIR` | Override the `data/` location | `../data` relative to `code/` |
| `GOOGLE_CLOUD_PROJECT` / `PUBSUB_TOPIC` | Real Pub/Sub streaming (Cloud Run) | In-process streaming fallback |

---

## 5. Dependencies & environment

- **Python 3.11+** (developed on 3.13 locally; the Cloud Run image uses 3.11-slim).
- All pinned in `code/requirements.txt`. Key libs: `fastapi`, `uvicorn`, `sentence-transformers`
  (all-MiniLM-L6-v2), `scikit-learn` (cosine k-NN retrieval), `pandas`, `numpy`, `python-docx`,
  `pypdf`, `plotly`, `xlsxwriter`, `google-cloud-pubsub`.
- `protobuf` is pinned `>=4.25,<7` so `google-cloud-pubsub` and the rest agree.

---

## 6. Project layout

```
JobPilot/
├── code/
│   ├── server.py            # FastAPI app (the entry point)
│   ├── build_index.py       # offline pipeline -> snapshot + embeddings
│   ├── requirements.txt
│   ├── web/                 # custom HTML/CSS/JS frontend (index.html, style.css, app.js)
│   └── jobpilot/            # the Python package (ingest, embeddings, ranking, learning, …)
├── data/                    # snapshot CSV + cached embeddings (see §2)
├── prompts/prompts.md       # the prompts.md deliverable
├── brief/brief.pdf          # the technical brief (≤4 pp)
├── Dockerfile               # Cloud Run container (FastAPI; embeds at build time)
└── README.md
```

See `prompts/prompts.md` for the development prompt log and `brief/brief.pdf` for the
architecture, technique choices, benchmarks, and persona results.

---

## 7. The `jobpilot` package (module map)

| Module | Responsibility |
|--------|----------------|
| `ingest.py` | `normalize`, `BloomFilter`, `stream_ingest`, `sample_techmap` (47 GB byte-offset sampler) |
| `pubsub_pipeline.py` | Google Pub/Sub streaming (unique per-run subscription + ack) |
| `live_sources.py` | Adzuna live API |
| `features.py` | enrich: seniority, years_required, contract, visa, defense, company_size, salary |
| `embeddings.py` | MiniLM model, `build_job_embeddings`, `ANNIndex` (sklearn cosine k-NN) |
| `store.py` | load corpus + load/build index |
| `ranking.py` | hard filters + weighted multi-stage scorer + `rank_quality_metrics` (P@k, NDCG) |
| `learning.py` | `AdaptiveLearner` — online reward learning + ε-greedy (stateless for the API) |
| `generate.py` | structured résumé/cover-letter `.docx` generation (+ ATS keywords) |
| `explain.py` | "why ranked here" reasons |
| `analytics.py` | top skills, salary/location/source demand, `CountMinSketch` |
| `benchmark.py` | embedding-vs-keyword (TF-IDF) A/B across personas |
| `personas.py` | the 4 test personas + machine-checkable pass criteria |

---

## 8. Hosting

Deployed to **Google Cloud Run** from the project root:

```bash
gcloud run deploy jobpilot --source . --region us-central1 \
  --memory 2Gi --cpu 2 --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=<project>,PUBSUB_TOPIC=jobpilot-postings
```

The Dockerfile installs **CPU-only torch** and **ships the prebuilt embeddings** (`COPY
data/artifacts`) alongside the snapshot, so the running container starts in seconds and the
build stays ~5 min; a build-time assert verifies the vectors align to the CSV. The build context
excludes the 47 GB dump via `.gcloudignore`. `--min-instances=1` keeps one instance warm for the
live demo.

> **Note on the résumé/cover backend:** the deployed app has `ANTHROPIC_API_KEY` set (Claude
> Haiku, tailoring only — never inventing experience). A grader running the submitted ZIP without
> keys gets the deterministic template backend, which is fully functional offline.
