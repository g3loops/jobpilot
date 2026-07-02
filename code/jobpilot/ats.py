"""ATS keyword extraction + match scoring.

Real applicant-tracking systems rank a résumé by how many of the *job description's*
keywords it contains. This module:
  1. extracts the ATS-relevant keywords actually present in a given job posting
     (a broad curated vocabulary spanning data / analytics / finance / engineering,
     plus the controlled skill vocabulary), and
  2. scores how many of those keywords the candidate's profile already covers.

The résumé generator then surfaces the COVERED keywords (things the candidate truly has
that the job asks for) — honest ATS alignment, no fabrication. MISSING keywords are shown
to the user as suggestions, never inserted into the résumé.
"""
from __future__ import annotations

import re

import pandas as pd

from .skills import SKILL_PATTERNS

# Curated ATS keyword vocabulary (multi-word first so they win during matching).
ATS_VOCAB = [
    # Finance / FP&A
    "financial modeling", "financial modelling", "financial analysis", "variance analysis",
    "forecasting", "budgeting", "financial planning", "fp&a", "p&l", "profit and loss",
    "gaap", "reconciliation", "accounts payable", "accounts receivable", "month-end close",
    "cost analysis", "revenue analysis", "valuation", "audit", "financial reporting",
    "cash flow", "general ledger", "accruals", "cost accounting",
    # Data / analytics / BI
    "data analysis", "data analytics", "business intelligence", "data visualization",
    "dashboards", "reporting", "kpis", "key performance indicators", "data warehouse",
    "etl", "data pipeline", "data modeling", "predictive modeling", "statistical analysis",
    "regression", "a/b testing", "experimentation", "forecasting models", "segmentation",
    "data cleaning", "data wrangling", "ad hoc analysis", "stakeholder management",
    "requirements gathering", "process improvement", "data governance", "data quality",
    # Tools / tech
    "sql", "python", "tableau", "power bi", "looker", "excel", "vba", "sas", "spss",
    "alteryx", "snowflake", "dbt", "airflow", "spark", "hadoop", "aws", "azure", "gcp",
    "salesforce", "google analytics", "looker studio", "bigquery", "redshift",
    "machine learning", "deep learning", "nlp", "pytorch", "tensorflow", "scikit-learn",
    "docker", "kubernetes", "git", "rest api", "microservices",
    # Soft / role
    "cross-functional", "communication", "presentation", "problem solving",
    "project management", "agile", "stakeholder", "stakeholders", "collaboration",
    # Single-word + synonym catches (reduce false 0% from rigid phrasing)
    "requirements", "reporting", "dashboard", "kpi", "analyst", "analytics",
    "banking", "finance", "financial", "accounting", "modeling", "modelling",
    "testing", "quality assurance", "qa", "user stories", "use cases",
    "mysql", "postgresql", "sql server", "pivot tables", "vlookup", "macros",
    "powerpoint", "presentations", "wireframes", "business analyst", "data analyst",
    "process improvement", "documentation", "metrics", "insights", "visualization",
]
# Add controlled skill vocab surface forms (single words) for completeness
_EXTRA = [k for k in SKILL_PATTERNS.keys() if k not in ATS_VOCAB]
ATS_VOCAB = ATS_VOCAB + _EXTRA

_COMPILED = [(kw, re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)) for kw in ATS_VOCAB]


def extract_jd_keywords(text: str, top: int = 25) -> list[str]:
    """Return the ATS keywords actually present in a job description (longest-match first)."""
    if not text:
        return []
    found = []
    for kw, rx in _COMPILED:
        if rx.search(text):
            # avoid adding a keyword that's a substring of one already found
            if not any(kw != f and kw in f for f in found):
                found.append(kw)
    # de-dup near-duplicates (e.g. "financial modeling"/"financial modelling")
    seen, out = set(), []
    for kw in found:
        norm = kw.replace("modelling", "modeling")
        if norm not in seen:
            seen.add(norm); out.append(kw)
    return out[:top]


def _candidate_corpus(prof) -> str:
    parts = [prof.resume_text, " ".join(prof.skills), " ".join(prof.target_roles),
             " ".join(getattr(prof, "experience", []) or []),
             " ".join(getattr(prof, "education", []) or [])]
    return " ".join(parts).lower()


def ats_match(job: pd.Series, prof) -> dict:
    """Score how well the candidate covers a job's ATS keywords."""
    jd_text = f"{job.get('title', '')}. {job.get('description', '')}"
    jd_kw = extract_jd_keywords(jd_text)
    cand = _candidate_corpus(prof)
    covered = [k for k in jd_kw if re.search(r"\b" + re.escape(k) + r"\b", cand)]
    missing = [k for k in jd_kw if k not in covered]
    score = round(100 * len(covered) / len(jd_kw), 0) if jd_kw else 0.0
    return {
        "score": score,                 # % of JD keywords the profile covers
        "covered": covered,             # honest -> can go in the résumé
        "missing": missing,             # suggestions only (shown in UI, never inserted)
        "jd_keywords": jd_kw,
        "n_jd": len(jd_kw),
    }
