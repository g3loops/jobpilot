# JobPilot — Session Handoff (continue in a new Claude session)

> Paste this whole file into the new session, or open it from the project root. It captures
> the full state of the build so you can continue without re-discovering anything.

---

## 0. TL;DR — where we are
- **Project:** JobPilot (Option B) for **BAX-423 Big Data, Spring 2026** final (UC Davis MSBA, Dr. Rahul Makhijani).
- **A job matcher + resume builder.** Ingests 50k postings, matches to a profile, ranks, learns from
  feedback, generates tailored resume/cover letter, exports, shows analytics.
- **ALL 6 core capabilities + several bonuses are built and verified.**
- **Current app = FastAPI backend (`server.py`) + custom HTML frontend (`web/`)** — it matches the
  user's approved mockup (`/Users/Gayathri/Downloads/ui-mockup-v2.html`). An older Streamlit app
  (`code/app.py`) exists but is **superseded** (kept for reference).
- **Deadline:** project due **Fri June 5, 2026 11:59pm PT**; live 1:1 demo **Sat June 6**. (Today in-session was June 4.)
- **What's LEFT:** (1) point Dockerfile at uvicorn, (2) GCP auth + Pub/Sub topic + **Cloud Run deploy**,
  (3) **brief.pdf** (≤4pp), (4) **README**, (5) final **ZIP**. Details in §8.

---

## 1. Paths
- **Project root:** `/Users/Gayathri/Desktop/Spring Quarter/Big Data/Final Assignment/JobPilot/`
- `code/` — all source
  - `server.py` — **FastAPI app (current/primary)**
  - `app.py` — old Streamlit app (superseded; themed to mockup but hit framework limits)
  - `build_index.py` — offline pipeline that builds the snapshot + embeddings
  - `requirements.txt`
  - `jobpilot/` — the Python package (see §4)
  - `web/` — `index.html`, `style.css`, `app.js` (the custom frontend = the mockup)
  - `.env` — Adzuna creds (git-ignored); `.env.example` — template
  - `.streamlit/config.toml` — (only for the old streamlit app)
- `data/`
  - `jobs_snapshot.csv` — **50,302 enriched postings (155 MB)** ← the offline snapshot deliverable
  - `artifacts/job_embeddings.npy` (75 MB) + `job_ids.npy` — cached 384-d embeddings
  - `techmap-jobs-dump-2021-09.json` — **47 GB Kaggle dump** (3.47M records; NOT in ZIP/image)
  - `build_log.txt`
- `prompts/prompts.md` — **the prompts.md deliverable** (21 detailed entries, kept up to date)
- `brief/` — empty (brief.pdf still TODO)
- `Dockerfile` (at JobPilot root), `.dockerignore`, `.gitignore`
- Mockups: `/Users/Gayathri/Downloads/ui-mockup.html` (original dark) and `ui-mockup-v2.html` (approved light theme)

---

## 2. How to run locally
```bash
cd "/Users/Gayathri/Desktop/Spring Quarter/Big Data/Final Assignment/JobPilot/code"
uvicorn server:app --port 8000          # FastAPI app -> http://localhost:8000
# (loads 50k corpus + embeddings + MiniLM model at startup, ~15s)
```
- Old Streamlit (reference only): `streamlit run app.py` → :8501
- Rebuild snapshot (rarely needed; snapshot already exists):
  `python build_index.py --live --target 50000` (add `--pubsub on` to force real Pub/Sub)

**Python:** local is `/opt/anaconda3` Python 3.13. Key libs installed: fastapi, uvicorn, python-multipart,
sentence-transformers, scikit-learn, pandas, numpy, plotly, pypdf, python-docx, xlsxwriter, requests,
python-dotenv, google-cloud-pubsub, **protobuf 6.33 (pinned >=4.25,<7)**.

---

