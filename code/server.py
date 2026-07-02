"""JobPilot — FastAPI backend serving a custom HTML/JS frontend (the approved mockup).

All the ML/data logic is reused from the jobpilot package; this server just exposes it as a
REST API and serves the static frontend. Designed for Cloud Run (stateless: the client holds
the learner state + feedback and sends it back each call).

Run locally:  uvicorn server:app --reload --port 8000
"""
from __future__ import annotations

import base64
import threading
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from jobpilot import (analytics, embeddings, explain, export, features, generate,
                      learning, live_sources, ranking, store)
from jobpilot.learning import AdaptiveLearner
from jobpilot.personas import PERSONAS
from jobpilot.profile import UserProfile, extract_pdf_text
from jobpilot.skills import SKILL_PATTERNS

WEB = Path(__file__).resolve().parent / "web"

app = FastAPI(title="JobPilot")


@app.middleware("http")
async def _no_cache_static(request, call_next):
    """Serve the HTML/JS/CSS with no-cache so browsers always revalidate and pick up new
    deploys immediately (the static files otherwise had no Cache-Control, which made
    browsers serve stale assets after a redeploy)."""
    resp = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    return resp

# --- load corpus + index once at startup ---
print("Loading corpus + embeddings…")
# Re-run feature enrichment on load so the latest inference (implied years-of-experience
# from seniority, known-large-employer company sizing) applies to the whole snapshot, not
# just newly-fetched Adzuna rows. Embeddings/job_ids are unaffected (text is unchanged).
DF = features.enrich(store.load_corpus())
VECS, INDEX = store.load_index(DF)
JOB_BY_ID = {r["job_id"]: r for _, r in DF.iterrows()}
print(f"Ready: {len(DF):,} jobs.")

# Serialize live-ingest mutations so two concurrent Adzuna fetches can't race. Appends
# only ADD rows (never reorder/remove), so an in-flight reader using the old INDEX with
# the new DF still maps to valid positions — at worst it misses the just-added jobs.
_ingest_lock = threading.Lock()
_adz_cursor = 1   # next Adzuna page to fetch; advances each refresh so we page DEEPER for
                  # genuinely new postings instead of re-pulling the same first pages.


def ingest_adzuna(pages: int = 2, start_page: int = 1) -> dict:
    """Fetch live Adzuna postings (analyst/ML/data, US) → normalize → enrich → embed →
    dedup against existing job_ids → append to the in-memory corpus/index. Best-effort:
    always returns a status dict and never raises, so startup and the refresh button can't
    break the app (e.g. if Adzuna creds are absent or the API is down)."""
    global DF, VECS, INDEX, JOB_BY_ID
    try:
        if not live_sources.adzuna_available():
            return {"added": 0, "corpus_size": len(DF), "note": "Adzuna credentials not set"}
        live = live_sources.fetch_live(country="us", pages=pages, start_page=start_page)
        if not len(live):
            return {"added": 0, "corpus_size": len(DF), "note": "no live postings returned"}
        enriched = features.enrich(live)
        with _ingest_lock:
            existing = set(DF["job_id"])
            # A job we already have may now arrive with BETTER signals (Adzuna's structured
            # contract_type / a no-sponsorship line the truncated snapshot text lacked). Upgrade
            # the volatile dealbreaker flags in place — contract stays/ becomes True, sponsorship
            # tightens to False — so a stale snapshot row (e.g. a contract role we couldn't detect
            # from 500 truncated chars) stops slipping past no-contract / needs-sponsor filters.
            # Feature columns only: never touches text/embeddings/index order.
            dup = enriched[enriched["job_id"].isin(existing)].drop_duplicates("job_id")
            refreshed = 0
            if len(dup):
                pos = {jid: i for i, jid in enumerate(DF["job_id"].values)}
                for _, src in dup.iterrows():
                    i = pos.get(src["job_id"])
                    if i is None:
                        continue
                    if bool(src["is_contract"]) and not bool(DF.iat[i, DF.columns.get_loc("is_contract")]):
                        DF.iat[i, DF.columns.get_loc("is_contract")] = True
                        refreshed += 1
                    if src["sponsors_visa"] is False and DF.iat[i, DF.columns.get_loc("sponsors_visa")] is not False:
                        DF.iat[i, DF.columns.get_loc("sponsors_visa")] = False
                        refreshed += 1
                    JOB_BY_ID[src["job_id"]] = DF.iloc[i]
            fresh = (enriched[~enriched["job_id"].isin(existing)]
                     .drop_duplicates("job_id").reset_index(drop=True))
            if not len(fresh):
                return {"added": 0, "corpus_size": len(DF), "refreshed": refreshed,
                        "duplicates": int(len(enriched)), "note": "all duplicates"}
            new_vecs = embeddings.embed_jobs(fresh)
            DF = pd.concat([DF, fresh], ignore_index=True)
            VECS = np.vstack([VECS, new_vecs])
            INDEX = embeddings.ANNIndex(VECS)              # rebuild over the grown matrix
            for _, r in fresh.iterrows():
                JOB_BY_ID[r["job_id"]] = r
            return {"added": int(len(fresh)), "corpus_size": int(len(DF)), "refreshed": refreshed,
                    "duplicates": int(len(enriched) - len(fresh)), "note": "ok"}
    except Exception as exc:                                # never let a live fetch crash us
        return {"added": 0, "corpus_size": len(DF), "note": f"adzuna fetch failed: {exc}"}


