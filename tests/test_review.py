import io
import json
from types import SimpleNamespace

import pytest

from app import db
from app.extract import extract_text
from app.questionnaire_admin import diff_questions
from app.review import (
    ANSWERED,
    NOT_ANSWERED,
    NOT_REVIEWED,
    PARTIAL,
    build_document_blocks,
    claude_review,
    follow_up_request,
    keyword_review,
    summarize,
)

Q = [
    {"id": 1, "section": "Gov", "text": "Do you have a documented information security policy?",
     "keywords": "information security policy, security policy, scope", "requires_document": 1},
    {"id": 2, "section": "Gov", "text": "Is the policy reviewed at least once a year?",
     "keywords": "reviewed annually, annual review, last reviewed", "requires_document": 0},
    {"id": 3, "section": "BCP", "text": "How often is the DR plan tested?",
     "keywords": "dr test, failover, tabletop", "requires_document": 1},
]

POLICY = (
    "Information Security Policy\n\nScope: this information security policy applies to all staff. "
    "The security policy is owned by the CISO.\n\nThe policy is reviewed annually by the security "
    "committee. Last reviewed: March 2026."
)


def doc(name, text, data=b"x", label="Information security policy"):
    return {"id": 1, "name": name, "doc_type_label": label, "data": data, "text": text, "note": ""}


# --- extraction ---------------------------------------------------------------

def test_extract_docx_xlsx_csv_txt():
    import docx
    from openpyxl import Workbook

    d = docx.Document()
    d.add_paragraph("Backups run nightly.")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "RTO"
    t.rows[0].cells[1].text = "4 hours"
    buf = io.BytesIO()
    d.save(buf)
    text, note = extract_text("bcp.docx", buf.getvalue())
    assert "Backups run nightly." in text and "RTO | 4 hours" in text and note == ""

    wb = Workbook()
    wb.active.append(["Control", "Answer"])
    wb.active.append(["MFA", "Required"])
    buf = io.BytesIO()
    wb.save(buf)
    text, _ = extract_text("sig.xlsx", buf.getvalue())
    assert "MFA | Required" in text

    assert extract_text("a.csv", b"a,b\n1,2")[0] == "a | b\n1 | 2"
    assert extract_text("a.txt", b"hello")[0] == "hello"
    assert extract_text("a.png", b"\x89PNG")[0] == ""
    assert "Legacy" in extract_text("a.doc", b"\xd0\xcf")[1]
    assert "Could not read" in extract_text("bad.docx", b"PK\x03\x04junk")[1]


# --- keyword scan -------------------------------------------------------------

def test_keyword_review_statuses_and_evidence():
    results, notes = keyword_review(Q, [doc("policy.txt", POLICY)])
    by = {r["question_id"]: r for r in results}
    assert by[1]["status"] == ANSWERED
    assert by[1]["evidence"][0]["document"] == "policy.txt"
    assert by[2]["status"] in (ANSWERED, PARTIAL)
    assert by[3]["status"] == NOT_ANSWERED
    assert "cannot tell" in notes[0]


def test_keyword_review_notes_unreadable_docs():
    results, notes = keyword_review(Q, [doc("scan.png", "", label="Other")])
    assert all(r["status"] == NOT_ANSWERED for r in results)
    assert any("scan.png" in n for n in notes)


def test_summary_and_follow_up():
    results, _ = keyword_review(Q, [doc("policy.txt", POLICY)])
    s = summarize(results)
    assert s["total"] == 3
    assert sum(s["counts"].values()) == 3
    assert 0 < s["coverage_pct"] < 100
    text = follow_up_request("Acme", results)
    assert "How often is the DR plan tested?" in text
    assert "## BCP" in text


# --- Claude review (fake client) ----------------------------------------------

class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    """Answers every question it is asked about, except id 3."""

    def __init__(self, with_fallback=False):
        self.calls = []
        self.with_fallback = with_fallback
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"][-1]["text"]
        qs = json.loads(prompt[prompt.index("["):])
        results = [
            {"question_id": q["question_id"], "status": ANSWERED, "answer": "Yes.",
             "evidence": [{"document": "policy.pdf", "excerpt": "reviewed annually"}],
             "missing": "", "follow_up": ""}
            for q in qs if q["question_id"] != 3
        ]
        content = []
        if self.with_fallback:
            content += [SimpleNamespace(type="text", text='{"partial'), SimpleNamespace(type="fallback")]
        content.append(SimpleNamespace(type="text", text=json.dumps({"results": results})))
        return FakeStream(SimpleNamespace(content=content, stop_reason="end_turn"))


