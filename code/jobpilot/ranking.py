"""Capability 4 — Multi-stage ranking pipeline (Lecture 7: Ranking & Multi-Stage Retrieval).

Stages:
  1. CANDIDATE GENERATION — ANN retrieval pulls the top-N (default 300) embedding-nearest
     jobs from the 50k corpus. Cheap recall stage.
  2. HARD FILTERS — drop any candidate that violates a dealbreaker (salary floor, location/
     US-only, contract, seniority cap/floor, defence exclusion, visa sponsorship, company
     size). Unknown values are NOT treated as violations (can't exclude on missing data).
  3. SCORING & RE-RANK — score survivors by a transparent weighted blend of signals
     (embedding similarity, skill overlap, title/role match, salary fit, seniority match)
     so every ranking is explainable.

Evaluation: rank_quality_metrics() reports precision@k and a skill-overlap NDCG-style score.
The keyword-vs-embedding A/B benchmark lives in benchmark.py (proves the L5 retriever beats
a TF-IDF lexical baseline).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .embeddings import ANNIndex, embed_texts
from .profile import UserProfile
from .skills import skill_overlap

# Default scoring weights (sum ~1). Tuned for transparency; the adaptive learner (Cap 5)
# nudges these from user feedback.
DEFAULT_WEIGHTS = {
    "similarity": 0.38,   # embedding cosine similarity (semantic title+skill match)
    "skills": 0.25,       # fraction of profile skills the job mentions
    "title": 0.24,        # target-role keyword match in the title
    "salary": 0.04,       # salary is mainly a HARD FILTER (below-min is dropped in stage 2);
                          # as a soft signal it is only a light tiebreaker, so it can't push an
                          # off-title/off-skill job up the list just for paying well.
    "seniority": 0.04,    # seniority aligns with preference
    "location": 0.05,     # SOFT location preference — preferred_locations (e.g. Priya: NY/remote)
                          # rank higher, but other in-region jobs still qualify (the only hard geo
                          # rule is us_only). Neutral (0.5) when a profile states no preference.
    "experience": 0.0,    # years-of-experience FIT — rewards roles needing FEWER years for
                          # candidates who cap experience (e.g. Marcus, a new grad). Starts 0 so
                          # it's opt-in per persona (via base_weights); neutral when no cap is set.
    "company_size": 0.0,  # large vs small employer — starts neutral, LEARNED from feedback
                          # (e.g. Kenji rejects tiny startups -> learner up-weights this so
                          #  small companies get deprioritised). See learning.py.
}

_SENIORITY_ORDER = {"junior": 0, "mid": 1, "senior": 2, "staff": 3}


# ===========================================================================
# Stage 2 — hard filters
# ===========================================================================
def _s(v) -> str:
    """NaN/None-safe string coercion."""
    return "" if v is None or (isinstance(v, float) and v != v) else str(v)


def _loc_ok(job_loc, job_country, prof: UserProfile) -> bool:
    loc = _s(job_loc).lower()
    country = _s(job_country).lower()
    if prof.us_only and country and country not in {"us", "usa", "united states"}:
        # allow only if the location string explicitly names the US (a bare
        # "remote" does NOT rescue a known non-US country, e.g. a UK remote job).
        if not any(tok in loc for tok in ["united states", "usa", ", us"]):
            return False
    if prof.locations:
        # Match each preferred token on WORD boundaries so short tokens like "ca"
        # don't false-match substrings (e.g. "ca" inside "chiCAgo").
        toks = [t.lower() for t in prof.locations]
        if "remote" in toks and "remote" in loc:
            return True
        return any(re.search(r"\b" + re.escape(t) + r"\b", loc) for t in toks)
    return True


def passes_filters(job: pd.Series, prof: UserProfile) -> bool:
    # Salary: only exclude when the job's salary is KNOWN and below the floor.
    if prof.min_salary and pd.notna(job.get("salary_value")):
        if job["salary_value"] < prof.min_salary:
            return False
    # Location / US-only
    if not _loc_ok(job.get("location", ""), job.get("country", ""), prof):
        return False
    # Contract
    if prof.no_contract and bool(job.get("is_contract", False)):
        return False
    # Seniority cap (e.g. Aisha: no senior/staff)
    if prof.max_seniority:
        cap = _SENIORITY_ORDER.get(prof.max_seniority, 99)
        if _SENIORITY_ORDER.get(job.get("seniority", "mid"), 1) > cap:
            return False
    # Seniority floor (e.g. Priya: no junior)
    if prof.min_seniority:
        floor = _SENIORITY_ORDER.get(prof.min_seniority, 0)
        if _SENIORITY_ORDER.get(job.get("seniority", "mid"), 1) < floor:
            return False
    # Years required (dealbreaker). Only exclude when known.
    if prof.max_years_required is not None:
        if int(job.get("years_required", 0) or 0) > prof.max_years_required:
            return False
    # Excluded industries (e.g. defence)
    if "defense" in [i.lower() for i in prof.exclude_industries] and bool(job.get("is_defense", False)):
        return False
    # Company size floor (e.g. Priya: large only). Only exclude KNOWN small.
    if prof.min_company_size == "large" and job.get("company_size") == "small":
        return False
    # Visa sponsorship: only exclude when explicitly known to NOT sponsor.
    if prof.needs_visa_sponsor and job.get("sponsors_visa") is False:
        return False
    return True


# ===========================================================================
# Stage 3 — scoring (transparent, explainable)
# ===========================================================================
# Generic title tokens carry little signal — almost every posting is some kind of
# "engineer"/"analyst", so matching on these alone makes unrelated roles look on-title.
# We score on the DISTINCTIVE tokens of each target role instead (e.g. ml, mlops, platform).
# (intentionally excludes ml/mlops/ai/data/platform/cloud etc. — those ARE distinctive)
_GENERIC_TITLE_TOKENS = {
    "engineer", "engineering", "senior", "sr", "jr", "junior", "staff", "lead", "principal",
    "manager", "management", "analyst", "developer", "development", "specialist", "consultant",
    "architect", "associate", "intern", "i", "ii", "iii", "iv", "of", "the", "and", "a", "an",
    "for", "to", "in",
}


def _norm_title(s: str) -> str:
    s = _s(s).lower()
    s = re.sub(r"machine\s+learning", "ml", s)
    s = re.sub(r"artificial\s+intelligence", "ai", s)
    s = re.sub(r"\bml\s*ops\b", "mlops", s)
    s = re.sub(r"\bm\.?l\.?\b", "ml", s)
    return s


def _title_match(title: str, roles: list[str]) -> float:
    toks = set(re.findall(r"[a-z0-9+#]+", _norm_title(title)))
    if not roles or not toks:
        return 0.0
    best = 0.0
    for r in roles:
        rtoks = re.findall(r"[a-z0-9+#]+", _norm_title(r))
        distinctive = [w for w in rtoks if w not in _GENERIC_TITLE_TOKENS] or rtoks
        hits = sum(1 for w in distinctive if w in toks)
        best = max(best, hits / max(1, len(distinctive)))
    return best


def _salary_score(job: pd.Series, prof: UserProfile) -> float:
    if not prof.min_salary or pd.isna(job.get("salary_value")):
        return 0.5  # neutral when unknown
    return 1.0 if job["salary_value"] >= prof.min_salary else 0.0


def _seniority_score(job: pd.Series, prof: UserProfile) -> float:
    js = _SENIORITY_ORDER.get(job.get("seniority", "mid"), 1)
    if prof.max_seniority:
        return 1.0 if js <= _SENIORITY_ORDER.get(prof.max_seniority, 99) else 0.0
    if prof.min_seniority:
        return 1.0 if js >= _SENIORITY_ORDER.get(prof.min_seniority, 0) else 0.0
    return 0.5


def _location_score(job: pd.Series, prof: UserProfile) -> float:
    """Soft preference: 1.0 if the job is in one of the profile's preferred locations (or
    remote when that's preferred), else a low-but-nonzero 0.3 so other qualifying (e.g.
    US) jobs still appear, just ranked below the preferred ones. Neutral 0.5 when the
    profile expresses no preference (so this signal does nothing for those users)."""
    prefs = [p.lower() for p in (getattr(prof, "preferred_locations", []) or [])]
    if not prefs:
        return 0.5
    loc = _s(job.get("location", "")).lower()
    if "remote" in prefs and "remote" in loc:
        return 1.0
    return 1.0 if any(re.search(r"\b" + re.escape(t) + r"\b", loc) for t in prefs) else 0.3


def _experience_score(job: pd.Series, prof: UserProfile) -> float:
    """Years-of-experience fit. For a candidate who caps experience (max_years_required set,
    e.g. a new grad), reward roles needing FEWER years: 0 yrs -> 1.0, scaling down toward the
    cap, and 0.0 above the cap (those are also hard-filtered out). Neutral 0.5 when the profile
    sets no cap, so this signal is inert for everyone except experience-sensitive personas."""
    cap = prof.max_years_required
    if cap is None:
        return 0.5
    yr = int(job.get("years_required", 0) or 0)
    if yr > cap:
        return 0.0
    return 1.0 - 0.5 * (yr / max(1, cap))


def _company_size_score(job: pd.Series) -> float:
    """Large employer -> 1.0, small -> 0.0, unknown -> 0.5 (neutral). Lets the adaptive
    learner deprioritise small companies once a user rejects them (e.g. Kenji)."""
    return {"large": 1.0, "small": 0.0}.get(job.get("company_size", "unknown"), 0.5)


def score_job(job: pd.Series, prof: UserProfile, sim: float, weights: dict) -> tuple[float, dict]:
    """Return (total_score, per-signal breakdown) — the breakdown powers the explain panel."""
    n_overlap, n_job = skill_overlap(job.get("skills", []) or [], prof.skills)
    skills_score = n_overlap / max(1, len(prof.skills))
    parts = {
        "similarity": float(sim),
        "skills": float(skills_score),
        "title": _title_match(job.get("title", ""), prof.target_roles),
        "salary": _salary_score(job, prof),
        "seniority": _seniority_score(job, prof),
        "location": _location_score(job, prof),
        "experience": _experience_score(job, prof),
        "company_size": _company_size_score(job),
    }
    total = sum(weights.get(k, 0) * v for k, v in parts.items())
    parts["_skills_overlap"] = f"{n_overlap}/{len(prof.skills)}"
    return total, parts


# ===========================================================================
# Full pipeline
# ===========================================================================
@dataclass
class RankResult:
    ranked: pd.DataFrame          # filtered + scored, sorted desc by score
    n_candidates: int
    n_after_filter: int
    profile_vec: np.ndarray


def rank_jobs(
    jobs: pd.DataFrame,
    profile_vec: np.ndarray,
    index: ANNIndex,
    prof: UserProfile,
    weights: dict | None = None,
    n_candidates: int = 1000,
    top_k: int = 50,
    exclude_ids: set | None = None,
) -> RankResult:
    """Run candidate generation -> hard filters -> scoring -> re-rank.

    exclude_ids: job_ids the user disliked/skipped — dropped so they never reappear.
    """
    weights = weights or DEFAULT_WEIGHTS
    idx, sims = index.query(profile_vec, k=n_candidates)
    cand = jobs.iloc[idx].copy()
    cand["similarity"] = sims

    # Stage 2: hard filters (+ drop user-excluded jobs)
    mask = cand.apply(lambda r: passes_filters(r, prof), axis=1)
    filtered = cand[mask].copy()
    if exclude_ids:
        filtered = filtered[~filtered["job_id"].isin(exclude_ids)]

    # Stage 3: score + re-rank
    scored = filtered.apply(lambda r: score_job(r, prof, r["similarity"], weights), axis=1)
    if len(filtered):
        filtered["score"] = [s for s, _ in scored]
        filtered["score_breakdown"] = [b for _, b in scored]
        filtered = filtered.sort_values("score", ascending=False).head(top_k).reset_index(drop=True)

    return RankResult(filtered, len(cand), int(mask.sum()), profile_vec)


def rank_for_profile(jobs, index, prof: UserProfile, **kw) -> RankResult:
    """Convenience: embed the profile then rank."""
    pvec = embed_texts([prof.profile_blob()])[0]
    return rank_jobs(jobs, pvec, index, prof, **kw)


# ===========================================================================
# Evaluation metrics (Capability 4 requires reporting at least one)
# ===========================================================================
def rank_quality_metrics(ranked: pd.DataFrame, prof: UserProfile, k: int = 10) -> dict:
    """Precision@k (skill-relevant) + skill-overlap NDCG@k over the top-k results."""
    top = ranked.head(k)
    if not len(top):
        return {"precision_at_k": 0.0, "ndcg_at_k": 0.0, "k": k, "n": 0}

    # Relevance = job shares >=1 skill with the profile (proxy ground truth)
    rels = [1 if skill_overlap(r.get("skills", []) or [], prof.skills)[0] > 0 else 0
            for _, r in top.iterrows()]
    precision = sum(rels) / len(rels)

    # Graded relevance = #overlapping skills; NDCG vs ideal ordering
    gains = [skill_overlap(r.get("skills", []) or [], prof.skills)[0] for _, r in top.iterrows()]
    dcg = sum(g / np.log2(i + 2) for i, g in enumerate(gains))
    idcg = sum(g / np.log2(i + 2) for i, g in enumerate(sorted(gains, reverse=True)))
    ndcg = (dcg / idcg) if idcg > 0 else 0.0
    return {"precision_at_k": round(precision, 3), "ndcg_at_k": round(ndcg, 3), "k": k, "n": len(top)}
