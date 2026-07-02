"""Capability 1 — Job data ingestion, streaming, and deduplication.

Techniques benchmarked here:
  * Bloom filter (Lecture 2 — Hashing / probabilistic structures) for O(1)-memory dedup.
  * In-process streaming pipeline (Lecture 3) — records are pushed through a producer ->
    queue -> consumer loop one at a time, mirroring a real streaming ingest. This is the
    offline-safe fallback; the GCP-native streaming path (Google Pub/Sub) lives in
    pubsub_pipeline.py and is used on the hosted Cloud Run app.

The module exposes:
  normalize(raw_df)        -> canonical schema (see config.CANONICAL_FIELDS)
  BloomFilter              -> probabilistic dedup structure
  stream_ingest(df, ...)   -> stream rows, dedup, return (clean_df, stats)
  sample_techmap(...)      -> random byte-offset sample of the 47 GB Kaggle dump
"""
from __future__ import annotations

import hashlib
import json
import math
import queue
import random
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config
from .skills import extract_skills


# ===========================================================================
# 1. Schema normalization (raw source -> canonical)
# ===========================================================================
def _pick_column(raw_cols_lower: dict[str, str], aliases: list[str]) -> str | None:
    for alias in aliases:
        if alias in raw_cols_lower:
            return raw_cols_lower[alias]
    return None


def normalize(raw: pd.DataFrame, source: str = "kaggle") -> pd.DataFrame:
    """Map an arbitrary raw posting frame onto config.CANONICAL_FIELDS."""
    raw_cols_lower = {c.lower(): c for c in raw.columns}
    out = pd.DataFrame(index=raw.index)

    for field_name, aliases in config.COLUMN_ALIASES.items():
        col = _pick_column(raw_cols_lower, aliases)
        out[field_name] = raw[col] if col is not None else None

    # Fill required text fields
    out["title"] = out["title"].fillna("").astype(str).str.strip()
    out["company"] = out["company"].fillna("Unknown").astype(str).str.strip()
    out["location"] = out["location"].fillna("").astype(str).str.strip()
    out["country"] = out["country"].fillna("").astype(str).str.strip()
    out["description"] = out["description"].fillna("").astype(str)

    # Strip any leftover HTML tags from descriptions
    out["description"] = out["description"].str.replace(r"<[^>]+>", " ", regex=True).str.strip()

    # Salaries -> numeric
    out["salary_min"] = pd.to_numeric(out["salary_min"], errors="coerce")
    out["salary_max"] = pd.to_numeric(out["salary_max"], errors="coerce")

    out["url"] = out["url"].fillna("").astype(str)
    out["source"] = out["source"].fillna(source).astype(str)
    out["posted_date"] = out["posted_date"].fillna("").astype(str)

    # Derive skills from title + description when not explicitly provided
    has_skills = out["skills"].apply(lambda v: isinstance(v, (list, str)) and len(str(v)) > 2)
    derived = (out["title"] + ". " + out["description"]).apply(extract_skills)
    out["skills"] = np.where(has_skills, out["skills"], derived)
    out["skills"] = out["skills"].apply(lambda v: v if isinstance(v, list) else extract_skills(str(v)))

    # Drop rows with no title AND no description (unusable)
    out = out[(out["title"] != "") | (out["description"] != "")].copy()

    # Stable job_id from content (used by dedup + as a primary key).
    # Include a description prefix so genuinely distinct roles at the same
    # employer/location survive, while exact reposts collapse.
    desc_key = out["description"].str.lower().str.replace(r"\s+", " ", regex=True).str[:120]
    out["job_id"] = (
        out["title"].str.lower() + "|" + out["company"].str.lower()
        + "|" + out["location"].str.lower() + "|" + desc_key
    ).apply(lambda s: hashlib.md5(s.encode()).hexdigest()[:16])
    return out[config.CANONICAL_FIELDS].reset_index(drop=True)


