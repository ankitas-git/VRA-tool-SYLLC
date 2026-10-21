"""Weighted inherent / control / residual scoring."""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from app.questionnaire import CONTROL_QUESTIONS, INHERENT_QUESTIONS, Question

MAX_ANSWER = 5.0

TIER_BANDS: List[Tuple[str, float]] = [
    ("Critical", 4.0),
    ("High", 3.0),
    ("Moderate", 2.0),
    ("Low", 0.0),
]

REVIEW_MONTHS = {
    "Critical": 6,
    "High": 12,
    "Moderate": 24,
    "Low": 36,
}

DECISION = {
    "Critical": "Escalate — do not approve without compensating controls or exec sign-off.",
    "High": "Conditional approve — require remediation plan and 12-month reassessment.",
    "Moderate": "Approve with standard monitoring.",
    "Low": "Approve — lightweight periodic review.",
}


def _weighted_mean(questions: Iterable[Question], answers: Dict[str, int]) -> float:
    total_w = 0.0
    acc = 0.0
    for q in questions:
        if q["id"] not in answers:
            continue
        w = float(q["weight"])
        acc += (answers[q["id"]] / MAX_ANSWER) * w
        total_w += w
    if total_w == 0:
        return 0.0
    return (acc / total_w) * MAX_ANSWER


def inherent_score(answers: Dict[str, int]) -> float:
    return round(_weighted_mean(INHERENT_QUESTIONS, answers), 2)


def control_score(answers: Dict[str, int]) -> float:
    return round(_weighted_mean(CONTROL_QUESTIONS, answers), 2)


def residual_score(inherent: float, control: float) -> float:
    """Residual stays high when inherent is high and controls are weak."""
    effectiveness = control / MAX_ANSWER
    residual = inherent * (1.0 - 0.75 * effectiveness)
    return round(min(MAX_ANSWER, max(0.0, residual)), 2)


def tier_for(score: float) -> str:
    for name, floor in TIER_BANDS:
        if score >= floor:
            return name
    return "Low"


def domain_breakdown(answers: Dict[str, int]) -> Dict[str, float]:
    buckets: Dict[str, List[Question]] = {}
    for q in list(INHERENT_QUESTIONS) + list(CONTROL_QUESTIONS):
        buckets.setdefault(q["domain"], []).append(q)
    out: Dict[str, float] = {}
    for domain, qs in buckets.items():
        out[domain] = round(_weighted_mean(qs, answers), 2)
    return out


def score_assessment(answers: Dict[str, int]) -> Dict[str, object]:
    inherent = inherent_score(answers)
    control = control_score(answers)
    residual = residual_score(inherent, control)
    tier = tier_for(residual)
    return {
        "inherent": inherent,
        "control": control,
        "residual": residual,
        "tier": tier,
        "review_months": REVIEW_MONTHS[tier],
        "recommendation": DECISION[tier],
        "domains": domain_breakdown(answers),
    }
