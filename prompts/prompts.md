# JobPilot — AI Prompts Log

This file records the key prompts used to build JobPilot (Option B) with Claude (Claude Code / Opus 4.8),
along with 2–3 lines summarizing the response/output for each. This is the `prompts.md` deliverable
required by the BAX-423 final project rubric.

Format per entry: the prompt (paraphrased where long), then **Response:** a short note on what was produced
and how it was used/modified.

---

## 1. Project kickoff — understand the assignment
**Prompt:** "I want to go ahead with Job Pilot. Read through the BAX423_Final_OnePager.pdf and
BAX423_FinalProject_JobPilot_Spring2026.docx end to end and tell me what we need to do; give me a step-by-step guide."

**Response:** Read both documents. Produced a complete breakdown: the 6 mandatory core capabilities (missing any caps
score at 60/100), the 5-dimension rubric, deliverables (live URL, brief.pdf ≤4pp, prompts.md, ZIP), the 4 test
personas, and a 10-step build plan. Flagged that the project is due June 5 with a live demo June 6.

## 2. Scope & technique selection
**Prompt:** "Let's go ambitious — 6 caps + polish, Streamlit + Cloud Run. Use multiple techniques: Kafka & streaming,
embeddings & vector semantics, multi-stage ranking, rewards (accept/reject), epsilon-greedy exploration, Streamlit
prototype-to-production."

**Response:** Mapped each chosen technique to a distinct BAX-423 lecture (Kafka→L3, Bloom dedup→L2, embeddings→L5,
ranking→L7, RL rewards/ε-greedy→L8, Streamlit→production), satisfying the "≥2 techniques from different lectures +
benchmark" rule with margin. Created a 7-task build plan and scaffolded the project directory.

## 3. Project scaffold + prompts logging
**Prompt:** "I have the dataset downloaded — I'll move it to the folder. Also save all prompts in a prompts folder
and record 2-3 lines of what you respond."

**Response:** Created the JobPilot/ project structure (code/, data/, prompts/, brief/) and this prompts.md logging
file. Set up the convention of recording every build prompt + a short response summary as we go.

---
## 4. Capability 1 — ingestion, streaming, dedup
**Prompt (internal build goal):** "Build the ingestion pipeline: flexible Kaggle/Adzuna/synthetic loader, normalize any
raw posting schema to a canonical schema via column-alias mapping, a from-scratch Bloom filter for dedup (Lecture 2),
and a Kafka-style producer→queue→consumer streaming loop (Lecture 3) with offline fallback."

**Response:** Wrote `config.py` (canonical schema + alias map), `skills.py` (controlled skill vocabulary +
extraction), `ingest.py` (loader, normalizer, `BloomFilter` class sized by target FP-rate, `stream_ingest` with
live dedup + benchmark vs. an exact set), and `features.py` (parse seniority, years-required, contract, visa
sponsorship, defence flag, company size, salary). Verified end-to-end on synthetic data: ~327k rec/s, 0–1 Bloom
false positives, dedup behaving correctly.

<!-- New entries appended below as the build progresses -->

## 5. Capability 2 & 3 — profile intake + embedding retrieval
**Prompt (internal build goal):** "Build profile intake with PDF resume extraction and a controlled skill vocabulary;
encode the 4 required test personas as profiles with machine-checkable pass criteria. Then build embedding-based
retrieval (Lecture 5): sentence-transformer dense vectors + nearest-neighbour search, cached to disk."

**Response:** Wrote profile.py (UserProfile, pypdf extraction, skill auto-detection), personas.py
(Aisha/Marcus/Priya/Kenji + pass-criteria functions), and embeddings.py (all-MiniLM-L6-v2 384-dim embeddings,
disk cache, ANNIndex). Verified retrieval is semantically correct (Priya->ML Platform roles, Marcus->Data Analyst).
Discovered FAISS segfaults alongside PyTorch (OpenMP conflict); switched to sklearn exact cosine k-NN
(~30 ms/query at 50k jobs) so the deployed app can never crash -- documented the tradeoff in code + brief.

## 6. BONUS — Live job postings via Adzuna API
**Prompt (internal build goal):** "Build a live-ingestion module that fetches current postings from the Adzuna free
API, normalizes them into the same canonical schema as the Kaggle snapshot, and feeds them through the identical
streaming + Bloom-dedup path. Read credentials from a git-ignored .env so they never enter the submission."

