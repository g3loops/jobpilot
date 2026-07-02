"""Central configuration and the clean internal job schema.

Every posting, regardless of source (Kaggle techmap dump, Adzuna API, synthetic),
is normalized to the CANONICAL_FIELDS below before it enters the pipeline. This
keeps ingestion, embedding, ranking, and the UI decoupled from the raw source schema.
"""
from __future__ import annotations

import os
from pathlib import Path

# Load a local .env (credentials for the Adzuna live-data bonus, optional LLM key).
# Safe no-op if python-dotenv or the file is absent.
try:
    from dotenv import load_dotenv
    # override=True so the local .env wins over an empty/placeholder shell var
    # (e.g. a blank ANTHROPIC_API_KEY exported by the parent shell). On Cloud Run the
    # .env file isn't shipped, so this is a no-op there and the real env var is used.
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
except Exception:
    pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CODE_DIR = Path(__file__).resolve().parent.parent          # .../JobPilot/code
PROJECT_DIR = CODE_DIR.parent                              # .../JobPilot
# DATA_DIR defaults to JobPilot/data but can be overridden (e.g. in the Cloud Run
# container, where the layout differs) via the JOBPILOT_DATA_DIR env var.
DATA_DIR = Path(os.environ.get("JOBPILOT_DATA_DIR", PROJECT_DIR / "data"))
ARTIFACTS_DIR = DATA_DIR / "artifacts"                     # embeddings, indexes, snapshots
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Offline snapshot the graders run against (no API/network needed)
SNAPSHOT_CSV = DATA_DIR / "jobs_snapshot.csv"
EMBEDDINGS_NPY = ARTIFACTS_DIR / "job_embeddings.npy"
EMBED_IDS_NPY = ARTIFACTS_DIR / "job_ids.npy"

# ---------------------------------------------------------------------------
# Models / knobs
# ---------------------------------------------------------------------------
EMBED_MODEL = os.environ.get("JOBPILOT_EMBED_MODEL", "all-MiniLM-L6-v2")  # 384-dim, fast, local
SNAPSHOT_TARGET = int(os.environ.get("JOBPILOT_SNAPSHOT_TARGET", "50000"))  # 20k-50k per spec

# Optional live API (graceful fallback if absent)
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")

# Optional LLM for resume generation (falls back to template if absent)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# Canonical schema — the only fields the rest of the app depends on
# ---------------------------------------------------------------------------
CANONICAL_FIELDS = [
    "job_id",       # stable unique id
    "title",        # job title
    "company",      # employer name
    "location",     # human-readable location string
    "country",      # country code/name if available
    "salary_min",   # float or NaN
    "salary_max",   # float or NaN
    "description",  # full JD text
    "skills",       # list[str] (may be derived from description)
    "url",          # apply link
    "source",       # provenance: kaggle / adzuna / synthetic
    "posted_date",  # ISO date string if available
]

# Map of canonical_field -> list of candidate raw column names (lowercased) to look for.
# Covers the Kaggle techmap "international-job-postings" dump + Adzuna naming.
COLUMN_ALIASES = {
    "title":       ["name", "title", "jobtitle", "job_title", "position"],
    "company":     ["company", "orgcompany", "org_company", "employer", "company_name", "companyname"],
    "location":    ["location", "city", "joblocation", "place", "locality", "area", "region"],
    "country":     ["country", "countrycode", "country_code", "nation"],
    "salary_min":  ["salary_min", "salarymin", "min_salary", "salary_lower"],
    "salary_max":  ["salary_max", "salarymax", "max_salary", "salary_upper"],
    "description": ["text", "description", "jobdescription", "job_description", "details", "content", "html"],
    "url":         ["url", "link", "applyurl", "apply_url", "redirect_url", "joburl", "source_url"],
    "posted_date": ["dateadded", "date_added", "posted", "posted_date", "created", "date", "datecreated"],
    "source":      ["source", "site", "board", "via"],
    "skills":      ["skills", "skill", "tags", "keywords"],
}