# Fetch live Adzuna postings by default (alongside the Kaggle snapshot) at startup.
print("Fetching live Adzuna postings (default)…")
print(f"Adzuna: {ingest_adzuna(pages=2, start_page=1)}")
_adz_cursor = 3   # startup consumed pages 1-2; the first refresh starts at page 3

DEALBREAKER_OPTS = ["US only", "No contract/temp", "No defence/military",
                    "No Senior/Staff titles", "No Junior titles", "Needs visa sponsor"]


# ===========================================================================
# Helpers
# ===========================================================================
def _persona_dealbreakers(p: UserProfile) -> list:
    out = []
    if p.us_only: out.append("US only")
    if p.no_contract: out.append("No contract/temp")
    if "defense" in [i.lower() for i in p.exclude_industries]: out.append("No defence/military")
    if p.max_seniority == "mid": out.append("No Senior/Staff titles")
    if p.min_seniority == "senior": out.append("No Junior titles")
    if p.needs_visa_sponsor: out.append("Needs visa sponsor")
    return out


def _persona_payload(p: UserProfile) -> dict:
    return {"name": p.name, "roles": p.target_roles, "skills": p.skills,
            "locations": p.locations, "min_salary": int(p.min_salary),
            "dealbreakers": _persona_dealbreakers(p),
            "max_years_required": p.max_years_required,
            "education": p.education, "experience": p.experience, "projects": p.projects,
            "publications": p.publications, "education_first": p.education_first,
            "emphasis": p.emphasis, "skills_first": p.skills_first,
            "preferred_locations": p.preferred_locations, "base_weights": p.base_weights,
            "contact": p.contact, "resume_text": p.resume_text}


def profile_from_payload(d: dict) -> UserProfile:
    ds = set(d.get("dealbreakers", []))
    return UserProfile(
        name=d.get("name", "You"),
        resume_text=(d.get("resume_text") or "Experienced analyst."),
        skills=[s.lower() for s in d.get("skills", [])],
        target_roles=d.get("roles", []),
        locations=[l.lower() for l in d.get("locations", [])],
        preferred_locations=[l.lower() for l in d.get("preferred_locations", [])],
        base_weights=d.get("base_weights"),
        min_salary=float(d.get("min_salary") or 0),
        us_only=("US only" in ds),
        no_contract=("No contract/temp" in ds),
        exclude_industries=(["defense"] if "No defence/military" in ds else []),
        max_seniority=("mid" if "No Senior/Staff titles" in ds else None),
        min_seniority=("senior" if "No Junior titles" in ds else None),
        needs_visa_sponsor=("Needs visa sponsor" in ds),
        max_years_required=d.get("max_years_required"),
        education=d.get("education", []),
        experience=d.get("experience", []),
        projects=d.get("projects", []),
        publications=d.get("publications", []),
        education_first=bool(d.get("education_first", False)),
        emphasis=d.get("emphasis", []),
        skills_first=bool(d.get("skills_first", False)),
        contact=d.get("contact", ""),
    )


