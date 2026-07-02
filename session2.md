# JobPilot — Session 2 Handoff (continue in a new Claude session)

> Paste this whole file into the new session (or open from the project root). It captures the
> full state after Session 2 so you can continue without re-discovering anything. Read §0 first.
> The original build notes are in `SESSION_HANDOFF.md` (Session 1); this supersedes it.

---

## 0. TL;DR — where we are
- **Project:** JobPilot (Option B) — BAX-423 Big Data, Spring 2026 final. UC Davis MSBA, **Gayathri Valsalakumari**, instructor Dr. Rahul Makhijani.
- A job matcher + résumé/cover builder: ingests ~50k postings + live Adzuna, embeds + ranks to a profile, learns from feedback, generates a **template-matching résumé + cover letter** (Word + PDF), analytics dashboard.
- **FULLY DEPLOYED & LIVE on Cloud Run:** **https://jobpilot-230916539522.us-central1.run.app**
  (project `smiling-duality-498421-j5`, region `us-central1`, revision **`jobpilot-00005-fx4`**, `min-instances=1` = always warm).
- **App = FastAPI (`code/server.py`) + custom HTML/JS frontend (`code/web/`).** Old Streamlit `code/app.py` is superseded/unused.
- **Deadline:** due **Fri Jun 5, 2026 11:59pm PT**; live 1:1 demo **Sat Jun 6**. Today ≈ Jun 5.
- **All 5 personas PASS.** All 6 core capabilities + bonuses built.
- **What's LEFT:** (1) regenerate the final submission **ZIP** with the latest code; (2) optional soft items (Aisha "all-ML" ranking, generation latency); (3) after grading: set `min-instances 0` + rotate the Anthropic key. See §7.

---