## 3. Architecture (current)
```
OFFLINE BUILD (build_index.py, run once -> already done):
  47GB Kaggle dump --byte-offset sampling(L2)--> normalize -> canonical 12-field schema
  + live Adzuna (bonus) --> stream: Pub/Sub(if avail) else in-process producer->queue->consumer (L3)
  -> Bloom-filter dedup (L2) -> features.enrich -> embed (MiniLM 384-d, L5)
  -> data/jobs_snapshot.csv (50,302) + artifacts/*.npy

RUNTIME (server.py FastAPI + web/ frontend):
  load snapshot + embeddings once -> REST API:
    /api/options, /api/match, /api/feedback, /api/generate, /api/export,
    /api/upload-resume, /api/analytics, /api/pubsub-demo
  Frontend (web/index.html+style.css+app.js) = the approved mockup, calls those endpoints.
  Stateless: client holds learner state + excluded set, sends back each call (Cloud-Run friendly).
```
**Matching:** profile -> MiniLM embed -> sklearn cosine k-NN candidate gen (1000) -> hard filters
(salary/location/contract/seniority/defence/visa/company-size; never exclude on unknown) -> weighted
score (similarity .45, skills .25, title .15, salary .10, seniority .05) -> re-rank -> top 25.

---

## 4. The `jobpilot/` package (module map)
- `config.py` — paths, **CANONICAL_FIELDS** (12), COLUMN_ALIASES, SNAPSHOT_TARGET=50000, loads `.env`
  (ADZUNA_APP_ID/KEY, ANTHROPIC_API_KEY). DATA_DIR overridable via `JOBPILOT_DATA_DIR` env.
- `skills.py` — controlled SKILL_PATTERNS vocab (~33), `extract_skills`, `skill_overlap`.
- `ingest.py` — `normalize`, **`BloomFilter`**, `IngestStats`, **`stream_ingest`** (in-process streaming),
  **`sample_techmap`** (random byte-offset sampler for the 47GB file), `parse_techmap_record`, `generate_synthetic`.
- `features.py` — `enrich` adds: seniority, years_required, is_contract, sponsors_visa, is_defense,
  company_size, salary_value.
- `live_sources.py` — Adzuna API (`fetch_adzuna`, `fetch_live`, `adzuna_available`).
- `pubsub_pipeline.py` — **Google Pub/Sub** streaming (`pubsub_available`, `stream_through_pubsub`);
  uses a UNIQUE per-run subscription + ack so Cloud Run multi-instance/leftover msgs can't corrupt counts.
- `profile.py` — `UserProfile` dataclass (skills, roles, locations, dealbreaker fields, education, experience,
  contact), `extract_pdf_text` (pypdf), `build_profile_from_resume`.
- `personas.py` — **5 personas** + machine-checkable pass criteria (see §5).
- `embeddings.py` — `get_model` (all-MiniLM-L6-v2), `embed_texts`, `build_job_embeddings`,
  `load_cached_embeddings`, **`ANNIndex`** (sklearn cosine k-NN; FAISS removed — see §6).
- `store.py` — `load_corpus` (reads snapshot CSV), `load_index` (loads/embeds + builds ANNIndex).
- `ranking.py` — DEFAULT_WEIGHTS, `passes_filters`, `score_job` (returns per-signal breakdown),
  `rank_jobs` (exclude_ids param), `rank_for_profile`, `rank_quality_metrics` (precision@k + NDCG).
- `learning.py` — **`AdaptiveLearner`** (rewards accept+1/reject-1/skip-0.2; baseline-subtracted online
  gradient; ε-greedy; `to_state`/`from_state` for stateless API), `simulate_learning` (benchmark curve).
- `ats.py` — `ATS_VOCAB`, `extract_jd_keywords`, `ats_match` (per-job ATS coverage % + missing keywords).
- `explain.py` — `explain_job` ("why ranked here" reasons + matched/missing skills).
- `generate.py` — `resume_sections` (structured: name/summary/education/experience/skills + ATS keywords),
  `resume_docx_bytes`, `cover_letter_docx_bytes`, `generate_resume`, `generate_cover_letter`
  (template default; optional Claude-haiku if ANTHROPIC_API_KEY set — currently blank, template used).
- `export.py` — `to_csv_bytes`, `to_excel_bytes`, `to_json_bytes`.
- `analytics.py` — `top_skills`, `salary_distribution`, `demand_by_location`, `demand_by_source`,
  `summary_stats`, **`CountMinSketch`** + `count_skills_cms` (L2 benchmark).
