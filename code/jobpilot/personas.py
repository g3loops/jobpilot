"""The four required test personas, encoded as UserProfiles + machine-checkable
pass-criteria. The grader also runs hidden personas, so the criteria are expressed
generically (functions over the returned top-10 frame), not hard-coded to titles.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from .profile import UserProfile


@dataclass
class Persona:
    profile: UserProfile
    # pass_criteria(top10_df) -> (passed: bool, detail: str)
    pass_criteria: Callable[[pd.DataFrame], tuple[bool, str]]


def _aisha_pass(top: pd.DataFrame) -> tuple[bool, str]:
    senior = top["seniority"].isin(["senior", "staff"]).sum()
    defense = top["is_defense"].sum()
    ok = senior == 0 and defense == 0
    return ok, f"senior/staff={senior} (want 0), defense={defense} (want 0)"


def _marcus_pass(top: pd.DataFrame) -> tuple[bool, str]:
    too_senior = (top["years_required"] >= 3).sum()
    contract = top["is_contract"].sum()
    ok = too_senior == 0 and contract == 0
    return ok, f"roles_needing_3+yrs={too_senior} (want 0), contract={contract} (want 0)"


def _priya_pass(top: pd.DataFrame) -> tuple[bool, str]:
    junior = (top["seniority"] == "junior").sum()
    small = (top["company_size"] == "small").sum()
    ok = junior == 0 and small == 0
    return ok, f"junior={junior} (want 0), tiny_startups={small} (want 0)"


def _kenji_pass(top: pd.DataFrame) -> tuple[bool, str]:
    contract = top["is_contract"].sum()
    ok = contract == 0
    return ok, f"contract={contract} (want 0); favours large/research labs"


PERSONAS: dict[str, Persona] = {
    "Aisha (Career Pivoter → ML)": Persona(
        UserProfile(
            name="Aisha",
            resume_text=("Data Analyst with 3 years at a mid-size retail company. "
                         "Built dashboards and reports in Excel and SQL; some Python and scikit-learn. "
                         "Seeking to pivot into machine learning engineering."),
            skills=["python", "sql", "pandas", "scikit-learn", "pytorch", "data analysis"],
            target_roles=["ML Engineer", "Applied Scientist", "Data Scientist"],
            locations=["remote", "san francisco", "bay area"],
            min_salary=140000, exclude_industries=["defense"],
            max_seniority="mid", max_years_required=4,
            # Career pivoter -> the résumé+cover must LEAD with Python + ML (her pass criteria),
            # surfacing scikit-learn/PyTorch ahead of her prior analytics/reporting work.
            emphasis=["Python", "machine learning", "scikit-learn", "PyTorch"],
            skills_first=True,
        ),
        _aisha_pass,
    ),
    "Marcus (New Grad · Broad)": Persona(
        UserProfile(
            name="Marcus",
            resume_text=("Recent MSBA graduate from UC Davis. Two analytics internships. "
                         "Skilled in Python, R, SQL, Tableau, PySpark and basic NLP. No full-time experience."),
            skills=["python", "r", "sql", "tableau", "spark", "nlp"],
            target_roles=["Data Analyst", "BI Analyst", "Junior Data Scientist", "Analytics Engineer"],
            locations=[], us_only=True, min_salary=80000,   # US-only via us_only; broad on city
            max_years_required=2,       # dealbreaker: No 3+ years required (excludes >2 yrs)
            no_contract=True,           # dealbreaker: No contract-only / unpaid roles
            max_seniority="mid",        # new grad: exclude Senior/Staff roles (implies 3+ yrs)
            education_first=True,       # lead the résumé with the MSBA, not work history
            # New grad with ~0 years -> lean HARD on experience-fit + seniority so entry-level
            # (0-1 yr) roles rank above 2-yr ones; title still matters for the target analyst roles.
            base_weights={"similarity": 0.30, "skills": 0.24, "title": 0.20, "salary": 0.03,
                          "seniority": 0.08, "location": 0.03, "experience": 0.12, "company_size": 0.0},
        ),
        _marcus_pass,
    ),
    "Priya (Experienced · Niche)": Persona(
        UserProfile(
            name="Priya",
            resume_text=("Senior Software Engineer, 7 years in fintech. Java, Python, Kubernetes, "
                         "microservices, Kafka, Spark, some TensorFlow. AWS certified. "
                         "Moving into ML/AI infrastructure."),
            skills=["java", "python", "kubernetes", "microservices", "kafka", "spark", "tensorflow", "aws"],
            target_roles=["ML Platform Engineer", "MLOps Engineer", "Senior ML Engineer"],
            # Hard geo rule is US-only; NY + remote are PREFERENCES (rank higher) but other US
            # locations now qualify too — "open up options if the dealbreakers match".
            locations=[], preferred_locations=["new york", "nyc", "remote"],
            us_only=True, min_salary=200000,
            min_seniority="senior",          # dealbreaker: No Junior titles
            min_company_size="large",        # dealbreaker: no <100-employee / tiny startups
            # Pivoting INTO ML -> lean harder on TITLE so ML-role titles (ML Platform / MLOps /
            # Senior ML Engineer) rank above generic senior-engineer roles that merely match skills.
            base_weights={"similarity": 0.32, "skills": 0.22, "title": 0.34, "salary": 0.03,
                          "seniority": 0.04, "location": 0.05, "company_size": 0.0},
            # Moving into ML/AI infra -> frame Kafka/Spark/Kubernetes as ML-platform / MLOps
            # infrastructure (feature pipelines, model serving, distributed training), NOT
            # generic backend, and lead with that on the résumé + cover.
            emphasis=["ML infrastructure", "MLOps", "Kafka", "Spark", "Kubernetes"],
        ),
        _priya_pass,
    ),
    "Kenji (International · Visa)": Persona(
        UserProfile(
            name="Kenji",
            resume_text=("MS Computer Science, graduating. Python, C++, deep learning with PyTorch, "
                         "NLP and computer vision. Published research papers. On OPT, needs H-1B sponsorship."),
            skills=["python", "c++", "deep learning", "pytorch", "nlp", "computer vision"],
            target_roles=["Research Scientist", "ML Engineer", "Applied Scientist", "AI Engineer"],
            locations=["us"], us_only=True, min_salary=120000,
            no_contract=True, needs_visa_sponsor=True,
            publications=[
                "Kim, K. et al. \"Attention-Guided Feature Fusion for Low-Resource NLP.\" ACL 2025.",
                "Kim, K. et al. \"Robust Visual Grounding under Domain Shift.\" CVPR 2024.",
            ],
        ),
        _kenji_pass,
    ),
}