def test_claude_review_request_shape_and_results():
    client = FakeClient()
    docs = [doc("policy.pdf", "", data=b"%PDF-1.7"), doc("notes.txt", POLICY), doc("old.doc", "")]
    results, notes = claude_review(Q, docs, client=client, model="m", effort="high")
    call = client.calls[0]
    assert call["model"] == "m"
    assert call["fallbacks"] == "default"
    assert call["output_config"]["format"]["type"] == "json_schema"
    blocks = call["messages"][0]["content"]
    assert blocks[0]["source"]["media_type"] == "application/pdf"
    assert blocks[1]["source"]["type"] == "text"
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}  # last document block is cached
    assert any("old.doc" in n for n in notes)
    by = {r["question_id"]: r for r in results}
    assert by[1]["status"] == ANSWERED and by[1]["evidence"][0]["excerpt"] == "reviewed annually"
    assert by[3]["status"] == NOT_REVIEWED  # model skipped it


def test_claude_review_batches_and_fallback_text():
    many = [dict(Q[0], id=i, text=f"Question {i}") for i in range(10, 55)]
    client = FakeClient(with_fallback=True)
    results, _ = claude_review(many, [doc("p.txt", POLICY)], client=client, model="m", effort="high")
    assert len(client.calls) == 3  # 45 questions in batches of 20
    assert [r["question_id"] for r in results] == [q["id"] for q in many]
    assert all(r["status"] == ANSWERED for r in results)


def test_document_blocks_size_limit(monkeypatch):
    import app.review as review

    monkeypatch.setattr(review, "MAX_REQUEST_BYTES", 100)
    with pytest.raises(review.ReviewError):
        build_document_blocks([doc("big.txt", "x" * 500)])


# --- admin diff ---------------------------------------------------------------

def test_diff_questions():
    orig = [
        {"id": 1, "section": "A", "text": "Q1", "keywords": "", "guidance": "", "requires_document": 0, "sort_order": 10, "active": 1},
        {"id": 2, "section": "A", "text": "Q2", "keywords": "", "guidance": "", "requires_document": 0, "sort_order": 20, "active": 1},
    ]
    edited = [
        {**orig[0], "text": "Q1 edited", "active": False},
        {"id": None, "section": "B", "text": "New", "requires_document": True},
        {"id": None, "section": None, "text": None},  # blank row ignored
    ]
    adds, updates, deletes = diff_questions(orig, edited)
    assert adds == [{"section": "B", "text": "New", "keywords": "", "guidance": "", "requires_document": 1, "active": 1}]
    assert updates == [(1, {"text": "Q1 edited", "active": 0})]
    assert deletes == [2]
    with pytest.raises(ValueError):
        diff_questions(orig, [{"id": None, "section": "B", "text": ""}])


# --- questionnaire storage ----------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "vra.db")
    monkeypatch.setattr(db, "DOCS_DIR", tmp_path / "documents")
    return tmp_path


def test_questionnaire_seeded_once_and_editable(tmp_db):
    qs = db.list_questions()
    assert len(qs) == 67
    assert qs[0]["text"].startswith("Do you have a documented information security policy?")
    assert qs[0]["requires_document"] == 1

    db.delete_question(qs[0]["id"])
    assert len(db.list_questions()) == 66  # not re-seeded on next connect

    assert db.update_question(qs[1]["id"], {"text": "Reviewed yearly?", "active": 0})
    assert not db.update_question(qs[1]["id"], {"text": "Reviewed yearly?"})  # no-op
    assert len(db.list_questions()) == 65
    assert len(db.list_questions(active_only=False)) == 66

    new_id = db.add_question({"section": "Custom", "text": "Do you use AI tools?"})
    assert db.list_questions()[-1]["id"] == new_id

    actions = [c["action"] for c in db.list_question_changes()]
    assert actions == ["add", "update", "delete"]

    db.reset_questionnaire()
    assert len(db.list_questions()) == 67
    assert db.replace_questionnaire([{"section": "S", "text": "Please attach X."}]) == 1
    assert db.list_questions()[0]["requires_document"] == 1


def test_review_round_trip(tmp_db):
    vid = db.add_vendor("Acme", "SaaS", "Sec")
    results, notes = keyword_review(Q, [doc("policy.txt", POLICY)])
    rid = db.save_review(vid, "keyword", None, [1], results, summarize(results), notes)
    r = db.latest_review(vid)
    assert r["id"] == rid and r["results"] == results and r["documents"] == [1]