- `benchmark.py` — embedding-vs-keyword(TF-IDF) **A/B benchmark** across personas.

---

## 5. The 5 test personas (all PASS)
1. **Aisha** — career pivoter to ML. Top-10: 0 Senior/Staff, 0 defence. PASS (P@10 1.0).
2. **Marcus** — new grad, US, ≥$80k, no 3+yr, no contract. PASS (P@10 0.6–0.8).
3. **Priya** — experienced, NYC/remote, ≥$200k, no junior, no tiny startups. PASS (P@10 0.9).
4. **Kenji** — international/visa, US, ≥$120k, no contract. PASS (P@10 0.43).
5. **Gayathri (the USER)** — Financial Analyst, CA only, ≥$90k. Dealbreaker "no 5+ yrs" but pass criteria
   "zero 4+ yrs" → resolved by setting `max_years_required=3` (exclude 4+). Education/experience filled in
   personas.py for the resume. PASS (P@10 0.9–1.0).

---

## 6. Key decisions & gotchas (DON'T re-litigate these)
- **FAISS removed.** It segfaults when loaded alongside PyTorch (OpenMP conflict) — can't be caught, would
  crash the app. Using **sklearn brute cosine k-NN** (~30 ms/query at 50k). Documented in embeddings.py.
- **protobuf pinned `>=4.25,<7`** (resolved to 6.33). google-cloud-pubsub pulled protobuf 7 which breaks
  Streamlit; pin keeps both happy. It's in requirements.txt.
- **Kafka → Google Pub/Sub.** User chose Pub/Sub + Cloud Run. All Kafka files removed (kafka_pipeline.py,
  kafka_demo.py, docker-compose.yml, live.py). In-process streaming remains as the offline fallback.
- **Embeddings generated at `docker build`** (option B): the Dockerfile RUN-step builds embeddings INSIDE
  the image from the CSV, so we ship only the enriched CSV (not the .npy). Runtime stays instant.
- **The snapshot is the streaming pipeline's OUTPUT**, not a static file. Spec explicitly allows offline
  gathering ("does not have to run live with each use" + "offline snapshot so graders can run without API access").
- **Found+fixed real bugs:** missing `import json` in ingest (masked by bare except); "ca" substring-matching
  "chiCAgo" (word-boundary fix); UK remote job passing us_only; learner's first-feedback zero-gradient
  (reordered baseline update); "CV"→"computer vision" skill false match; Pub/Sub leftover-message counts.

---

## 7. Credentials / .env  (`code/.env`, git-ignored, NOT in ZIP)
```
ADZUNA_APP_ID=<set, 8 chars>
ADZUNA_APP_KEY=<set, 32 chars>
ANTHROPIC_API_KEY=            # left blank on purpose -> resume/cover use free template backend
```
- Adzuna works (verified: pulled real current US postings). Snapshot already has ~2,344 live Adzuna rows baked in.
- For Cloud Run: put these in **Secret Manager / env vars**, never in the image.

---

## 8. WHAT'S LEFT (the to-do list)
### A. Switch Dockerfile to uvicorn (the Dockerfile still runs Streamlit)
`Dockerfile` (at JobPilot root) currently `CMD streamlit run app.py ...`. Change to run FastAPI:
- `pip install` already covers fastapi/uvicorn via requirements.txt (confirm they're added — ADD if missing:
  `fastapi`, `uvicorn[standard]`, `python-multipart`).
- Copy `web/` and `server.py` into the image (currently copies `app.py` + `jobpilot/`).
- `CMD exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}` (Cloud Run sets $PORT).
- Keep the build-time embedding RUN step.

### B. GCP setup + Cloud Run deploy (user must auth)
`gcloud` SDK 571 is installed (`/opt/homebrew/bin/gcloud`) but **NOT authenticated** (no account/project yet).
User runs:
```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable pubsub.googleapis.com run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud pubsub topics create jobpilot-postings
# deploy (build context = JobPilot/ root so it sees code/ + data/):
gcloud run deploy jobpilot --source . --region us-central1 --memory 2Gi --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,PUBSUB_TOPIC=jobpilot-postings
```
- Grant the Cloud Run **service account** roles `roles/pubsub.publisher` + `roles/pubsub.subscriber` so the
  in-app "Run Pub/Sub demo" works live on the hosted URL.