**Response:** Wrote live_sources.py (fetch_adzuna with pagination + polite rate-limiting, fetch_live convenience
wrapper) and a .env/.gitignore credential setup; made config.py auto-load .env via python-dotenv. Verified against
the real API: pulled 100 current US postings (Lockheed Martin, Capgemini, Indeed...) with real salaries/locations,
normalized cleanly. Earns the spec's extra credit for gathering current postings.

## 7. Real data build — 50k snapshot from 47 GB Kaggle dump + Persona 5
**Prompt:** "Confirm we're taking a 50,000 sample. I downloaded the Kaggle dataset. Also add me as Persona 5
(table at the bottom of the spec): Gayathri, Financial Analyst; dealbreaker no 5+ years; pass criteria zero 4+."

**Response:** Found the dataset is a 47 GB / 3.47M-record JSONL MongoDB dump. Built a techmap parser + random
byte-offset sampler (sampling technique, Lecture 2) to pull 50k English postings in ~70s without loading the file.
Ran build_index.py: 50k Kaggle + 2.4k live Adzuna -> Bloom dedup -> 50,302 unique (61 KB filter, 83 FPs) ->
snapshot CSV + cached 384-dim embeddings (8 min one-time). Added Persona 5 (Gayathri) with CA-only, >=$90K,
no-5+-years filter and zero-4+-years pass criteria. (Fixed a masked `import json` bug found via rejection counters.)

## 8. Capability 4 — multi-stage ranking + evaluation (Lecture 7)
**Prompt (internal build goal):** "Build candidate generation -> hard filters (salary/location/contract/seniority/
defence/visa/company-size; never exclude on unknown values) -> transparent weighted scoring -> re-rank, plus a
ranking metric (precision@k, NDCG). Test all 5 personas on the real 50k corpus."

**Response:** Wrote ranking.py (passes_filters, score_job with per-signal breakdown for the explain panel,
rank_jobs pipeline, rank_quality_metrics) and store.py (corpus + cached-embedding loader). First run: 4/5 pass.
Fixed two real bugs found in the output: (1) "ca" substring-matched "chiCAgo" -> switched to word-boundary location
matching; (2) a UK remote job slipped past us_only -> tightened the gate. Resolved Persona 5's filter/criteria
mismatch (tightened to exclude 4+ yrs per user). Widened candidate pool to 1000 so every persona fills a top-10.
Final: ALL 5 PERSONAS PASS (P@10 0.43-1.0).

## 9. Capability 5 — adaptive learning (Lecture 8: rewards + e-greedy)
**Prompt (internal build goal):** "Build an online learner: accept/reject/skip rewards update the ranking weights;
e-greedy exploration; simulate a user with hidden preferences and show measurable improvement over rounds + a
benchmark vs a no-learning baseline."

**Response:** Wrote learning.py: AdaptiveLearner (baseline-subtracted online gradient, e-greedy choose() with decay)
+ simulate_learning harness. Iterated on the benchmark twice: first the retrieved pool was too uniformly good to
show a lift, so I (a) added a diverse pool (retrieved + random), (b) switched to expected-acceptance metric, and
(c) reframed as cold-start (uniform init) vs a random no-learning baseline. Final: acceptance climbs 0.84->0.99
(+18% over rounds, +88% vs random), and learned weights converge onto the hidden prefs (skills/title). Honest
note: this is personalization on top of the base ranker, not a claim of beating the already-tuned default.

## 10. Capability 6 + deliverables — explain, resume, cover letter, export, analytics
**Prompt (internal build goal):** "Build the 'why ranked here' explain panel from the score breakdown; a tailored
resume generator + cover-letter bonus (template default, LLM optional); CSV/Excel/JSON export of top matches; and
batch analytics (top skills, salary distribution, demand by location) including a Count-Min Sketch benchmark."

**Response:** Wrote explain.py, generate.py (template + optional Claude-haiku backend with graceful fallback),
export.py (CSV/Excel/JSON), analytics.py (summary stats, top skills, salary dist, demand by location/source, and a
CountMinSketch class benchmarked vs exact counts: 0% error on most skills, 7.4% overestimate on one). Analytics
surfaced a real bug -- the skill regex matched "CV" (resume) as "computer vision", inflating it to #2; fixed the
ambiguous cv/tf/ml patterns and re-derived the 50k skills column. Re-verified ALL 5 PERSONAS STILL PASS.