## 1. Live deployment facts
- **URL:** https://jobpilot-230916539522.us-central1.run.app  (also resolves at `jobpilot-cqdr22citq-uc.a.run.app`)
- **GCP project:** `smiling-duality-498421-j5` (account `gvals@ucdavis.edu`, billing enabled). **NOT** `biomebar-data`.
- **Region:** `us-central1` · **Service:** `jobpilot` · **Revision:** `jobpilot-00005-fx4` · **min-instances=1**.
- **Pub/Sub topic:** `jobpilot-postings` (real GCP Pub/Sub works live for the streaming demo).
- **Env vars set on the service (plain env vars, NOT Secret Manager — user's choice):**
  `GOOGLE_CLOUD_PROJECT`, `PUBSUB_TOPIC=jobpilot-postings`, `ANTHROPIC_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`.
- **Two separate billing meters:** GCP (Cloud Run/build/PubSub — on the $50 GCP credit; `min-instances=1` ≈ $2–5/day) vs **Anthropic** (Haiku résumé/cover calls — pennies). They are unrelated.

---

## 2. Paths
- **Project root:** `/Users/Gayathri/Desktop/Spring Quarter/Big Data/Final Assignment/JobPilot/`
- **Assignment dir (one level up):** `/Users/Gayathri/Desktop/Spring Quarter/Big Data/Final Assignment/`
  - `BAX423_FinalProject_JobPilot_Spring2026.docx` — **the spec + rubric + personas** (read via python-docx).
  - `Lectures/` — lecture notes (Lecture 1–10). Lecture topics verified (see §6).
  - `BAX423_Final_OnePager.pdf`
- `code/` — `server.py` (PRIMARY), `app.py` (old Streamlit, unused), `build_index.py`, `requirements.txt`,
  `.env` (Adzuna + Anthropic keys; git-ignored, NOT in ZIP), `jobpilot/` package, `web/` frontend.
- `data/` — `jobs_snapshot.csv` (50,302 rows, 155MB), `artifacts/job_embeddings.npy` (74MB) + `job_ids.npy`,
  `techmap-jobs-dump-2021-09.json` (47GB raw dump — NOT in ZIP/image).
- `brief/brief.html` + `brief.pdf` (3 pp), `prompts/prompts.md`, `README.md`, `Dockerfile`, `.gcloudignore`, `.dockerignore`.
- `mockups/` — `adzuna-feature-mockup.html`, `analytics-mockup.html` (+ PNGs) — design mockups (approved).
- **User's real templates (the format the generator now matches):**
  `/Users/Gayathri/Desktop/Job Hunt 2026/Resume/Finance/Gayathri_Finance_Resume.pdf`
  `/Users/Gayathri/Desktop/Job Hunt 2026/Coverletter/Coverletter_GayathriValsalakumari.pdf`

---

## 3. What Session 2 did (on top of Session 1's core build)
1. **Deploy-ready Docker + GCP deploy.** Dockerfile → `uvicorn` (FastAPI); copies `web/` + `server.py`; **CPU-only torch**
   (`--index-url .../whl/cpu`) + **ships prebuilt embeddings** (`COPY data/artifacts`) instead of regenerating → build ~5 min.
   `.gcloudignore` created (gcloud uses it, NOT `.dockerignore`) to keep the 47GB dump out of the upload.
2. **README + brief.pdf** (architecture, benchmarks, persona table, limitations; 3 pages).
3. **Claude API for résumé/cover — HAIKU ONLY.** `claude-haiku-4-5`, **never Opus/Sonnet** (hard user rule, saved to memory
   `feedback_jobpilot_haiku_only.md`). Key in `code/.env`; `config.py` uses `load_dotenv(override=True)` (an empty shell
   `ANTHROPIC_API_KEY` was shadowing the file).
4. **Adzuna live fetch.** Fetched **by default at startup** + an **`↻ Adzuna` refresh button** that pages DEEPER each click
   (`_adz_cursor` in `server.py`, `start_page` in `live_sources.py`). Normalizes → enriches → embeds → Bloom-dedups →
   appends to the **in-memory** corpus/index (ephemeral per Cloud Run instance; `min-instances=1` keeps one warm).
5. **Analytics → Plotly.js 2×2 grid** (orange theme `#e8612c`): top skills (bar), salary distribution (histogram),
   demand by location (bar), data source mix (pie). Data already came from `/api/analytics`.
6. **Rubric-3 fix.** Added a learnable **`company_size`** signal (`ranking.py` DEFAULT_WEIGHTS + `score_job`;
   `learning.py` FEATURES). Rejecting small companies now raises the company-size weight → large companies rise (Kenji).
   Added a live **"Run learning benchmark"** view (Feedback tab, `/api/learning-curve`) showing acceptance climbing vs a
   flat random baseline = "visible improvement."
7. **Template-matching résumé + cover generation (BOTH .docx and PDF).** `generate.py` fully rewritten:
   Haiku tailors the candidate's **own resume text + the job** into **structured JSON** (summary, experience entries with
   title|company + location·dates, projects, publications, grouped skills, education); rendered to **.docx (python-docx)**
   AND **PDF (fpdf2 — pure-Python, Cloud-Run friendly, no Chrome)** styled to match the user's navy/clean résumé + serif
   (Times) cover letter. Deterministic fallback if no API key. UI shows **⬇ Word** and **⬇ PDF** buttons.
8. **Persona pointer fixes** (the 8 the user reported — see §5).
9. **Enriched Gayathri persona** with her full real résumé text (so the demo produces a rich résumé).
10. **no-cache middleware** in `server.py` (HTML/JS/CSS) so browsers pick up new deploys; **deep-link tabs** (`?tab=analytics`).

---

## 4. Architecture (current)
```
OFFLINE (build_index.py, already done -> ships the snapshot):
  47GB dump --byte-offset sample(L2)--> normalize -> 12-field schema -> stream+Bloom dedup(L2/L3)
  -> features.enrich -> embed MiniLM 384-d(L5) -> data/jobs_snapshot.csv (50,302) + artifacts/*.npy

RUNTIME (server.py FastAPI + web/):
  startup: load snapshot -> features.enrich(DF) [RE-ENRICH so latest inference applies to whole corpus]
           -> load cached embeddings -> ANNIndex -> ingest_adzuna() [live fetch by default]
  REST API: /api/options /api/match /api/feedback /api/generate /api/export /api/upload-resume
            /api/analytics /api/pubsub-demo /api/fetch-adzuna /api/learning-curve
  Matching: profile -> MiniLM embed -> sklearn cosine kNN (1000) -> hard filters -> weighted score
            (similarity .45, skills .25, title .15, salary .10, seniority .05, company_size .00*learned)
            -> top-25.  Adaptive learner adjusts the 6 weights from accept/reject/skip (ε-greedy).
```

