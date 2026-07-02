"""'Why ranked here' explanations (required deliverable).

Turns the per-signal score breakdown that ranking.score_job() already produces into a
plain-English rationale, so every recommendation is transparent.
"""
from __future__ import annotations

import pandas as pd

from .ranking import DEFAULT_WEIGHTS
from .skills import skill_overlap

_LABELS = {
    "similarity": "semantic match to your profile",
    "skills": "overlap with your skills",
    "title": "title matches your target roles",
    "salary": "salary fits your floor",
    "seniority": "seniority level fits",
}


def explain_job(job: pd.Series, prof, weights: dict | None = None) -> dict:
    """Return a structured explanation: ranked-position drivers + matched/missing skills."""
    weights = weights or DEFAULT_WEIGHTS
    bd = job.get("score_breakdown", {}) or {}

    # Rank signals by their weighted contribution to the score
    contribs = {k: weights.get(k, 0) * float(bd.get(k, 0)) for k in _LABELS}
    ordered = sorted(contribs.items(), key=lambda kv: kv[1], reverse=True)

    job_skills = set(job.get("skills", []) or [])
    prof_skills = set(prof.skills)
    matched = sorted(job_skills & prof_skills)
    missing = sorted(prof_skills - job_skills)

    reasons = []
    for key, contrib in ordered:
        if contrib <= 0.001:
            continue
        val = float(bd.get(key, 0))
        if key == "skills" and matched:
            reasons.append(f"Matches {len(matched)} of your skills: {', '.join(matched[:6])}")
        elif key == "similarity" and val > 0.3:
            reasons.append(f"Strong {_LABELS[key]} ({val:.0%})")
        elif key == "title" and val > 0:
            reasons.append(f"Title aligns with your target roles")
        elif key == "salary" and val >= 1.0:
            reasons.append("Meets your salary requirement")
        elif key == "seniority" and val >= 1.0:
            reasons.append("Seniority level matches your preference")

    return {
        "score": float(job.get("score", 0)),
        "reasons": reasons or ["Relevant to your profile"],
        "matched_skills": matched,
        "missing_skills": missing[:8],
        "contributions": {k: round(v, 3) for k, v in contribs.items()},
    }
