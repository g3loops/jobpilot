"""Capability 2 — Profile intake & skill matching.

A UserProfile captures everything the ranker needs: the resume text (for embedding and
resume generation), extracted skills, target roles, and the hard preferences/dealbreakers
that drive the filter stage. Resumes arrive as a PDF (parsed with pypdf) or pasted text.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UserProfile:
    name: str = "Candidate"
    resume_text: str = ""
    skills: list[str] = field(default_factory=list)
    target_roles: list[str] = field(default_factory=list)

    # Optional structured résumé sections (used to build a polished Word résumé).
    # If left empty, the generator derives them heuristically from resume_text.
    contact: str = ""                                    # email · phone · location · linkedin
    education: list = field(default_factory=list)        # str bullets OR {degree,school,dates,coursework}
    experience: list = field(default_factory=list)       # str bullets OR {title,company,location,dates,bullets}
    projects: list = field(default_factory=list)         # same shape as experience entries
    publications: list = field(default_factory=list)     # publication strings (e.g. Kenji)
    education_first: bool = False                         # lead the résumé with Education (new grads)
    emphasis: list[str] = field(default_factory=list)    # skills/themes the résumé+cover must LEAD
                                                         # with (e.g. Aisha -> Python/ML; Priya ->
                                                         # ML-infrastructure framing of Kafka/Spark)
    skills_first: bool = False                            # render Skills right after the summary

    # Preferences / dealbreakers (drive the hard-filter stage in ranking.py)
    locations: list[str] = field(default_factory=list)   # HARD location filter (empty => any, subject to us_only)
    preferred_locations: list[str] = field(default_factory=list)  # SOFT boost (rank these higher, don't exclude others)
    us_only: bool = False
    min_salary: float = 0.0
    exclude_industries: list[str] = field(default_factory=list)  # e.g. ["defense"]
    max_seniority: str | None = None     # cap, e.g. "mid" => no senior/staff
    min_seniority: str | None = None     # floor, e.g. "senior" => no junior
    max_years_required: int | None = None
    no_contract: bool = False
    needs_visa_sponsor: bool = False
    min_company_size: str | None = None  # "large" => exclude small/startups
    # Optional per-profile starting scoring weights (e.g. a persona that should lean harder on
    # title match). None => use ranking.DEFAULT_WEIGHTS. The adaptive learner takes over from here.
    base_weights: dict | None = None

    def profile_blob(self) -> str:
        """Text used to embed the profile (skills weighted by repetition)."""
        roles = " ".join(self.target_roles)
        skills = " ".join(self.skills * 2)  # emphasize skills in the embedding
        return f"{roles}. {skills}. {self.resume_text}".strip()


def extract_pdf_text(file_or_bytes) -> str:
    """Extract text from a PDF (path, file-like, or bytes). Returns '' on failure."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_or_bytes)
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001
        return f""  # caller falls back to pasted text