- Cost: well within the user's **$50 GCP credit** (Cloud Run scale-to-zero ~$0; Pub/Sub free tier).

### C. brief.pdf (≤4 pages) — REQUIRED deliverable
Must cover: architecture diagram, the BAX-423 technique choices **with benchmarks**, pipeline design,
**persona pass/fail table**, limitations. Benchmarks to cite (all measured this session):
- Bloom dedup: **61 KB** for 52,400 records, **83 false positives (0.16%)**, 0 remaining duplicate job_ids.
- Streaming throughput: ~**277k rec/s** in-process; ~**1,400 rec/s** through a real broker.
- Sampling: 50k drawn from 47 GB in ~**70s** (byte-offset).
- Embedding vs keyword **A/B**: P@10 **1.00 vs 0.90 (+11%)**, NDCG +0.046, embeddings **win/tie 5/5 personas**.
- Count-Min Sketch: **0–7.4%** error vs exact.
- Adaptive learning: acceptance **0.84→0.99 (+18%/rounds, +88% vs random)**; weights converge to true prefs.
- Personas: **all 5 PASS** (P@10 0.43–1.0).
- Techniques mapped to lectures: L2 (Bloom/CMS/sampling), L3 (streaming/Pub/Sub), L5 (embeddings),
  L7 (multi-stage ranking), L8 (RL rewards + ε-greedy).
- Use the architecture diagram in §3 (or render a PNG). Tools: there's an `anthropic-skills:docx`/`pdf` skill.

### D. README (REQUIRED) — exact setup + run commands
Local run (uvicorn), what's in data/, how to rebuild, env vars, dependencies. Note "code must run or 0 on
dims 1–4."

### E. Final ZIP: `LastName_FirstName_BAX423_Final.zip`
- (Confirm Gayathri's last name with the user.)
- Contents: `code/` (with requirements.txt, runs with one command), `data/` (the 50,302-row CSV sample;
  **also include `artifacts/*.npy`** so graders running locally don't wait ~9 min to embed),
  `brief.pdf`, `prompts.md`. **Exclude** the 47 GB dump and `.env`.
- The CSV is 155 MB → ZIP ~30–40 MB. Fine. (If size matters, can gzip or trim to ~30k, but 50k is allowed.)

---

## 9. Rubric status (100 pts, 5 dimensions)
1. **Data Pipeline (15):** streaming (Pub/Sub + in-process) ✅, Bloom dedup correct (0 dups, benchmarked) ✅,
   50,302 records (≥500) ✅ → full credit. (Note: snapshot is pipeline OUTPUT; spec allows offline gathering.)
2. **Matching & Ranking (20):** embeddings retrieval ✅, multi-stage ranking ✅, P@10/NDCG reported ✅,
   embedding-vs-keyword A/B proves it beats keyword ✅.
3. **Adaptive Learning & Techniques (15):** RL rewards+ε-greedy with visible improvement (+18%/+88%) ✅,
   6 techniques benchmarked across L2/L3/L5/L7/L8 ✅.
4. **Hosting & Deployment (20):** UI clean (matches mockup) ✅, explain feature ✅, **hosting = TODO (deploy to Cloud Run)**.
5. **Brief & Demo (30):** brief.pdf TODO; prompts.md ✅; demo = the live 1:1.

---

## 10. Servers currently running (may be stale by next session)
- A uvicorn/preview server was on **:8000**. Old Streamlit instances may linger on :8501.
- To clean up: `lsof -ti:8000 | xargs kill; lsof -ti:8501 | xargs kill`, then restart uvicorn (§2).

## 11. Suggested next action for the new session
1. Confirm the user is happy with the FastAPI UI (open :8000, click through Matches/Analytics/Feedback/About).
2. Update the Dockerfile to uvicorn (§8A).
3. Walk the user through GCP auth + `gcloud run deploy` (§8B).
4. Write README + brief.pdf (§8C/D) and assemble the ZIP (§8E).