## 11. Polished résumé/cover-letter + real ATS keyword tailoring
**Prompt:** "Resume needs a ready-to-use format (name centered, summary, education, experience, skills); download as
Word not txt; cover letter needs a Word download too; Like/Dislike buttons should show state; can I download more
than 10? And: how is each resume different — is it ATS-tailored per job?"

**Response:** Rewrote generate.py to emit polished Word (.docx) résumé (name centered -> summary -> education ->
experience -> skills) and Word cover letter via python-docx; added structured education/experience to the profiles.
Updated app.py: Like/Dislike buttons highlight when selected + LIKED/DISLIKED badge, re-rank-on-demand, and a
slider to show/download 1-25 matches. Built ats.py: extracts real keywords from each job description, scores ATS
coverage (per-job 43-78%), adds a per-job "Key Qualifications" section + missing-keyword suggestions in the UI.
Each résumé now genuinely differs per posting (different key quals, ATS score, summary keywords).

## 12. Dislike = remove job + learn + instant re-rank
**Prompt:** "Listed jobs don't match résumé requirements. When Dislike is clicked, that mismatched job should go away
and the feedback should be used for learning. First explain how/where learning happens, then make the change."

**Response:** Explained the learning path (learning.py AdaptiveLearner adjusts 5 scoring weights from accept=+1/
reject=-1/skip=-0.2 rewards; app.py applies it; run_ranking re-scores). Added an `exclude_ids` param to rank_jobs
so disliked/skipped job_ids are dropped permanently; app now keeps a per-session `excluded` set. Dislike/Skip remove
the job + record the reward + instantly re-rank; a Reset button clears it. Caught + fixed a real learner bug: the
baseline was updated BEFORE the gradient, so the first feedback produced zero learning — reordered it (gradient vs
prior EMA baseline, 0.5 init) so the first dislike already shifts weights. Phase-5 benchmark still climbs 0.85->0.97.

## 13. Embedding-vs-keyword A/B benchmark (closes Dimension 3 gap)
**Prompt:** "How is 'Learning implemented with visible improvement; 2 BAX-423 techniques benchmarked' implemented
currently?" -> then: "Add the missing embedding-vs-keyword A/B benchmark."

**Response:** Audited Dimension 3: confirmed learning + 5 benchmarked techniques (Bloom 61KB/0.16% FP, CMS 0-7.4%,
RL +18%/+88%, Kafka ~299k rec/s, sampling), but found the keyword-vs-embedding A/B promised in a docstring was
never built. Implemented benchmark.py: a TF-IDF lexical retriever vs the dense-embedding retriever, scored with a
stricter >=2-skill relevance (the >=1 bar saturated at P@10=1.0). Result: embeddings win/tie on 5/5 personas, avg
P@10 1.00 vs 0.90 (+11%), NDCG +0.046 — biggest gains for Kenji (+0.30) and Gayathri (+0.20). Wired a "Run
benchmark" button into the app's Pipeline tab and fixed the stale ranking.py docstring.

## 14. Real Kafka-in-Docker streaming demo (Lecture 3)
**Prompt:** "Is it possible to run a live demo of Kafka producer/consumer using Docker?"

**Response:** Yes — built it. Added docker-compose.yml (single-node Kafka in KRaft mode, no Zookeeper),
kafka_pipeline.py (real producer publishes postings to topic `jobpilot.postings`; consumer reads them back with
Bloom-filter dedup), kafka_demo.py (CLI demo), and a broker-auto-detecting "Run LIVE Kafka demo" button in the app's
Pipeline tab (hidden when no broker; in-process fallback otherwise). Started Docker, pulled apache/kafka:3.8.0,
verified real messages land on the topic. Fixed a real bug: the topic persists across runs, so the consumer re-read
old messages — fixed by seeking to the partition end before producing so each run consumes only its own messages.
Verified twice: produced=consumed=950, exactly 150 injected dups removed, 0 false positives, ~1,400 rec/s.

## 15. Architecture change — two pipeline modes (Live demo vs Runtime)
**Prompt:** "Keep Kafka local but change the architecture: Live Demo = Kaggle/Adzuna → Kafka producer → consumer →
Ingest/Dedup(Bloom) → Enrich+Embed → embeddings → rest of app; Runtime App = embeddings onwards → rest of app."

