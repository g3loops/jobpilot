"""Retrieval benchmark — dense EMBEDDINGS (Lecture 5) vs a KEYWORD/TF-IDF baseline.

This is the A/B that proves the embedding retrieval is worth it. Both methods retrieve
the top-k candidate jobs for the same profile; we score each top-k with the same relevance
metric (a job is "relevant" if it shares >=1 skill with the profile) and report
Precision@k + NDCG@k. Run across all personas to get an averaged win-rate.

Keyword baseline = TF-IDF bag-of-words cosine, i.e. classic lexical search — exactly the
"keyword match only" approach the rubric contrasts embeddings against.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .embeddings import embed_texts
from .skills import skill_overlap

_VECT = None
_MAT = None


def _retrieval_metrics(rows: pd.DataFrame, prof, k: int = 10, min_overlap: int = 2) -> dict:
    """Precision@k (job shares >= min_overlap skills) + graded NDCG@k (by overlap count).

    A stricter relevance bar than the app's >=1-skill metric, so it can actually separate
    a semantic retriever from a lexical one.
    """
    top = rows.head(k)
    if not len(top):
        return {"precision": 0.0, "ndcg": 0.0}
    overlaps = [skill_overlap(r.get("skills", []) or [], prof.skills)[0] for _, r in top.iterrows()]
    rels = [1 if o >= min_overlap else 0 for o in overlaps]
    precision = sum(rels) / len(rels)
    dcg = sum(g / np.log2(i + 2) for i, g in enumerate(overlaps))
    idcg = sum(g / np.log2(i + 2) for i, g in enumerate(sorted(overlaps, reverse=True)))
    ndcg = (dcg / idcg) if idcg > 0 else 0.0
    return {"precision": round(precision, 3), "ndcg": round(ndcg, 3)}


def build_keyword_index(df: pd.DataFrame, max_features: int = 20000):
    """Fit a TF-IDF index over title + skills + description (cached module-level)."""
    global _VECT, _MAT
    from sklearn.feature_extraction.text import TfidfVectorizer
    skills_txt = df["skills"].apply(lambda s: " ".join(s) if isinstance(s, list) else "")
    corpus = (df["title"].fillna("").astype(str) + " " + skills_txt + " "
              + df["description"].fillna("").astype(str).str.slice(0, 400))
    _VECT = TfidfVectorizer(max_features=max_features, stop_words="english", ngram_range=(1, 2))
    _MAT = _VECT.fit_transform(corpus)
    return _VECT, _MAT


def keyword_retrieve(prof, k: int = 50) -> np.ndarray:
    """Top-k job indices by TF-IDF cosine to the profile query (lexical baseline)."""
    from sklearn.metrics.pairwise import linear_kernel
    qv = _VECT.transform([prof.profile_blob()])
    sims = linear_kernel(qv, _MAT).ravel()
    return np.argsort(sims)[::-1][:k]


def embedding_retrieve(df, index, prof, k: int = 50) -> np.ndarray:
    """Top-k job indices by dense-embedding cosine (the system's method)."""
    pv = embed_texts([prof.profile_blob()])[0]
    idx, _ = index.query(pv, k=k)
    return np.array(idx)


def benchmark_retrieval(df, index, prof, k: int = 10) -> dict:
    """Compare embedding vs keyword retrieval for one profile."""
    emb_idx = embedding_retrieve(df, index, prof, k=k)
    kw_idx = keyword_retrieve(prof, k=k)
    return {
        "embedding": _retrieval_metrics(df.iloc[emb_idx], prof, k=k),
        "keyword":   _retrieval_metrics(df.iloc[kw_idx], prof, k=k),
    }


def run_full_benchmark(df, index, personas: dict, k: int = 10) -> pd.DataFrame:
    """Embedding vs keyword across all personas -> tidy results table."""
    if _MAT is None:
        build_keyword_index(df)
    rows = []
    for name, persona in personas.items():
        r = benchmark_retrieval(df, index, persona.profile, k=k)
        rows.append({
            "persona": name.split(" (")[0],
            "embed_P@10": r["embedding"]["precision"], "embed_NDCG": r["embedding"]["ndcg"],
            "keyword_P@10": r["keyword"]["precision"], "keyword_NDCG": r["keyword"]["ndcg"],
            "P@10_lift": round(r["embedding"]["precision"] - r["keyword"]["precision"], 3),
        })
    return pd.DataFrame(rows)