def _salary_str(job) -> str:
    lo, hi, val = job.get("salary_min"), job.get("salary_max"), job.get("salary_value")
    if pd.notna(lo) and pd.notna(hi) and lo != hi:
        return f"${lo/1000:,.0f}k–${hi/1000:,.0f}k"
    if pd.notna(val):
        return f"${val:,.0f}"
    return "salary N/A"


def job_to_dict(job, prof) -> dict:
    e = explain.explain_job(job, prof)
    bd = job.get("score_breakdown", {}) or {}
    return {
        "job_id": job["job_id"], "title": str(job["title"]),
        "company": str(job["company"]), "location": str(job["location"]),
        "salary": _salary_str(job), "url": export.job_link(job),  # working link (shared w/ CSV export)
        "score": round(float(job["score"]), 2),
        "company_size": str(job.get("company_size", "unknown")),
        "seniority": str(job.get("seniority", "")),
        "why": {
            "matched": e["matched_skills"][:4], "overlap": bd.get("_skills_overlap", ""),
            "similarity": round(float(bd.get("similarity", 0)), 2),
            "salary_ok": bool(bd.get("salary", 0) >= 1),
            "title_ok": bool(bd.get("title", 0) > 0),
            "missing": e["missing_skills"][:3],
        },
        "breakdown": {k: float(bd.get(k, 0)) for k in ranking.DEFAULT_WEIGHTS},
    }


def _rank(prof, weights, excluded, n):
    res = ranking.rank_for_profile(DF, INDEX, prof, weights=weights, top_k=25,
                                   exclude_ids=set(excluded or []))
    ranked = res.ranked
    m = ranking.rank_quality_metrics(ranked, prof, k=10)
    jobs = [job_to_dict(r, prof) for _, r in ranked.head(int(n)).iterrows()]
    return {"jobs": jobs, "total": int(res.n_after_filter),
            "candidates": int(res.n_candidates), "metrics": m}


# ===========================================================================
# API
# ===========================================================================
@app.get("/api/options")
def options():
    roles = sorted({r for p in PERSONAS.values() for r in p.profile.target_roles})
    skills = sorted(SKILL_PATTERNS.keys())
    locs = sorted({l for p in PERSONAS.values() for l in p.profile.locations}
                  | {"remote", "united states", "new york", "san francisco",
                     "los angeles", "seattle", "boston", "austin", "chicago"})
    personas = {name: _persona_payload(p.profile) for name, p in PERSONAS.items()}
    return {"roles": roles, "skills": skills, "locations": locs,
            "dealbreakers": DEALBREAKER_OPTS, "personas": personas, "corpus_size": len(DF)}


@app.post("/api/match")
def match(payload: dict):
    prof = profile_from_payload(payload["profile"])
    # Explicit override > the profile's own starting weights (e.g. Priya leans on title) > default.
    weights = payload.get("weights") or prof.base_weights or dict(ranking.DEFAULT_WEIGHTS)
    out = _rank(prof, weights, payload.get("excluded", []), payload.get("n", 10))
    out["weights"] = weights
    return out


@app.post("/api/feedback")
def feedback(payload: dict):
    prof = profile_from_payload(payload["profile"])
    state = payload.get("learner")
    # First feedback (no saved state) starts from the profile's base weights so a persona's
    # title-lean isn't wiped out by the first click; thereafter we resume the saved learner.
    learner = AdaptiveLearner.from_state(state) if state else AdaptiveLearner(weights=prof.base_weights)
    learner.update(payload["breakdown"], payload["action"])
    excluded = set(payload.get("excluded", []))
    if payload["action"] in ("reject", "skip"):
        excluded.add(payload["job_id"])
    out = _rank(prof, learner.weights, excluded, payload.get("n", 10))
    out["weights"] = learner.weights
    out["learner"] = learner.to_state()
    out["excluded"] = list(excluded)
    return out


@app.post("/api/generate")
def gen_doc(payload: dict):
    prof = profile_from_payload(payload["profile"])
    row = JOB_BY_ID.get(payload["job_id"])
    if row is None:
        return JSONResponse({"error": "job not found"}, status_code=404)
    b64 = lambda b: base64.b64encode(b).decode()
    if payload.get("kind", "resume") == "cover":
        r = generate.generate_cover_letter(row, prof)
        return {"docx_b64": b64(r["docx"]), "pdf_b64": b64(r["pdf"]), "preview": r["text"],
                "backend": r["backend"], "filename": "CoverLetter"}
    r = generate.generate_resume(row, prof)
    return {"docx_b64": b64(r["docx"]), "pdf_b64": b64(r["pdf"]), "preview": r["text"],
            "ats": r["ats"], "backend": r["backend"], "filename": "Resume"}


