"""Snapshot + embedding loader. Caches the corpus, embeddings, and ANN index so the
Streamlit app (and tests) load everything once and reuse it.
"""
from __future__ import annotations

import ast

import numpy as np
import pandas as pd

from . import config, embeddings


def _parse_skills(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.startswith("["):
        try:
            return ast.literal_eval(v)
        except Exception:
            return []
    return []


def load_corpus() -> pd.DataFrame:
    """Load the offline snapshot CSV with correct dtypes."""
    df = pd.read_csv(config.SNAPSHOT_CSV, low_memory=False)
    df["skills"] = df["skills"].apply(_parse_skills)
    for col in ["salary_min", "salary_max", "salary_value", "years_required"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "is_contract" in df:
        df["is_contract"] = df["is_contract"].astype(str).str.lower().isin(["true", "1", "1.0"])
    if "is_defense" in df:
        df["is_defense"] = df["is_defense"].astype(str).str.lower().isin(["true", "1", "1.0"])
    return df.reset_index(drop=True)


def load_index(df: pd.DataFrame):
    """Load cached embeddings aligned to df, build the ANN index. Returns (vectors, index)."""
    vecs = embeddings.load_cached_embeddings(df)
    if vecs is None:
        vecs = embeddings.build_job_embeddings(df, cache=True)
    return vecs, embeddings.ANNIndex(vecs)
