from datetime import date

import pytest

from app import db
from app.documents import (
    checklist,
    default_expiry,
    doc_status,
    evidence_gaps,
    required_doc_types,
    safe_filename,
    validate_upload,
)

TODAY = date(2026, 6, 1)


def test_baseline_request_without_answers():
    assert required_doc_types() == ["soc2_report", "security_policy"]


def test_high_risk_vendor_gets_more_requests():
    req = required_doc_types(
        {"data_sensitivity": 5, "system_access": 5, "business_criticality": 5}
    )
    for t in ["dpa", "pentest_summary", "bcp_dr_plan", "insurance_certificate", "incident_response_plan"]:
        assert t in req
    assert len(req) == len(set(req))


def test_safe_filename_strips_paths_and_odd_chars():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\x\\SOC 2 (final).pdf") == "SOC_2_final_.pdf"
    assert safe_filename("...") == "document"


def test_validate_upload():
    assert validate_upload("report.pdf", b"%PDF-1.7 ...") == []
    assert validate_upload("report.exe", b"MZ")  # disallowed type
    assert validate_upload("report.pdf", b"")  # empty
    assert validate_upload("report.pdf", b"<html>")  # wrong content
    assert validate_upload("notes.txt", b"hello") == []


def test_expiry_and_status():
    assert default_expiry("dpa", TODAY) is None
    assert default_expiry("soc2_report", None) is None
    assert default_expiry("soc2_report", date(2026, 1, 1)) == date(2026, 12, 27)
    assert doc_status(None, TODAY) == "Current"
    assert doc_status("2026-05-01", TODAY) == "Expired"
    assert doc_status("2026-06-15", TODAY) == "Expiring soon"
    assert doc_status("2027-01-01", TODAY) == "Current"


def test_checklist_picks_best_status():
    docs = [
        {"doc_type": "soc2_report", "expires_on": "2025-01-01"},
        {"doc_type": "soc2_report", "expires_on": "2027-01-01"},
    ]
    rows = {r["doc_type"]: r["status"] for r in checklist(["soc2_report", "dpa"], docs, TODAY)}
    assert rows == {"soc2_report": "Current", "dpa": "Missing"}


def test_strong_claims_without_evidence_are_flagged():
    answers = {"soc2_iso": 5, "privacy": 5, "bcp": 2}
    gaps = evidence_gaps(answers, [], TODAY)
    assert {g["question_id"] for g in gaps} == {"soc2_iso", "privacy"}

    docs = [{"doc_type": "soc2_report", "expires_on": "2027-01-01"}, {"doc_type": "dpa", "expires_on": None}]
    assert evidence_gaps(answers, docs, TODAY) == []

    expired = [{"doc_type": "soc2_report", "expires_on": "2025-01-01"}]
    assert "soc2_iso" in {g["question_id"] for g in evidence_gaps(answers, expired, TODAY)}


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "vra.db")
    monkeypatch.setattr(db, "DOCS_DIR", tmp_path / "documents")
    return tmp_path


def test_document_round_trip(tmp_db):
    vid = db.add_vendor("Acme", "SaaS", "Sec")
    doc_id = db.add_document(vid, "soc2_report", "../SOC2.pdf", b"%PDF-1.7 body", "application/pdf",
                             issued_on="2026-01-01", expires_on="2026-12-27")
    doc = db.get_document(doc_id)
    path = db.document_path(doc)
    assert path.parent == tmp_db / "documents" / str(vid)
    assert path.exists()
    assert db.read_document(doc_id) == b"%PDF-1.7 body"
    assert len(doc["sha256"]) == 64
    assert [d["id"] for d in db.list_documents(vid)] == [doc_id]

    assert db.delete_document(doc_id)
    assert not path.exists()
    assert db.list_documents(vid) == []


def test_assessment_stores_evidence(tmp_db):
    vid = db.add_vendor("Acme", "SaaS", "Sec")
    aid = db.save_assessment(vid, {"data_sensitivity": 5}, {"tier": "Low", "review_months": 36},
                             evidence={"outstanding": ["dpa"]})
    assert '"dpa"' in db.get_assessment(aid)["evidence_json"]
    assert db.latest_answers(vid) == {"data_sensitivity": 5}