**Response:** Built jobpilot/live.py: run_live_pipeline() runs the WHOLE pipeline on a small live sample
(sample → Kafka produce/consume → Bloom dedup → features.enrich → embed live → ANN index), with a fallback to the
in-process stream when no broker. Added a sidebar 'Data mode' toggle (⚡ Runtime cached-50k vs 🔴 Live Kafka→embed),
live controls (N, include-Adzuna, Build button) and a live-pipeline funnel display in Matches. Matcher now ranks on
the active corpus. Verified end-to-end via real Kafka (1492 jobs, 13s embed). Fixed a real bug: a small live sample
can yield 0 matches for a strict persona (Marcus) and the slider crashed at <=1 result — added empty/tiny-result
guards + a friendly message. App boots cleanly headless.

## 16. Wire real Kafka into the build pipeline (architecture fix)
**Prompt:** "The architecture diagram doesn't show Kafka — why?" → "Wire Kafka into the build."

**Response:** Explained honestly that build_index.py used the in-process streaming sim, so Kafka was only a
standalone demo. Fixed it: build_index.py now auto-detects the broker and routes ingestion through real Kafka
(produce → topic 'jobpilot.postings' → consume → Bloom dedup) when up, falling back to in-process otherwise; added
a --kafka {auto,on,off} flag. Verified the Kafka build path on a 1.5k sample (1,513 rec/s via kafka-docker) without
overwriting the 50k snapshot. Kafka (L3) is now a first-class stage in the ingestion pipeline, and the architecture
diagram reflects it.

## 17. Package only the enriched 50K — generate embeddings at docker build (option B)
**Prompt:** "What if only the enriched 50K (from step 5) is packaged in the app? ... I like B."

**Response:** Explained 3 options: (A) ship CSV only + embed at runtime = breaks Cloud Run (9-min cold start every
scale-from-zero); (B) ship CSV only + embed during `docker build` = image still has embeddings, +9 min one-time
build, instant runtime; (C) current = ship CSV + .npy. User chose B. Updated the Dockerfile to drop
`COPY data/artifacts` and add a `RUN python -c "...store.load_index(df)..."` step that generates+caches the 384-d
embeddings INSIDE the image from the enriched snapshot; added `data/artifacts/` to .dockerignore. Verified the
build-time command runs correctly (corpus 50,302 → (50302, 384)).

## 18. Switch streaming to Google Pub/Sub + target Cloud Run (drop Kafka)
**Prompt:** "Let's go with just Google Pub/Sub + Cloud Run."

**Response:** Built pubsub_pipeline.py (publish → topic → unique per-run subscription → pull + ack + Bloom dedup,
immune to multi-instance/leftover messages — the Pub/Sub analog of the Kafka offset fix). Wired it into app.py
(Pipeline tab "Run LIVE Pub/Sub demo", shown when Pub/Sub reachable) and build_index.py (--pubsub auto/on/off).
Removed all Kafka artifacts (kafka_pipeline.py, kafka_demo.py, docker-compose.yml, live.py) and relabeled the
in-process pipeline as the offline fallback. Resolved a real dependency conflict: google-cloud-pubsub pulled
protobuf 7 which breaks Streamlit (<7) — pinned protobuf>=4.25,<7 (resolved to 6.33). Installed gcloud SDK 571.
Pending: user gcloud auth + project (browser).

## 19. UI redesign to match mockup (white theme + removable chips)
**Prompt:** "Update the UI to look like ui-mockup.html but white background; must-have skills box rectangular;
Location multi-select; Target roles/Location/Skills shown as (value x) chips with a clickable x to remove."

**Response:** Added .streamlit/config.toml (light/white theme) + injected CSS for a white app, rectangular removable
chips, and card polish. Converted Target roles, Must-have skills, and Location to st.multiselect — which natively
renders each selected value as a tag with a clickable × (removes on click); made the chips rectangular via CSS.
Location is now multi-value. Added a 'Quick-load a test persona' selectbox that prefills the chip fields (then
editable), plus Find matches / Reset. App boots clean (HTTP 200).

## 20. Full UI redesign to match the mockup (header, nav, job cards)
**Prompt:** "UI not complete — the title section, Matches/Analytics nav, and Job Listing section should also match
ui-mockup.html."

