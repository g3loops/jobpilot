#!/usr/bin/env python3
"""Offline build pipeline — run ONCE to produce the artifacts the app loads instantly.

Steps:
  1. Random byte-offset sample 50k English postings from the 47 GB Kaggle techmap dump.
  2. (Optional) fetch live Adzuna postings and merge them in.
  3. Stream through Google Pub/Sub (or in-process fallback) + Bloom dedup.
  4. Parse structured features (seniority, years, contract, visa, salary...).
  5. Save the offline snapshot CSV (data/jobs_snapshot.csv).
  6. Embed every job and cache vectors to disk (data/artifacts/).

Usage:
    python build_index.py                 # 50k from Kaggle, no live data
    python build_index.py --live          # also fetch live Adzuna postings
    python build_index.py --target 30000  # smaller snapshot
    python build_index.py --no-embed      # snapshot only, skip embeddings
"""
from __future__ import annotations

import argparse
import time
import warnings

warnings.filterwarnings("ignore")

from jobpilot import config, ingest, features, embeddings  # noqa: E402

KAGGLE_DUMP = config.DATA_DIR / "techmap-jobs-dump-2021-09.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=config.SNAPSHOT_TARGET)
    ap.add_argument("--live", action="store_true", help="also fetch live Adzuna postings")
    ap.add_argument("--no-embed", action="store_true", help="skip embedding step")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--pubsub", choices=["auto", "on", "off"], default="auto",
                    help="auto: use Google Pub/Sub if reachable, else in-process; "
                         "on: require Pub/Sub; off: force in-process")
    args = ap.parse_args()

    t_all = time.time()

    # 1. Sample from Kaggle dump
    print(f"[1/6] Sampling {args.target:,} English postings from Kaggle dump (47 GB)...")
    t = time.time()
    kaggle = ingest.sample_techmap(str(KAGGLE_DUMP), target=args.target, seed=args.seed)
    print(f"      -> {len(kaggle):,} postings in {time.time()-t:.0f}s")

    frames = [kaggle]

    # 2. Optional live data
    if args.live:
        print("[2/6] Fetching live Adzuna postings...")
        try:
            from jobpilot import live_sources
            live = live_sources.fetch_live(country="us", pages=8)
            print(f"      -> {len(live):,} live postings")
            if len(live):
                frames.append(live)
        except Exception as exc:  # noqa: BLE001
            print(f"      live fetch skipped: {exc}")
    else:
        print("[2/6] Live data skipped (use --live to enable).")

    import pandas as pd
    combined = pd.concat(frames, ignore_index=True)

    # 3. Stream + Bloom dedup — route through Google Pub/Sub when available.
    use_pubsub = args.pubsub != "off"
    clean = stats = None
    if use_pubsub:
        from jobpilot import pubsub_pipeline
        if pubsub_pipeline.pubsub_available():
            print(f"[3/6] Streaming {len(combined):,} records through Google Pub/Sub "
                  f"(publish → topic → pull) + Bloom dedup...")
            clean, stats = pubsub_pipeline.stream_through_pubsub(combined)
        elif args.pubsub == "on":
            raise SystemExit("--pubsub on requested but Pub/Sub not reachable. Set GOOGLE_CLOUD_PROJECT "
                             "and run `gcloud auth application-default login` (or PUBSUB_EMULATOR_HOST).")
    if clean is None:
        print(f"[3/6] Streaming {len(combined):,} records through in-process pipeline + Bloom dedup "
              f"(no Pub/Sub)...")
        clean, stats = ingest.stream_ingest(combined)
    print(f"      -> seen={stats.total_seen:,} dup={stats.duplicates:,} kept={stats.ingested:,} "
          f"| bloom={stats.bloom_size_kb:.0f}KB fp={stats.bloom_false_positives} "
          f"| {stats.throughput_per_s:,.0f} rec/s | backend={stats.notes.get('backend')}")

    # 4. Feature enrichment
    print("[4/6] Parsing structured features...")
    enriched = features.enrich(clean)

    # 5. Save snapshot
    print(f"[5/6] Saving snapshot -> {config.SNAPSHOT_CSV}")
    enriched.to_csv(config.SNAPSHOT_CSV, index=False)
    print(f"      -> {len(enriched):,} rows, {config.SNAPSHOT_CSV.stat().st_size/1e6:.1f} MB")

    # 6. Embeddings
    if args.no_embed:
        print("[6/6] Embeddings skipped (--no-embed).")
    else:
        print(f"[6/6] Embedding {len(enriched):,} jobs (one-time, ~{len(enriched)/95/60:.0f} min)...")
        t = time.time()
        vecs = embeddings.build_job_embeddings(enriched, cache=True)
        print(f"      -> {vecs.shape} cached in {time.time()-t:.0f}s")

    print(f"\nDONE in {time.time()-t_all:.0f}s. Snapshot + artifacts ready.")


if __name__ == "__main__":
    main()
