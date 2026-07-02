"""GCP-native streaming pipeline with Google Cloud Pub/Sub (Lecture 3).

Replaces the Kafka path. A PUBLISHER sends each job posting to a Pub/Sub topic; a SUBSCRIBER
pulls them back and applies Bloom-filter dedup (Lecture 2) on the consume side. Because
Pub/Sub is fully managed, this runs on Cloud Run (no broker to host) — so the streaming
pipeline is demonstrable on the hosted app.

Safety: each run creates a UNIQUE subscription, pulls only its own messages, acks them, and
deletes the subscription afterward — so concurrent Cloud Run instances or leftover messages
never corrupt the counts (the Pub/Sub analog of the Kafka seek-past-offsets fix).

Auth: on Cloud Run, the service account supplies Application Default Credentials automatically.
Locally, set GOOGLE_CLOUD_PROJECT + run `gcloud auth application-default login`, or point at
the emulator with PUBSUB_EMULATOR_HOST=localhost:8085 (no GCP cost).
"""
from __future__ import annotations

import json
import math
import os
import time

import numpy as np
import pandas as pd

from .ingest import BloomFilter, IngestStats

TOPIC_ID = os.environ.get("PUBSUB_TOPIC", "jobpilot-postings")


def _project() -> str | None:
    return (os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GCP_PROJECT")
            or os.environ.get("PUBSUB_PROJECT_ID"))


def _clean(v):
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (np.integer, np.floating)):
        return v.item()
    return v


def pubsub_available() -> bool:
    """True if Pub/Sub is reachable (real project creds, or the local emulator)."""
    if os.environ.get("PUBSUB_EMULATOR_HOST"):
        return bool(_project())
    if not _project():
        return False
    try:
        from google.cloud import pubsub_v1
        pubsub_v1.PublisherClient()        # picks up ADC; raises if no creds
        return True
    except Exception:
        return False


def _ensure_topic(publisher, topic_path):
    try:
        publisher.create_topic(request={"name": topic_path})
    except Exception:
        pass  # already exists


def stream_through_pubsub(
    df: pd.DataFrame,
    fp_rate: float = 0.01,
    topic_id: str = TOPIC_ID,
    progress=None,
) -> tuple[pd.DataFrame, IngestStats]:
    """Publish every row to a Pub/Sub topic, then pull it back with Bloom dedup."""
    from google.api_core.exceptions import DeadlineExceeded
    from google.cloud import pubsub_v1

    project = _project()
    if not project:
        raise RuntimeError("No GCP project set (GOOGLE_CLOUD_PROJECT).")

    records = df.to_dict("records")
    n = len(records)
    stats = IngestStats()
    stats.notes["backend"] = "pubsub (gcp)"
    stats.notes["topic"] = topic_id
    t0 = time.perf_counter()

    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    topic_path = publisher.topic_path(project, topic_id)
    _ensure_topic(publisher, topic_path)

    # Unique per-run subscription created BEFORE publishing -> we only ever read our own
    # messages, immune to other instances / leftover messages on the topic.
    sub_id = f"{topic_id}-run-{int(t0 * 1000) % 10_000_000}"
    sub_path = subscriber.subscription_path(project, sub_id)
    subscriber.create_subscription(request={"name": sub_path, "topic": topic_path,
                                            "ack_deadline_seconds": 30})
    try:
        # --- PUBLISH ---
        futures = [publisher.publish(topic_path,
                                     json.dumps({k: _clean(v) for k, v in r.items()}).encode("utf-8"))
                   for r in records]
        for f in futures:
            f.result()                      # block until acked by the server
        stats.notes["produced"] = n

        # --- PULL back + Bloom dedup ---
        bloom = BloomFilter(n=max(1000, n), p=fp_rate)
        exact_seen: set[str] = set()
        kept: list[dict] = []
        empty_pulls = 0
        while stats.total_seen < n and empty_pulls < 5:
            try:
                resp = subscriber.pull(request={"subscription": sub_path, "max_messages": 1000},
                                       timeout=15)
            except DeadlineExceeded:
                empty_pulls += 1
                continue
            if not resp.received_messages:
                empty_pulls += 1
                continue
            empty_pulls = 0
            ack_ids = []
            for msg in resp.received_messages:
                ack_ids.append(msg.ack_id)
                rec = json.loads(msg.message.data.decode("utf-8"))
                stats.total_seen += 1
                key = str(rec.get("job_id", "")) or str(rec.get("title", "")) + str(rec.get("company", ""))
                if key in bloom:
                    stats.duplicates += 1
                    if key not in exact_seen:
                        stats.bloom_false_positives += 1
                else:
                    bloom.add(key)
                    kept.append(rec)
                    stats.ingested += 1
                exact_seen.add(key)
            subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})
            if progress:
                progress(stats.total_seen / max(1, n), stats)

        stats.elapsed_s = time.perf_counter() - t0
        stats.bloom_size_kb = bloom.size_kb
        stats.throughput_per_s = stats.total_seen / max(1e-6, stats.elapsed_s)
        clean = pd.DataFrame(kept).reset_index(drop=True) if kept else df.head(0).copy()
        return clean, stats
    finally:
        try:
            subscriber.delete_subscription(request={"subscription": sub_path})
        except Exception:
            pass
        subscriber.close()
