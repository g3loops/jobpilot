"""Shared skill vocabulary + extraction.

Both job descriptions and user profiles are reduced to a normalized set of skills
from a controlled vocabulary. Keeping one vocabulary on both sides makes skill
overlap (a ranking signal) well-defined and explainable.
"""
from __future__ import annotations

import re
from typing import Iterable

# Controlled vocabulary: canonical_skill -> regex of surface forms.
# Curated for the data/ML/SWE roles the four test personas target.
SKILL_PATTERNS: dict[str, str] = {
    "python":            r"\bpython\b",
    "r":                 r"(?<![a-z])r(?![a-z])(?=\b)",  # standalone 'R'
    "sql":               r"\bsql\b",
    "pandas":            r"\bpandas\b",
    "numpy":             r"\bnumpy\b",
    "scikit-learn":      r"\b(scikit[- ]?learn|sklearn)\b",
    "pytorch":           r"\b(pytorch|torch)\b",
    "tensorflow":        r"\b(tensorflow|keras)\b",
    "deep learning":     r"\bdeep learning\b",
    "machine learning":  r"\b(machine learning|ml engineer|ml engineering)\b",
    "nlp":               r"\b(nlp|natural language processing)\b",
    "computer vision":   r"\b(computer vision|opencv)\b",
    "spark":             r"\b(spark|pyspark)\b",
    "kafka":             r"\bkafka\b",
    "hadoop":            r"\bhadoop\b",
    "aws":               r"\b(aws|amazon web services)\b",
    "gcp":               r"\b(gcp|google cloud)\b",
    "azure":             r"\bazure\b",
    "kubernetes":        r"\b(kubernetes|k8s)\b",
    "docker":            r"\bdocker\b",
    "microservices":     r"\bmicroservices?\b",
    "java":              r"\bjava\b(?!script)",
    "c++":               r"\bc\+\+\b",
    "scala":             r"\bscala\b",
    "tableau":           r"\btableau\b",
    "power bi":          r"\bpower\s?bi\b",
    "excel":             r"\bexcel\b",
    "etl":               r"\b(etl|elt|data pipeline)\b",
    "airflow":           r"\bairflow\b",
    "mlops":             r"\bmlops\b",
    "statistics":        r"\b(statistics|statistical)\b",
    "data analysis":     r"\b(data analysis|analytics)\b",
    "deep reinforcement":r"\b(reinforcement learning|rl)\b",
}

_COMPILED = {name: re.compile(pat, re.IGNORECASE) for name, pat in SKILL_PATTERNS.items()}


def extract_skills(text: str) -> list[str]:
    """Return the sorted set of canonical skills present in free text."""
    if not text:
        return []
    found = [name for name, rx in _COMPILED.items() if rx.search(text)]
    return sorted(set(found))


def skill_overlap(job_skills: Iterable[str], profile_skills: Iterable[str]) -> tuple[int, int]:
    """(num_overlapping, num_job_skills) — used by the ranker and explain panel."""
    js, ps = set(job_skills), set(profile_skills)
    return len(js & ps), len(js)
