"""BONUS — Live job postings from the Adzuna API (and optional JSearch).

The spec awards extra credit for pipelines that gather *current* postings. This module
fetches fresh jobs on demand, normalizes them to the same canonical schema as the Kaggle
snapshot (config.CANONICAL_FIELDS), and feeds them through the identical streaming +
Bloom-dedup path in ingest.py. Credentials are read from the environment / a local .env
file, never hardcoded, so they stay out of the submitted ZIP.

Adzuna docs:  https://developer.adzuna.com/overview
Endpoint:     GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
              ?app_id=...&app_key=...&results_per_page=50&what=...&where=...
"""
from __future__ import annotations

import time

import pandas as pd
import requests

from . import config

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"


def adzuna_available() -> bool:
    return bool(config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY)


def fetch_adzuna(
    queries: list[str] | None = None,
    country: str = "us",
    pages: int = 5,
    results_per_page: int = 50,
    where: str | None = None,
    pause_s: float = 0.3,
    start_page: int = 1,
) -> pd.DataFrame:
    """Fetch live postings from Adzuna for one or more search queries.

    start_page lets the caller page DEEPER on a refresh (e.g. pages 3-4) to pull postings
    a previous fetch didn't, instead of re-pulling the same first-page results.

    Returns a RAW DataFrame (Adzuna field names) ready for ingest.normalize().
    Raises RuntimeError if credentials are missing so the caller can fall back cleanly.
    """
    if not adzuna_available():
        raise RuntimeError("Adzuna credentials not set (ADZUNA_APP_ID / ADZUNA_APP_KEY).")

    queries = queries or [
        "machine learning engineer", "data scientist", "data analyst",
        "mlops engineer", "applied scientist", "analytics engineer",
    ]
    rows: list[dict] = []
    for q in queries:
        for page in range(start_page, start_page + pages):
            url = f"{ADZUNA_BASE}/{country}/search/{page}"
            params = {
                "app_id": config.ADZUNA_APP_ID,
                "app_key": config.ADZUNA_APP_KEY,
                "results_per_page": results_per_page,
                "what": q,
                "content-type": "application/json",
            }
            if where:
                params["where"] = where
            try:
                resp = requests.get(url, params=params, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as exc:
                # Stop paginating this query on error (rate limit / network); keep what we have.
                print(f"[adzuna] {q} p{page} failed: {exc}")
                break
            results = resp.json().get("results", [])
            if not results:
                break
            for r in results:
                # Adzuna exposes the employment type as structured fields (contract_type:
                # permanent|contract, contract_time: full_time|part_time) that the free-text
                # description often omits — and Adzuna truncates the description to ~500 chars,
                # so the word "contract" can be absent even on a contract role. Fold those
                # signals into the description text so the shared features.enrich() contract
                # detector picks them up (no schema change needed downstream).
                desc = r.get("description", "") or ""
                ctype = (r.get("contract_type") or "").lower()
                ctime = (r.get("contract_time") or "").lower()
                emp = []
                if ctype == "contract":
                    emp.append("Employment type: contract.")
                elif ctype == "permanent":
                    emp.append("Employment type: permanent / full-time.")
                if ctime == "part_time":
                    emp.append("This is a part-time position.")
                if emp:
                    desc = f"{desc} {' '.join(emp)}".strip()
                rows.append({
                    "title": r.get("title", ""),
                    "company": (r.get("company") or {}).get("display_name", "Unknown"),
                    "location": (r.get("location") or {}).get("display_name", ""),
                    "country": country.upper(),
                    "salary_min": r.get("salary_min"),
                    "salary_max": r.get("salary_max"),
                    "description": desc,
                    "url": r.get("redirect_url", ""),
                    "source": "adzuna",
                    "dateAdded": r.get("created", ""),
                })
            time.sleep(pause_s)  # be polite to the free tier
    return pd.DataFrame(rows)


def fetch_live(country: str = "us", pages: int = 5, start_page: int = 1,
               queries: list[str] | None = None) -> pd.DataFrame:
    """Convenience: fetch live data from whichever source has credentials.

    Returns a canonical (normalized) frame, or an empty frame if no source is configured.
    Imported lazily to avoid a circular import with ingest.
    """
    from .ingest import normalize
    if adzuna_available():
        raw = fetch_adzuna(country=country, pages=pages, start_page=start_page, queries=queries)
        if len(raw):
            return normalize(raw, source="adzuna")
    return pd.DataFrame(columns=config.CANONICAL_FIELDS)