---

## 5. The 8 pointer fixes (Session 2, all deployed in rev 00005)
| # | Issue | Fix | State |
|---|-------|-----|-------|
| 1 | Matches slow ("Ranking 50k…") | `--min-instances=1` (warm); spinner text → "Ranking matches…" | ✅ |
| 2 | Aisha: top-10 not all ML; résumé should lead Python/ML | Résumé tailoring leads with ML (Claude hint toward target roles). Ranking "all-ML" is **soft** — still partial | 🟡 partial |
| 3 | Marcus: 8+/7-10yr roles in top-10 | `max_seniority="mid"` for Marcus + `features.enrich` **implies years from seniority** (senior→5, staff→8) + re-enrich corpus | ✅ (top-10 max-years now 0) |
| 4 | Marcus: lead with MSBA education | `education_first` profile flag → résumé renders Education before Experience | ✅ |
| 5 | Generate résumé slow | Inherent Haiku latency (~5s); spinner says "Generating with Claude…" | 🟡 inherent |
| 6 | Priya: >100-employee only | `features.LARGE_COMPANIES` known-employer list → 8,566 jobs "large"; Priya top-10 has ~6 large | ✅ improved (unknown-size firms can still pass) |
| 7 | Kenji: lead with publications | `publications` profile field + a Publications section that leads the résumé | ✅ |
| 8 | Kenji: rejecting companies not learning | Root cause = company_size mostly "unknown" (no signal). Fixed via known-large list **+** a **"Large co."/"Small co." badge** on cards so you can see which to reject | ✅ |

**How to test personas (demo):** open the URL → "Quick-load a test persona" → pick persona → **Find matches** → check top-10
against criteria (Aisha: 0 senior/staff, 0 defense; Marcus: 0 roles ≥3yr, 0 contract; Priya: 0 junior, 0 tiny startups;
Kenji: 0 contract, favors large; Gayathri: 0 roles ≥4yr, 0 contract). For Kenji's learning: reject **Small co.**-badged
jobs and watch large rise; or Feedback tab → **Run learning benchmark**.
**Automated check (offline, ~20s):**
```python
from jobpilot import store, ranking, features
from jobpilot.personas import PERSONAS
df = features.enrich(store.load_corpus()); _, idx = store.load_index(df)
for n,p in PERSONAS.items():
    r = ranking.rank_for_profile(df, idx, p.profile, top_k=25)
    print(n, p.pass_criteria(r.ranked.head(10)))
```
(User declined saving this as `test_personas.py` — offer again if useful.)

---

## 6. Rubric (from the .docx) + lecture mapping (verified)
5 dimensions (100 pts): 1 Data Pipeline (15) · 2 Matching & Ranking (20) · **3 Adaptive Learning & Course Techniques (15)**
· 4 Hosting & Deployment (20) · 5 Brief & Demo (30). "Code that doesn't run = 0 on dims 1–4."
**Dim 3 full credit:** "Learning implemented with visible improvement. **2 BAX-423 techniques integrated and benchmarked.**"
Lecture topics (verified against `Lectures/`): **L2** Bloom/Count-Min/HyperLogLog/sampling · **L3** Kafka & Streaming ·
**L4** PySpark · **L5** Embeddings & Vector Semantics · **L6** Recommendation Systems/DCN · **L7** Ranking & Multi-Stage ·
**L8** Intro RL (Q-learning, ε-greedy) · **L9** Deep RL/DQN · **L10** Prototype→Production. Our claims (L2/L3/L5/L7/L8) are correct.
5 personas required (Aisha, Marcus, Priya, Kenji, Gayathri) — all implemented with machine-checkable `pass_criteria`.