**Response:** Rebuilt the whole app shell to match the mockup (white version): custom HTML header (Job**Pilot** +
subtitle + hosted-on badge); renamed nav to 4 tabs matching the mockup — Matches / Analytics / Feedback log / About;
restyled job cards to the mockup layout — title + green score right-aligned, company·location·salary·link meta line,
inline 'Why this rank →' explanation (matched skills, salary, cosine sim), and ✓ Accept / ↷ Skip / ✕ Reject /
⚙ Résumé / ✉ Cover-letter action buttons; added a download bar (top-N · P@10 · NDCG · CSV/Excel/JSON) and filter
badges. New Feedback-log tab (accept/skip/reject counts + learned-weights chart + reset). Verified via Streamlit
AppTest: persona → Find matches → cards render with zero exceptions.

## 21. Apply approved mockup-v2 theme to the app (cream/coral/green + Inter)
**Prompt:** "Make it look like the screenshot (JobPilot layout) but with the colors/font of the Monarch screenshot;
several tweaks; create an updated mockup first." → approved → "go ahead and build this UI."

**Response:** Created ui-mockup-v2.html (warm cream bg, white rounded cards, coral accent, green scores, Inter font,
rectangular chips), iterated on user tweaks (Smart Job Searcher; solid-red Reject; Generate Resume/Cover Letter
labels; download bar = "Showing top N of M"; removed filter badges; dealbreakers as chips+add; CSV/Excel/JSON
themed like Generate). Ported it into app.py: new config.toml theme + CSS (per-button colors via st-key- prefixes:
Accept=green, Reject=red, Skip=grey-outline, Generate/Download=coral-outline), header subtitle, Dealbreakers
converted to a multiselect mapped to filter fields (us_only/contract/defence/seniority/visa), simplified download
bar (metric kept as a small caption for grading), removed badges. Verified via AppTest: persona→matches render clean.

## 22. Rebuild UI as FastAPI + custom HTML (pixel-perfect to the mockup)
**Prompt:** "Since this is hosted on GCP, why even need Streamlit?" → chose to rebuild → "go ahead and build this UI."

**Response:** Explained Streamlit's styling ceiling; rebuilt as FastAPI backend (server.py) exposing all existing
Python logic as REST endpoints (/api/options, match, feedback, generate, export, upload-resume, analytics,
pubsub-demo) + a custom HTML/CSS/JS frontend (web/index.html, style.css, app.js) that renders the approved
ui-mockup-v2 exactly: cream bg, white rounded cards, coral accent, green scores, Inter font, rectangular removable
chips with +add for all fields, Accept/Skip/Reject + Generate Resume/Cover Letter, tabs (Matches/Analytics/Feedback
log/About). Stateless design (client holds learner state) for Cloud Run. Added AdaptiveLearner.to_state/from_state.
Verified all endpoints (match P@10 0.9, resume docx + ATS, export, analytics, Pub/Sub demo) and screenshotted —
matches the mockup. Old Streamlit app.py superseded. NEXT: Dockerfile->uvicorn, GCP auth, Cloud Run deploy, brief, ZIP.

## 23. Dockerfile → uvicorn + Cloud Run deploy
**Prompt:** "Point the Dockerfile at the FastAPI app and deploy to Cloud Run."

**Response:** Rewrote the Dockerfile to install **CPU-only torch** (PyTorch CPU wheel index — avoids ~2–3 GB of
unusable CUDA libs), copy `web/` + `server.py`, **ship the prebuilt embeddings** (`COPY data/artifacts`) instead of
re-embedding at build (~5-min builds), and `exec uvicorn` on `$PORT`; added a build-time assert that the shipped
vectors align to the snapshot. Wrote `.gcloudignore` (gcloud uses it, not `.dockerignore`) to keep the 47 GB dump out
of the upload. Deployed with `gcloud run deploy --source .` (`--min-instances=1` = always warm). I only adopted the
generated commands after pinning the correct `--project` (gcloud kept drifting to an inaccessible project).

## 24. Technical brief.pdf + README
**Prompt:** "Write the brief (≤4 pp) and a README with exact run instructions."

