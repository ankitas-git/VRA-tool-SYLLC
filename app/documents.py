"""Security document catalog, request rules, upload validation, and evidence checks.

Everything here is pure (no Streamlit, no SQLite) so it can be unit-tested.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import PurePath
from typing import Dict, Iterable, List, Mapping, Optional, TypedDict


class DocType(TypedDict):
    id: str
    label: str
    description: str
    validity_months: Optional[int]  # None = does not expire


DOC_TYPES: List[DocType] = [
    {
        "id": "soc2_report",
        "label": "SOC 2 Type II report",
        "description": "Most recent SOC 2 Type II report, or a bridge letter if the period has ended.",
        "validity_months": 12,
    },
    {
        "id": "iso27001_cert",
        "label": "ISO 27001 certificate",
        "description": "Current ISO/IEC 27001 certificate and Statement of Applicability.",
        "validity_months": 36,
    },
    {
        "id": "security_policy",
        "label": "Information security policy",
        "description": "Security program overview, covering access control and encryption.",
        "validity_months": 12,
    },
    {
        "id": "pentest_summary",
        "label": "Penetration test summary",
        "description": "Executive summary of a third-party penetration test from the last 12 months.",
        "validity_months": 12,
    },
    {
        "id": "incident_response_plan",
        "label": "Incident response plan",
        "description": "Incident response policy or plan with customer notification commitments.",
        "validity_months": 12,
    },
    {
        "id": "dpa",
        "label": "Data processing agreement (DPA)",
        "description": "Signed DPA, with SCCs where cross-border transfers apply.",
        "validity_months": None,
    },
    {
        "id": "bcp_dr_plan",
        "label": "Business continuity / DR plan",
        "description": "BCP/DR plan with stated RTO/RPO and evidence of the latest test.",
        "validity_months": 12,
    },
    {
        "id": "insurance_certificate",
        "label": "Cyber insurance certificate",
        "description": "Certificate of insurance showing cyber / tech E&O coverage.",
        "validity_months": 12,
    },
    {
        "id": "security_questionnaire",
        "label": "Completed security questionnaire",
        "description": "Vendor-completed SIG Lite, CAIQ, or equivalent questionnaire.",
        "validity_months": 12,
    },
    {
        "id": "other",
        "label": "Other",
        "description": "Any other supporting security evidence.",
        "validity_months": None,
    },
]

DOC_TYPES_BY_ID: Dict[str, DocType] = {d["id"]: d for d in DOC_TYPES}

# Control question id -> document types that substantiate a strong answer.
CONTROL_EVIDENCE: Dict[str, List[str]] = {
    "soc2_iso": ["soc2_report", "iso27001_cert"],
    "encryption": ["soc2_report", "iso27001_cert", "security_policy", "pentest_summary"],
    "identity": ["soc2_report", "iso27001_cert", "security_policy"],
    "incident_response": ["incident_response_plan", "soc2_report"],
    "privacy": ["dpa"],
    "bcp": ["bcp_dr_plan"],
}

# Control answers at or above this value are claims that need a document behind them.
STRONG_CLAIM_THRESHOLD = 4

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".txt", ".png", ".jpg", ".jpeg"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
EXPIRING_SOON_DAYS = 30

# Leading bytes expected for binary formats; a mismatch suggests a renamed file.
_MAGIC = {
    ".pdf": [b"%PDF"],
    ".png": [b"\x89PNG"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".docx": [b"PK\x03\x04"],
    ".xlsx": [b"PK\x03\x04"],
    ".doc": [b"\xd0\xcf\x11\xe0"],
    ".xls": [b"\xd0\xcf\x11\xe0"],
}


def required_doc_types(inherent_answers: Optional[Mapping[str, int]] = None) -> List[str]:
    """Which documents to request from a vendor, given its inherent-risk answers.

    With no answers yet, return the baseline that every vendor is asked for.
    """
    a = dict(inherent_answers or {})
    required = ["soc2_report", "security_policy"]
    sensitivity = a.get("data_sensitivity", 0)
    access = a.get("system_access", 0)
    criticality = a.get("business_criticality", 0)

    if sensitivity >= 2:
        required.append("incident_response_plan")
    if sensitivity >= 4:
        required.append("dpa")
    if sensitivity >= 4 or access >= 4:
        required += ["pentest_summary", "security_questionnaire"]
    if criticality >= 4:
        required.append("bcp_dr_plan")
    if sensitivity >= 5 or access >= 5:
        required.append("insurance_certificate")
    # De-duplicate, keep catalog order.
    order = [d["id"] for d in DOC_TYPES]
    return sorted(set(required), key=order.index)


def safe_filename(name: str) -> str:
    """Strip any path and reduce to a conservative character set."""
    base = PurePath(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return base[:120] or "document"


def validate_upload(filename: str, data: bytes) -> List[str]:
    """Return a list of problems; empty means the upload is acceptable."""
    errors: List[str] = []
    ext = PurePath(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        errors.append(
            f"File type '{ext or 'none'}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )
    if len(data) == 0:
        errors.append("File is empty.")
    elif len(data) > MAX_UPLOAD_BYTES:
        errors.append(f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    magics = _MAGIC.get(ext)
    if magics and data and not any(data.startswith(m) for m in magics):
        errors.append(f"File content does not look like a valid {ext} file.")
    return errors


def default_expiry(doc_type: str, issued: Optional[date]) -> Optional[date]:
    months = DOC_TYPES_BY_ID.get(doc_type, {}).get("validity_months")
    if not months or issued is None:
        return None
    return issued + timedelta(days=int(months) * 30)


def doc_status(expires_on: Optional[str], today: Optional[date] = None) -> str:
    """'Current', 'Expiring soon', or 'Expired' for an ISO date string (or None)."""
    if not expires_on:
        return "Current"
    today = today or date.today()
    exp = date.fromisoformat(expires_on)
    if exp < today:
        return "Expired"
    if exp <= today + timedelta(days=EXPIRING_SOON_DAYS):
        return "Expiring soon"
    return "Current"


def current_doc_types(documents: Iterable[Mapping[str, object]], today: Optional[date] = None) -> set:
    """Doc types with at least one non-expired document on file."""
    return {
        str(d["doc_type"])
        for d in documents
        if doc_status(d.get("expires_on"), today) != "Expired"  # type: ignore[arg-type]
    }


def checklist(
    required: Iterable[str],
    documents: Iterable[Mapping[str, object]],
    today: Optional[date] = None,
) -> List[Dict[str, str]]:
    """One row per requested doc type with its best status."""
    docs = list(documents)
    rank = {"Current": 0, "Expiring soon": 1, "Expired": 2}
    rows = []
    for dt in required:
        statuses = [
            doc_status(d.get("expires_on"), today)  # type: ignore[arg-type]
            for d in docs
            if d["doc_type"] == dt
        ]
        status = min(statuses, key=rank.__getitem__) if statuses else "Missing"
        rows.append({"doc_type": dt, "document": DOC_TYPES_BY_ID[dt]["label"], "status": status})
    return rows


def evidence_gaps(
    control_answers: Mapping[str, int],
    documents: Iterable[Mapping[str, object]],
    today: Optional[date] = None,
) -> List[Dict[str, object]]:
    """Strong control claims with no current supporting document on file."""
    have = current_doc_types(documents, today)
    gaps = []
    for qid, accepted in CONTROL_EVIDENCE.items():
        value = control_answers.get(qid)
        if value is None or value < STRONG_CLAIM_THRESHOLD:
            continue
        if not have.intersection(accepted):
            gaps.append(
                {
                    "question_id": qid,
                    "answer": value,
                    "needs_one_of": [DOC_TYPES_BY_ID[d]["label"] for d in accepted],
                }
            )
    return gaps