---

## 7. WHAT'S LEFT / open items
1. **Regenerate the submission ZIP** (the old `/tmp` one is stale). Name: **`Valsalakumari_Gayathri_BAX423_Final.zip`**
   (confirm last name). Contents: `code/` (with requirements.txt, runs with one command), `data/jobs_snapshot.csv` +
   `data/artifacts/*.npy`, `brief/brief.pdf`, `prompts/prompts.md`, `README.md`, `Dockerfile`, `.gcloudignore`.
   **Exclude:** the 47GB dump, `code/.env`, `__pycache__`, `.DS_Store`, `session*.md`/`SESSION_HANDOFF.md` (internal).
   Likely ~120 MB (CSV 155MB + npy 75MB compress to that). If a portal caps at 100MB, drop the `.npy` (graders regenerate).
2. **Soft items not done:** #2 Aisha "all-ML in top-10" (only résumé side done — could add a title/role relevance gate or
   boost title weight for ML personas); #5 generation latency (inherent; could reduce `max_tokens` or stream).
3. **Other personas' résumés are thin** — only Gayathri's persona has full `resume_text`. Real users **upload** their resume
   (`/api/upload-resume` → `resume_text`) → Claude tailors richly. Fine as-is.
4. **brief.pdf** could be refreshed to mention template résumé gen + Adzuna-by-default (mostly covered; minor).
5. **After grading:** `gcloud run services update jobpilot --region us-central1 --min-instances 0` (stop continuous billing);
   **rotate the Anthropic key** (it was pasted in chat) at console.anthropic.com → update `code/.env` + the Cloud Run env var.

---

## 8. Files changed in Session 2 (all under `code/`)
- `jobpilot/generate.py` — **fully rewritten**: `build_resume_data` (Claude JSON tailoring + fallback), `_llm_resume_json`,
  `build_cover_data`/`_llm_cover_paragraphs`, docx renderers, **fpdf2** PDF renderers (`_latin1` sanitizes unicode for core
  fonts), `resume_plaintext`, section ordering (publications-first / education-first), `generate_resume`/`generate_cover_letter`
  now return dicts `{docx, pdf, text, ats, backend}`.
- `jobpilot/ranking.py` — `company_size` in `DEFAULT_WEIGHTS` (0.0, learned) + `_company_size_score` + in `score_job` breakdown.
- `jobpilot/learning.py` — `company_size` added to `FEATURES`; `__init__` setdefaults missing weights; `from_state` guards
  baseline length; `simulate_learning`/`_candidate_features`/`embeddings_lookup` take optional `vecs=` (use live in-memory matrix).
- `jobpilot/features.py` — `LARGE_COMPANIES` set; `enrich` infers years from seniority; company_size uses known-large list.
- `jobpilot/embeddings.py` — `embed_jobs(df)` (embed without caching, for live Adzuna append).
- `jobpilot/personas.py` — Marcus (`max_seniority="mid"`, `education_first=True`), Kenji (`publications=[...]`),
  Gayathri (full `resume_text`, real name, contact).
- `jobpilot/profile.py` — added `projects`, `publications`, `education_first`; `education`/`experience` may be dicts.
- `jobpilot/live_sources.py` — `start_page` param on `fetch_adzuna`/`fetch_live`.
- `server.py` — re-enrich corpus at startup; `ingest_adzuna()` + startup fetch + `_adz_cursor`; `/api/fetch-adzuna`,
  `/api/learning-curve`; `gen_doc` returns docx+pdf; **no-cache middleware**; `company_size`/`seniority` in `job_to_dict`;
  persona payload + `profile_from_payload` carry `publications`/`education_first`/`projects`.
- `web/index.html` — Plotly CDN; "Live data source" card; `.leftcol` wrapper.
- `web/app.js` — Plotly analytics; Adzuna refresh; learning benchmark; company-size badge; **Word+PDF** download buttons;
  deep-link tabs; spinner text.
