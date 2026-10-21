"""Default inherent-risk and control questionnaires.

Scores are 0–5 unless noted. Higher inherent answers mean more risk.
Higher control answers mean stronger mitigation.
"""

from __future__ import annotations

from typing import Dict, List, TypedDict


class Choice(TypedDict):
    label: str
    value: int


class Question(TypedDict):
    id: str
    domain: str
    prompt: str
    choices: List[Choice]
    weight: float


INHERENT_QUESTIONS: List[Question] = [
    {
        "id": "data_sensitivity",
        "domain": "Data",
        "prompt": "What is the most sensitive data this vendor will process or store?",
        "weight": 1.4,
        "choices": [
            {"label": "No personal or confidential data", "value": 0},
            {"label": "Internal business data only", "value": 2},
            {"label": "PII / customer data", "value": 4},
            {"label": "PHI, PCI, secrets, or regulated data", "value": 5},
        ],
    },
    {
        "id": "data_volume",
        "domain": "Data",
        "prompt": "Approximate volume of records the vendor will handle?",
        "weight": 0.8,
        "choices": [
            {"label": "None / not applicable", "value": 0},
            {"label": "Fewer than 1,000", "value": 1},
            {"label": "1,000 – 100,000", "value": 3},
            {"label": "More than 100,000", "value": 5},
        ],
    },
    {
        "id": "system_access",
        "domain": "Access",
        "prompt": "What access will the vendor have to SYLLC systems?",
        "weight": 1.3,
        "choices": [
            {"label": "No network or system access", "value": 0},
            {"label": "Limited SaaS / API access", "value": 2},
            {"label": "Production data or privileged APIs", "value": 4},
            {"label": "Admin, VPN, or infrastructure access", "value": 5},
        ],
    },
    {
        "id": "business_criticality",
        "domain": "Business",
        "prompt": "How critical is this vendor to operations?",
        "weight": 1.2,
        "choices": [
            {"label": "Nice-to-have / easily replaced", "value": 1},
            {"label": "Important but workarounds exist", "value": 3},
            {"label": "Core process; disruption is costly", "value": 4},
            {"label": "Mission-critical; outage stops the business", "value": 5},
        ],
    },
    {
        "id": "fourth_party",
        "domain": "Business",
        "prompt": "Does the vendor use subprocessors for this service?",
        "weight": 0.7,
        "choices": [
            {"label": "No subprocessors", "value": 0},
            {"label": "Known subprocessors, similar region", "value": 2},
            {"label": "Many subprocessors or unknown chain", "value": 4},
            {"label": "Offshore / opaque subcontracting", "value": 5},
        ],
    },
]

CONTROL_QUESTIONS: List[Question] = [
    {
        "id": "soc2_iso",
        "domain": "Assurance",
        "prompt": "Current independent assurance (SOC 2, ISO 27001, or equivalent)?",
        "weight": 1.3,
        "choices": [
            {"label": "None", "value": 0},
            {"label": "In progress / self-attestation only", "value": 2},
            {"label": "SOC 2 Type I or ISO in audit", "value": 3},
            {"label": "SOC 2 Type II or ISO 27001 current", "value": 5},
        ],
    },
    {
        "id": "encryption",
        "domain": "Security",
        "prompt": "Encryption of data in transit and at rest?",
        "weight": 1.2,
        "choices": [
            {"label": "Unknown or not encrypted", "value": 0},
            {"label": "TLS in transit only", "value": 2},
            {"label": "TLS + at-rest encryption", "value": 4},
            {"label": "TLS + at-rest + customer-managed keys option", "value": 5},
        ],
    },
    {
        "id": "identity",
        "domain": "Security",
        "prompt": "Identity controls for the service (SSO/MFA)?",
        "weight": 1.1,
        "choices": [
            {"label": "Password only", "value": 0},
            {"label": "Optional MFA", "value": 2},
            {"label": "Required MFA", "value": 4},
            {"label": "SSO (SAML/OIDC) + MFA required", "value": 5},
        ],
    },
    {
        "id": "incident_response",
        "domain": "Operations",
        "prompt": "Incident notification and response commitments?",
        "weight": 1.0,
        "choices": [
            {"label": "No documented process", "value": 0},
            {"label": "Internal process, no customer SLA", "value": 2},
            {"label": "Notify within 72 hours", "value": 4},
            {"label": "Notify within 24–48 hours with playbooks", "value": 5},
        ],
    },
    {
        "id": "privacy",
        "domain": "Privacy",
        "prompt": "Privacy / data processing terms?",
        "weight": 1.0,
        "choices": [
            {"label": "No DPA / unclear processing terms", "value": 0},
            {"label": "DPA available on request", "value": 3},
            {"label": "Signed DPA with SCCs if needed", "value": 5},
        ],
    },
    {
        "id": "bcp",
        "domain": "Resilience",
        "prompt": "Business continuity / disaster recovery?",
        "weight": 0.9,
        "choices": [
            {"label": "Unknown", "value": 0},
            {"label": "Backups only", "value": 2},
            {"label": "Documented BCP, RTO/RPO stated", "value": 4},
            {"label": "Tested BCP with evidence", "value": 5},
        ],
    },
]


def questions_by_id() -> Dict[str, Question]:
    all_qs = INHERENT_QUESTIONS + CONTROL_QUESTIONS
    return {q["id"]: q for q in all_qs}
