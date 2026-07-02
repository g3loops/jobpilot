"""Derived structured features parsed from each posting.

The hard filters (Capability 4) and the persona pass-criteria need fields that are
not columns in the raw data — seniority, years of experience required, contract flag,
visa sponsorship, defence/military flag, company-size hint. We parse them once from
title + description and cache them as columns on the canonical frame.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

_SENIORITY = [
    ("staff", r"\b(staff|principal|distinguished)\b"),
    ("senior", r"\b(senior|sr\.?|lead)\b"),
    ("junior", r"\b(junior|jr\.?|entry[- ]level|intern|new grad|graduate)\b"),
]
_YEARS_RX = re.compile(r"(\d+)\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)
# Contract / temporary / staffing roles. Beyond the literal "contract" word we also catch
# the staffing-agency tells that never say "contract" outright: a fixed engagement length
# ("Duration: 6 Months", "12-month engagement") and corp-to-corp / 1099 markers. These are
# how most Dice/staffing postings (e.g. "Duration: 12 months") and many Adzuna contract
# roles signal a non-permanent role.
_CONTRACT_RX = re.compile(
    r"\b(?:contract|contractor|contract[- ]to[- ]hire|c2c|corp[- ]to[- ]corp|1099"
    r"|temp(?:orary)?|part[- ]time|freelance)\b"
    r"|\bduration\s*[:\-]?\s*\d+\s*\+?\s*(?:months?|mos?|weeks?|years?|yrs?)\b"
    r"|\b\d+\s*[-+]?\s*(?:month|week|yr|year)s?\s+(?:contract|engagement|assignment|project|gig)\b"
    # Unpaid / volunteer roles (a dealbreaker for Marcus). Guarded so benefits language like
    # "unpaid leave / unpaid time off" does NOT trip it.
    r"|\bunpaid\s+(?:intern(?:ship)?|position|role|opportunity|work)\b"
    r"|\bvolunteer\s+(?:intern(?:ship)?|position|role|opportunity)\b"
    r"|\b(?:no|without)\s+compensation\b",
    re.IGNORECASE,
)
# "Does not / cannot / will not sponsor", "no visa sponsorship", "without sponsorship",
# "US citizens only", "authorized to work without sponsorship" — the common ways a posting
# rules out visa candidates (Kenji needs sponsorship, so any of these must exclude the job).
_NO_SPONSOR_RX = re.compile(
    r"(?:"
    r"\bno\s+(?:visa\s+|h-?1b\s+)?sponsor"
    r"|\bnot\s+(?:able|in a position|willing|currently able)\s+to\s+sponsor"
    r"|\b(?:cannot|can'?t|unable to|won'?t|will not|do(?:es)? not|are not able to)\s+"
    r"(?:currently\s+)?(?:provide|offer|support|extend|consider)?\s*(?:visa\s+)?sponsor"
    r"|\bwithout\s+(?:visa\s+)?sponsor"
    r"|\bsponsorship\s+(?:is\s+)?(?:not\s+available|unavailable|not\s+provided|not\s+offered)"
    r"|\bno\s+(?:c2c|corp[- ]to[- ]corp)\b"
    r"|\bauthoriz(?:ed|ation)\s+to\s+work[^.]{0,40}without\s+sponsor"
    r"|\b(?:us|u\.s\.?)\s+citizens?\s+only\b"
    r"|\bmust\s+be\s+(?:a\s+)?(?:us|u\.s\.?)\s+citizen"
    r")", re.IGNORECASE,
)
_SPONSOR_RX = re.compile(r"\b(?:h-?1b|sponsor(?:ship)? (?:is )?(?:available|provided|offered)|will sponsor)\b", re.IGNORECASE)
_DEFENSE_RX = re.compile(r"\b(?:defen[cs]e|military|lockheed|raytheon|northrop|weapons?|aerospace defen)\b", re.IGNORECASE)
_SMALL_RX = re.compile(r"\b(?:early[- ]stage|seed|tiny|small (?:startup|team)|<\s*\d{1,2}\s*employees|stealth)\b", re.IGNORECASE)
_LARGE_RX = re.compile(r"\b(?:fortune|enterprise|\d{3,}\+? employees|large (?:company|team)|publicly traded)\b", re.IGNORECASE)


# Well-known large employers (>>100 staff) — used to assign company_size="large" even when
# the description has no explicit size cue. Matched as a substring of the company name.
LARGE_COMPANIES = {
    "google", "alphabet", "youtube", "amazon", "aws", "apple", "microsoft", "meta",
    "facebook", "instagram", "oracle", "ibm", "intel", "nvidia", "amd", "qualcomm", "cisco",
    "salesforce", "adobe", "sap", "netflix", "uber", "lyft", "airbnb", "paypal", "stripe",
    "linkedin", "tesla", "spacex", "deloitte", "accenture", "pwc", "pricewaterhouse", "kpmg",
    "ernst", "jpmorgan", "jp morgan", "goldman", "morgan stanley", "wells fargo",
    "bank of america", "citigroup", "citibank", "american express", "capital one", "visa",
    "mastercard", "comcast", "verizon", "at&t", "t-mobile", "walmart", "target", "costco",
    "home depot", "disney", "warner", "booz allen", "lockheed", "raytheon", "northrop",
    "boeing", "general electric", "ford", "general motors", "johnson & johnson", "pfizer",
    "unitedhealth", "cvs", "kaiser", "intuit", "workday", "servicenow", "snowflake",
    "databricks", "palantir", "dell", "hewlett", "nike", "starbucks", "mcdonald", "pepsico",
    "coca-cola", "procter", "honeywell", "caterpillar", "fedex", "ups", "marriott", "hilton",
    "wipro", "infosys", "tcs", "tata", "cognizant", "capgemini", "oracle", "indeed", "spotify",
}


def _seniority(title: str, desc: str) -> str:
    blob = f"{title} {desc}".lower()
    for level, rx in _SENIORITY:
        if re.search(rx, blob):
            return level
    return "mid"


def _years_required(desc: str) -> int:
    nums = [int(m) for m in _YEARS_RX.findall(desc or "")]
    return max(nums) if nums else 0


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add parsed feature columns to a canonical frame (returns a copy)."""
    out = df.copy()
    title = out["title"].fillna("").astype(str)
    desc = out["description"].fillna("").astype(str)
    blob = (title + ". " + desc)

    out["seniority"] = [_seniority(t, d) for t, d in zip(title, desc)]
    # Years required: explicit "N years" if stated, else IMPLY from seniority so that a
    # "Senior"/"Staff" posting with no explicit number still reads as experienced (fixes
    # new-grad filtering — e.g. Marcus must not see senior roles).
    _implied = {"senior": 5, "staff": 8, "mid": 0, "junior": 0}
    out["years_required"] = [max(_years_required(d), _implied.get(sen, 0))
                             for d, sen in zip(desc, out["seniority"])]
    out["is_contract"] = blob.str.contains(_CONTRACT_RX)
    # Sponsorship: explicit "no sponsor" wins; else explicit sponsor; else unknown (NaN)
    no_sp = blob.str.contains(_NO_SPONSOR_RX)
    yes_sp = blob.str.contains(_SPONSOR_RX)
    out["sponsors_visa"] = np.where(no_sp, False, np.where(yes_sp, True, np.nan))
    out["is_defense"] = blob.str.contains(_DEFENSE_RX)

    # Company-size hint: small / large / unknown. Known big employers -> large even with no
    # textual size cue (helps Priya's "large only" filter + Kenji's company-size learning).
    comp = out["company"].fillna("").astype(str).str.lower()
    known_large = comp.apply(lambda c: any(k in c for k in LARGE_COMPANIES))
    small = blob.str.contains(_SMALL_RX)
    large = blob.str.contains(_LARGE_RX) | known_large
    out["company_size"] = np.where(small & ~known_large, "small",
                                   np.where(large, "large", "unknown"))

    # Best-effort single salary figure for filtering (USD)
    out["salary_value"] = out[["salary_min", "salary_max"]].mean(axis=1)
    return out