# ===========================================================================
# 3. Bloom filter (Lecture 2) — probabilistic dedup
# ===========================================================================
class BloomFilter:
    """Space-efficient probabilistic set membership.

    Sized from expected item count n and target false-positive rate p:
        m = -n ln p / (ln 2)^2   bits
        k = (m/n) ln 2           hash functions
    Uses double hashing (md5 + sha1) to synthesize k hashes cheaply.
    """

    def __init__(self, n: int, p: float = 0.01):
        self.n = max(1, n)
        self.p = p
        self.m = max(8, int(-self.n * math.log(p) / (math.log(2) ** 2)))
        self.k = max(1, int((self.m / self.n) * math.log(2)))
        self.bits = bytearray((self.m + 7) // 8)
        self.added = 0

    def _hashes(self, item: str):
        h1 = int(hashlib.md5(item.encode()).hexdigest(), 16)
        h2 = int(hashlib.sha1(item.encode()).hexdigest(), 16)
        for i in range(self.k):
            yield (h1 + i * h2) % self.m

    def _set(self, pos: int):
        self.bits[pos // 8] |= (1 << (pos % 8))

    def _get(self, pos: int) -> bool:
        return bool(self.bits[pos // 8] & (1 << (pos % 8)))

    def add(self, item: str):
        for pos in self._hashes(item):
            self._set(pos)
        self.added += 1

    def __contains__(self, item: str) -> bool:
        return all(self._get(pos) for pos in self._hashes(item))

    @property
    def size_kb(self) -> float:
        return len(self.bits) / 1024.0


# ===========================================================================
# 4. In-process streaming pipeline (Lecture 3) — offline-safe fallback
# ===========================================================================
@dataclass
class IngestStats:
    total_seen: int = 0
    duplicates: int = 0
    ingested: int = 0
    bloom_size_kb: float = 0.0
    elapsed_s: float = 0.0
    throughput_per_s: float = 0.0
    bloom_false_positives: int = 0  # measured vs. an exact set (benchmark)
    notes: dict = field(default_factory=dict)


def stream_ingest(
    df: pd.DataFrame,
    fp_rate: float = 0.01,
    benchmark_exact: bool = True,
    progress=None,
) -> tuple[pd.DataFrame, IngestStats]:
    """Stream rows through a producer->queue->consumer loop with Bloom dedup.

    Returns the deduplicated canonical frame and ingest statistics. `progress` is an
    optional callable(fraction, stats) for live UI updates.
    """
    records = df.to_dict("records")
    n = len(records)
    bloom = BloomFilter(n=max(1000, n), p=fp_rate)
    exact_seen: set[str] = set() if benchmark_exact else None

    q: "queue.Queue" = queue.Queue(maxsize=2000)
    SENTINEL = object()

    def producer():
        for rec in records:
            q.put(rec)
        q.put(SENTINEL)

    threading.Thread(target=producer, daemon=True).start()

    kept: list[dict] = []
    stats = IngestStats()
    stats.notes["backend"] = "in-process-queue"
    t0 = time.perf_counter()

    while True:
        rec = q.get()
        if rec is SENTINEL:
            break
        stats.total_seen += 1
        key = str(rec.get("job_id", "")) or str(rec.get("title", "")) + str(rec.get("company", ""))

        is_dup_bloom = key in bloom
        if is_dup_bloom:
            stats.duplicates += 1
            # Benchmark: was it a TRUE dup or a Bloom false positive?
            if exact_seen is not None and key not in exact_seen:
                stats.bloom_false_positives += 1
        else:
            bloom.add(key)
            kept.append(rec)
            stats.ingested += 1
        if exact_seen is not None:
            exact_seen.add(key)

        if progress and stats.total_seen % 2000 == 0:
            progress(stats.total_seen / max(1, n), stats)

    stats.elapsed_s = time.perf_counter() - t0
    stats.bloom_size_kb = bloom.size_kb
    stats.throughput_per_s = stats.total_seen / max(1e-6, stats.elapsed_s)
    clean = pd.DataFrame(kept).reset_index(drop=True) if kept else df.head(0).copy()
    return clean, stats


# ===========================================================================
# 5. Kaggle techmap dump — parser + random byte-offset sampler
# ===========================================================================
# The techmap "international-job-postings" dump is a 47 GB JSONL MongoDB export
# (3.47M nested records). We never load it whole. Instead we use RANDOM BYTE-OFFSET
# SAMPLING (a sampling technique from Lecture 2): seek to a random byte position,
# discard the partial line, read the next complete record. This pulls a ~uniform
# sample in minutes while touching <5% of the file. Slight length bias (longer
# records are marginally likelier to be hit) is noted in the technical brief.

_ENGLISH_CC = {"us", "uk", "gb", "ca", "au", "ie", "nz", "in", "sg", "za"}


def parse_techmap_record(rec: dict) -> dict | None:
    """Flatten one nested techmap record to alias-friendly raw fields (or None if unusable)."""
    title = (rec.get("name") or rec.get("position", {}).get("name") or "").strip()
    text = (rec.get("text") or "").strip()
    if not title or len(text) < 40:
        return None

    org = rec.get("orgCompany") or {}
    company = (org.get("name")
               or rec.get("orgAddress", {}).get("companyName")
               or rec.get("json", {}).get("schemaOrg", {}).get("hiringOrganization", "")
               or "Unknown")
    if isinstance(company, dict):
        company = company.get("name", "Unknown")

    addr = rec.get("orgAddress") or {}
    location = (addr.get("addressLine") or addr.get("formatted") or "").strip()
    country = (addr.get("countryCode") or rec.get("sourceCC") or "").upper()
    date = rec.get("dateCreated", {})
    date = date.get("$date", "") if isinstance(date, dict) else str(date)

    return {
        "name": title,
        "company": str(company).strip() or "Unknown",
        "location": location,
        "country": country,
        "text": text,
        "url": rec.get("url", ""),
        "source": "kaggle:" + str(rec.get("source", "techmap")),
        "dateAdded": date[:10],
        "_locale": rec.get("locale", ""),
        "_idInSource": rec.get("idInSource", ""),
    }


def _is_english(raw: dict) -> bool:
    loc = (raw.get("_locale") or "").lower()
    if loc.startswith("en"):
        return True
    if loc:                       # explicit non-English locale
        return False
    return (raw.get("country") or "").lower() in _ENGLISH_CC


def sample_techmap(
    path: str,
    target: int = 50000,
    english_only: bool = True,
    seed: int = 42,
    max_attempts_factor: int = 6,
    progress=None,
) -> pd.DataFrame:
    """Random byte-offset sample `target` valid English postings from the big JSONL dump."""
    import os
    rng = random.Random(seed)
    size = os.path.getsize(path)
    seen_ids: set[str] = set()
    rows: list[dict] = []
    attempts = 0
    max_attempts = target * max_attempts_factor

    with open(path, "rb") as f:
        while len(rows) < target and attempts < max_attempts:
            attempts += 1
            f.seek(rng.randint(0, max(1, size - 200_000)))
            f.readline()                      # discard partial line
            line = f.readline()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            raw = parse_techmap_record(rec)
            if raw is None:
                continue
            if english_only and not _is_english(raw):
                continue
            key = raw.get("_idInSource") or (raw["name"] + raw["company"])
            if key in seen_ids:
                continue
            seen_ids.add(key)
            rows.append(raw)
            if progress and len(rows) % 2000 == 0:
                progress(len(rows) / target, attempts)

    df = pd.DataFrame(rows)
    return normalize(df, source="kaggle")
