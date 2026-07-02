"""Batch analytics over the full corpus (required deliverable + dashboard bonus).

Aggregate market insights: top in-demand skills, salary distribution, demand by location,
and postings by source. Returns tidy DataFrames the Streamlit dashboard renders with Plotly.

The top-skills counter is also where the Lecture-2 probabilistic-counting idea applies: at
50k rows we count exactly, but count_skills_cms() shows a Count-Min-Sketch estimate and its
error vs exact — a cheap second benchmark for the brief.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd


def top_skills(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    c = Counter()
    for sk in df["skills"]:
        if isinstance(sk, list):
            c.update(sk)
    rows = c.most_common(n)
    return pd.DataFrame(rows, columns=["skill", "count"])


def salary_distribution(df: pd.DataFrame) -> pd.DataFrame:
    s = pd.to_numeric(df.get("salary_value"), errors="coerce").dropna()
    s = s[(s > 10000) & (s < 600000)]   # drop obvious parse errors
    return pd.DataFrame({"salary": s})


def demand_by_location(df: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    loc = df["location"].fillna("Unknown").astype(str).str.strip().replace("", "Unknown")
    vc = loc.value_counts().head(n)
    return pd.DataFrame({"location": vc.index, "count": vc.values})


def demand_by_source(df: pd.DataFrame) -> pd.DataFrame:
    src = df["source"].astype(str).apply(
        lambda s: "Adzuna (live)" if "adzuna" in s else ("Kaggle" if "kaggle" in s else "Other"))
    vc = src.value_counts()
    return pd.DataFrame({"source": vc.index, "count": vc.values})


def summary_stats(df: pd.DataFrame) -> dict:
    sal = pd.to_numeric(df.get("salary_value"), errors="coerce").dropna()
    sal = sal[(sal > 10000) & (sal < 600000)]
    return {
        "total_jobs": len(df),
        "companies": df["company"].nunique(),
        "locations": df["location"].nunique(),
        "median_salary": float(sal.median()) if len(sal) else None,
        "pct_with_salary": round(100 * len(sal) / max(1, len(df)), 1),
    }


# ---------------------------------------------------------------------------
# Count-Min Sketch benchmark (Lecture 2) — estimate skill frequencies
# ---------------------------------------------------------------------------
class CountMinSketch:
    def __init__(self, width: int = 256, depth: int = 4, seed: int = 7):
        self.w, self.d = width, depth
        self.table = np.zeros((depth, width), dtype=np.int64)
        self.seeds = [(seed + i) * 2654435761 for i in range(depth)]

    def _idx(self, item: str, row: int) -> int:
        return (hash((self.seeds[row], item)) & 0x7FFFFFFF) % self.w

    def add(self, item: str, c: int = 1):
        for r in range(self.d):
            self.table[r, self._idx(item, r)] += c

    def estimate(self, item: str) -> int:
        return int(min(self.table[r, self._idx(item, r)] for r in range(self.d)))


def count_skills_cms(df: pd.DataFrame, top: int = 10) -> pd.DataFrame:
    """Compare exact skill counts vs a Count-Min-Sketch estimate (benchmark)."""
    exact = Counter()
    cms = CountMinSketch()
    for sk in df["skills"]:
        if isinstance(sk, list):
            for s in sk:
                exact[s] += 1
                cms.add(s)
    rows = []
    for skill, ct in exact.most_common(top):
        est = cms.estimate(skill)
        rows.append({"skill": skill, "exact": ct, "cms_estimate": est,
                     "error_pct": round(100 * (est - ct) / ct, 2)})
    return pd.DataFrame(rows)
