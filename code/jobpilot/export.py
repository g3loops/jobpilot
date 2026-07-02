"""Capability 6 — download the user's top matches as CSV / Excel / JSON."""
from __future__ import annotations

import io
import json
import urllib.parse

import pandas as pd

EXPORT_COLS = ["title", "company", "location", "salary_min", "salary_max",
               "salary_value", "score", "url", "description"]


def job_link(row) -> str:
    """Canonical 'link to the posting' used by both the UI and the CSV/Excel/JSON export.

    Live Adzuna rows carry a current, valid apply URL — use it. The Kaggle snapshot is a
    Sept-2021 archive whose original listing URLs are dead (boards 301-redirect expired
    listings to their home page), so for those we emit a live Google search for the exact
    title+company+location, which lands on the real current posting or its closest match.
    """
    src = str(row.get("source", "") or "")
    url = str(row.get("url", "") or "")
    if src.startswith("adzuna") and url.startswith("http"):
        return url
    terms = " ".join(str(row.get(k, "") or "") for k in ("title", "company", "location")).strip()
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus((terms + " job").strip())


def _slim(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in EXPORT_COLS if c in df.columns]
    out = df[cols].copy()
    # Replace the raw (often dead-archive) URL with the resolved working link so the
    # downloaded file's "links to postings" actually go somewhere useful.
    if {"url", "source", "title"} & set(df.columns):
        out["url"] = df.apply(job_link, axis=1).values
    if "description" in out:
        out["description"] = out["description"].astype(str).str.slice(0, 2000)
    return out


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return _slim(df).to_csv(index=False).encode("utf-8")


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        _slim(df).to_excel(xw, index=False, sheet_name="Top Matches")
    return buf.getvalue()


def to_json_bytes(df: pd.DataFrame) -> bytes:
    records = _slim(df).to_dict(orient="records")
    return json.dumps(records, indent=2, default=str).encode("utf-8")