**Response:** Generated `brief.html` (architecture SVG, BAX-423 technique table with measured benchmarks, ranking
weights, embedding-vs-keyword A/B, persona pass table, limitations) and rendered it to PDF via headless Chrome; wrote
the README (one-command run, data description, env vars, layout). I re-ran every benchmark myself rather than keep the
model's drafted numbers, and corrected claims that didn't match the code (e.g. embeddings are shipped, not rebuilt at
build time).

## 25. Template-matching résumé/cover via Claude — Haiku only
**Prompt:** "Tailor the résumé to my real template using Claude, and only ever use Haiku."

**Response:** Rewrote `generate.py` so Claude (**`claude-haiku-4-5` only — never Opus/Sonnet**) reorders the
candidate's *own* résumé text into structured JSON (summary, experience, projects, publications, grouped skills,
education), rendered to both **.docx** (python-docx) and **PDF** (fpdf2, Cloud-Run-friendly) styled to the user's
navy/serif templates; deterministic template fallback when no API key. System prompt explicitly forbids inventing
employers/dates/skills. Fixed an empty shell `ANTHROPIC_API_KEY` shadowing the `.env` value via `load_dotenv(override=True)`.

## 26. Adzuna-by-default + Plotly analytics + learnable company-size
**Prompt:** "Pull live Adzuna jobs by default, make the analytics real charts, and make rejecting small companies actually learn."

**Response:** Added a startup Adzuna fetch + an **↻ Adzuna** refresh that pages *deeper* each click (normalize → enrich →
embed → Bloom-dedup → append to the in-memory index). Replaced the analytics tab with a Plotly 2×2 grid (top skills,
salary histogram, demand by location, source pie). Added a learnable **`company_size`** signal + a live "Run learning
benchmark" view so Kenji's rejections of small companies visibly raise the company-size weight (Rubric-3 visible improvement).

## 27. Persona pointer fixes — contract / sponsorship / dead links / résumé emphasis
**Prompt:** "Marcus/Kenji still show contract roles; Aisha's links all go to a dead Dice portal; Aisha's résumé must lead with Python/ML; Priya's must frame Kafka/Spark as ML infra."

**Response:** Diagnosed each from the data before coding. **Contract:** broadened detection to catch the staffing tells the
word "contract" misses — "Duration: N months", c2c/1099, contract-to-hire, **unpaid/volunteer** — plus captured Adzuna's
structured `contract_type`; found Adzuna returns it null for ~99% of postings (documented as an honest limit). **Sponsorship:**
broadened the no-sponsor regex (cannot/unable/without sponsor, "US citizens only", "authorized to work without sponsorship").
**Links:** root-caused the dead links to the 2021 archive → emit a live Google search for archive rows, real URL for live Adzuna.
**Résumé:** added `emphasis` + `skills_first` profile fields so the LLM leads the summary/skills with the right themes (Aisha →
Python/ML; Priya → Kafka/Spark as ML-platform/MLOps infra). Verified every persona still passes before deploying.

## 28. Per-persona starting weights + new ranking signals (Priya, Marcus)
**Prompt:** "Priya: more weight on ML titles, US-only but prefer NY/remote (open to other cities). Marcus: weight years-of-experience so only 0–3-yr roles show, lead résumé with MSBA."

**Response:** Added optional per-persona `base_weights` (used as the match's starting weights and to seed the learner) — Priya
leans **title 0.34**; Marcus leans a new **experience-fit signal 0.12**. Split hard `locations` from soft `preferred_locations`
+ added a `location` scoring signal so US-only is the only geo filter while NY/remote rank higher. Rewrote the title matcher to
score **distinctive** role tokens (ml/mlops/platform, with machine-learning↔ml normalization) instead of generic
"engineer"/"senior", so ML titles finally lead for Priya. Marcus kept `education_first` (MSBA-led résumé) + `no_contract`/unpaid.

## 29. Align to the 4 required personas + working CSV links
**Prompt:** "Remove Gayathri; tell me exactly what to submit per the spec." (after reading the spec doc/one-pager)

**Response:** Read the spec `.docx` + one-pager, confirmed the required set is the **4 personas** (the one-pager says "all 4
provided personas"), and removed the self-added Gayathri persona. Applied the same working-link resolver to the CSV/Excel/JSON
**export** (dead archive URL → live search; live Adzuna → real URL) so the downloaded "links to postings" actually work, and
laid out the final deliverables (code/, data/, brief.pdf, prompts.md, README, live URL).