@app.post("/api/export")
def do_export(payload: dict):
    prof = profile_from_payload(payload["profile"])
    res = ranking.rank_for_profile(DF, INDEX, prof, weights=payload.get("weights"),
                                   top_k=25, exclude_ids=set(payload.get("excluded", [])))
    shown = res.ranked.head(int(payload.get("n", 10)))
    fmt = payload.get("fmt", "csv")
    if fmt == "excel":
        data, fn = export.to_excel_bytes(shown), "jobpilot_matches.xlsx"
    elif fmt == "json":
        data, fn = export.to_json_bytes(shown), "jobpilot_matches.json"
    else:
        data, fn = export.to_csv_bytes(shown), "jobpilot_matches.csv"
    return {"b64": base64.b64encode(data).decode(), "filename": fn}


@app.post("/api/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    import io
    raw = await file.read()
    text = extract_pdf_text(io.BytesIO(raw))
    from jobpilot.skills import extract_skills
    return {"resume_text": text, "skills": extract_skills(text)}


@app.get("/api/analytics")
def get_analytics():
    return {
        "summary": analytics.summary_stats(DF),
        "top_skills": analytics.top_skills(DF, 15).to_dict("records"),
        "locations": analytics.demand_by_location(DF, 12).to_dict("records"),
        "sources": analytics.demand_by_source(DF).to_dict("records"),
        "salary": [float(x) for x in analytics.salary_distribution(DF)["salary"].tolist()],
    }


@app.post("/api/pubsub-demo")
def pubsub_demo(payload: dict):
    n = int(payload.get("n", 2000))
    sample = DF.sample(min(n, len(DF)), random_state=5)
    dupes = sample.sample(min(int(n * 0.2), len(sample)), random_state=1)
    combined = pd.concat([sample, dupes], ignore_index=True)
    from jobpilot import pubsub_pipeline, ingest
    if pubsub_pipeline.pubsub_available():
        clean, st = pubsub_pipeline.stream_through_pubsub(combined)
    else:
        clean, st = ingest.stream_ingest(combined)
    return {"backend": st.notes.get("backend"), "topic": st.notes.get("topic", "—"),
            "produced": st.notes.get("produced", st.total_seen), "consumed": st.total_seen,
            "duplicates": st.duplicates, "false_positives": st.bloom_false_positives,
            "bloom_kb": round(st.bloom_size_kb, 1), "rate": int(st.throughput_per_s)}


@app.post("/api/fetch-adzuna")
def fetch_adzuna(payload: dict | None = None):
    """Refresh: pull fresh live Adzuna postings into the in-memory corpus (in addition to
    the Kaggle set already loaded). Pages DEEPER each call so it adds genuinely new jobs.
    Returns how many new jobs were added + the new size."""
    global _adz_cursor
    pages = int((payload or {}).get("pages", 2))
    res = ingest_adzuna(pages=pages, start_page=_adz_cursor)
    _adz_cursor += pages                      # advance so the next refresh goes deeper still
    res["corpus_size"] = len(DF)
    res["available"] = live_sources.adzuna_available()
    return res


@app.post("/api/learning-curve")
def learning_curve(payload: dict):
    """Run the adaptive-learning benchmark (Rubric 3: 'visible improvement') on a profile:
    acceptance rate of surfaced jobs across rounds, adaptive learner vs a no-learning
    random baseline. Uses the live in-memory vectors so it includes any Adzuna jobs."""
    prof = (profile_from_payload(payload["profile"]) if payload.get("profile")
            else PERSONAS[next(iter(PERSONAS))].profile)
    sim = learning.simulate_learning(DF, INDEX, prof, rounds=6, k=10, vecs=VECS)
    lift = (sim.adaptive_accept[-1] - sim.adaptive_accept[0]) if sim.adaptive_accept else 0.0
    return {"rounds": sim.rounds, "adaptive": sim.adaptive_accept, "static": sim.static_accept,
            "final_weights": sim.final_weights, "hidden_weights": sim.hidden_weights,
            "lift": round(lift, 3)}


# --- static frontend (mounted last so /api/* wins) ---
app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