- `web/style.css` — live card, analytics grid, company-size badge styles.
- `requirements.txt` — added `fastapi`, `uvicorn[standard]`, `python-multipart`, `python-docx`, `anthropic>=0.49`, `fpdf2>=2.7`.
- root: `Dockerfile` (uvicorn + CPU torch + shipped embeddings), `.gcloudignore`, `README.md`, `brief/brief.html`+`brief.pdf`.

---

## 9. How to run / deploy
**Local** (loads 50k + re-enrich + Adzuna fetch + MiniLM, ~30s):
```bash
cd "/Users/Gayathri/Desktop/Spring Quarter/Big Data/Final Assignment/JobPilot/code"
uvicorn server:app --port 8000      # http://localhost:8000   (.env supplies Adzuna+Anthropic keys)
```
**Deploy** (run from project root; reads keys from code/.env so they're not in shell history):
```bash
cd "/Users/Gayathri/Desktop/Spring Quarter/Big Data/Final Assignment/JobPilot"
PROJ=smiling-duality-498421-j5
AK=$(grep '^ANTHROPIC_API_KEY=' code/.env | cut -d= -f2-)
AID=$(grep '^ADZUNA_APP_ID=' code/.env | cut -d= -f2-)
AKEY=$(grep '^ADZUNA_APP_KEY=' code/.env | cut -d= -f2-)
gcloud run deploy jobpilot --source . --project $PROJ --region us-central1 \
  --memory 2Gi --cpu 2 --timeout 900 --min-instances 1 --allow-unauthenticated \
  --set-env-vars "^@^GOOGLE_CLOUD_PROJECT=$PROJ@PUBSUB_TOPIC=jobpilot-postings@ANTHROPIC_API_KEY=$AK@ADZUNA_APP_ID=$AID@ADZUNA_APP_KEY=$AKEY"
```

---

## 10. Key decisions & gotchas (DON'T re-litigate)
- **Haiku only** for all Claude calls (`claude-haiku-4-5`). Never Opus/Sonnet. (Saved to memory.)
- **gcloud project drifts** — once it became `job-pilot` (a project the account can't access). **Always pass `--project smiling-duality-498421-j5`.**
- **gcloud upload uses `.gcloudignore`** (not `.dockerignore`). The 47GB dump MUST be excluded there.
- **Embeddings shipped prebuilt** + **CPU-only torch** in the Docker image → ~5-min builds. Don't regenerate embeddings at build.
- **Adzuna refresh is in-memory & ephemeral** on Cloud Run (per-instance; resets on cold start). Intentional for the demo.
- **company_size / years_required are heuristic** (text + known-large list); corpus is **re-enriched at startup** so the
  whole 50k uses the latest logic (not just live rows).
- **PDF generation = fpdf2** (no Chrome on Cloud Run). `_latin1()` maps unicode (—, •, ✓) to latin-1-safe for core fonts;
  skills use markdown bold in `multi_cell`.
- **Browser cache** — `no-cache` middleware is deployed; if old UI appears, hard-refresh (⌘+Shift+R) or incognito.
- **Preview MCP can't access the "Spring Quarter" path** (sandbox). Verify via Chrome headless screenshots or the running server.
- **FAISS removed** (segfaults with PyTorch) — sklearn cosine kNN. **protobuf pinned `>=4.25,<7`**.
- **Snapshot is the pipeline OUTPUT** (spec allows offline gathering). Don't treat it as a static-file shortcut.

---

## 11. Suggested next actions for the new session
1. Confirm last name → **regenerate the final ZIP** (§7.1) and place it in the assignment dir.
2. (Optional) Tighten Aisha "all-ML" ranking (#2) and/or reduce generation latency (#5).
3. Final pre-demo check: open the live URL, click each persona, generate a résumé (Word+PDF), run the Pub/Sub + learning
   benchmark demos. Pre-warm is unneeded (min-instances=1).
4. After grading: `min-instances 0` + rotate the Anthropic key.
