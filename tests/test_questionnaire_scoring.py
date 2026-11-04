import io
import shutil
import subprocess

import pytest

from app import db
from app.company_questionnaire import DEFAULT_QUESTIONS, NIST_FUNCTIONS
from app.questionnaire_scoring import (
    SATISFACTORY,
    UNSATISFACTORY,
    review_items,
    score_questionnaire,
    score_review,
    suggested_response,
)
from app.workbook import WorkbookError, read_questionnaire, write_scored_workbook

QS = [
    {"id": 1, "section": "Policies", "nist_function": "Govern", "weight": 1.0},
    {"id": 2, "section": "Policies", "nist_function": "Govern", "weight": 0.3},
    {"id": 3, "section": "Access", "nist_function": "Protect", "weight": 0.5},
    {"id": 4, "section": "Access", "nist_function": "Protect", "weight": 0.0},  # asked, not scored
    {"id": 5, "section": "DR", "nist_function": "Recover", "weight": 0.4},
]


def by_name(groups):
    return {g["name"]: g for g in groups}


# --- the formula --------------------------------------------------------------

def test_workbook_formula():
    resp = {1: SATISFACTORY, 2: UNSATISFACTORY, 3: SATISFACTORY, 4: UNSATISFACTORY}  # 5 unanswered
    s = score_questionnaire(QS, resp)
    # Actual = 1.0 + 0.5 ; Possible = 1.0 + 0.3 + 0.5 + 0 + 0.4
    assert s["actual"] == 1.5 and s["possible"] == 2.2
    assert s["overall"] == round(1.5 / 2.2, 4)
    nist = by_name(s["by_nist_function"])
    assert nist["Govern"]["score"] == round(1.0 / 1.3, 4)
    assert nist["Protect"]["score"] == 1.0  # zero-weight question doesn't count against it
    assert nist["Recover"]["score"] == 0.0  # missing response = Unsatisfactory
    assert [g["name"] for g in s["by_nist_function"]] == ["Govern", "Protect", "Recover"]  # NIST order
    assert by_name(s["by_control_area"])["Policies"]["score"] == round(1.0 / 1.3, 4)


def test_all_satisfactory_is_100_and_none_is_0():
    assert score_questionnaire(QS, {q["id"]: SATISFACTORY for q in QS})["overall"] == 1.0
    assert score_questionnaire(QS, {})["overall"] == 0.0
    s = score_questionnaire([{"id": 1, "section": "X", "nist_function": "Govern", "weight": 0}], {1: SATISFACTORY})
    assert s["overall"] is None  # nothing weighted: the workbook would show #DIV/0!


def test_suggested_response():
    assert suggested_response("Answered") == SATISFACTORY
    for status in ("Partially answered", "Not answered", "Not reviewed"):
        assert suggested_response(status) == UNSATISFACTORY


def test_default_questionnaire_matches_workbook():
    assert len(DEFAULT_QUESTIONS) == 67
    assert round(sum(q[2] for q in DEFAULT_QUESTIONS), 2) == 30.1
    assert all(q[1] in NIST_FUNCTIONS and 0 < q[2] <= 1 for q in DEFAULT_QUESTIONS)
    first = DEFAULT_QUESTIONS[0]
    assert first[:3] == ("Information Security Policies", "Govern", 1)
    assert len({q[0] for q in DEFAULT_QUESTIONS}) == 14


# --- workbook in / out ----------------------------------------------------------

def items():
    return [
        {"control_area": q["section"], "nist_function": q["nist_function"], "question": f"Question {q['id']}?",
         "weight": q["weight"], "response": SATISFACTORY if q["id"] in (1, 3) else UNSATISFACTORY,
         "review_status": "Answered"}
        for q in QS
    ]


def test_scored_workbook_round_trip():
    from openpyxl import load_workbook

    data = write_scored_workbook("Acme Vendor Risk Assessment", items())
    wb = load_workbook(io.BytesIO(data))
    q = wb["Questionnaire"]
    assert q["F2"].value == '=IF(D2="Satisfactory",1*E2,0)' and q["G2"].value == "=E2"
    assert q["F7"].value == "=SUM(F2:F6)"
    assert "SUMIF(Questionnaire!B:B" in wb["Results"]["C6"].value
    rows = read_questionnaire(data)
    assert [(r["section"], r["nist_function"], r["weight"], r["response"]) for r in rows] == [
        (i["control_area"], i["nist_function"], i["weight"], i["response"]) for i in items()
    ]


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
def test_exported_formulas_recalculate_to_our_score(tmp_path):
    from openpyxl import load_workbook

    src = tmp_path / "scored.xlsx"
    src.write_bytes(write_scored_workbook("Acme", items()))
    subprocess.run(["soffice", "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(tmp_path / "out"),
                    str(src)], check=True, capture_output=True, timeout=120)
    res = load_workbook(tmp_path / "out" / "scored.xlsx", data_only=True)["Results"]
    ours = score_questionnaire(QS, {1: SATISFACTORY, 3: SATISFACTORY})
    assert res["A3"].value == pytest.approx(ours["overall"], abs=1e-4)
    excel_nist = {res.cell(r, 2).value: res.cell(r, 3).value for r in range(6, 12)}
    for g in ours["by_nist_function"]:
        assert excel_nist[g["name"]] == pytest.approx(g["score"], abs=1e-4)
    assert excel_nist["Identify"] == "n/a"  # no questions -> no score


def test_read_workbook_template_layout():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Questionnaire"
    ws.append(["Control Area", "NIST Function", "Question", "Response", "Weight (standard is 30%)",
               "Actual Score", "Possible Score"])
    ws.append(["Compliance", "Govern", "Do you hold a SOC 2?", "Satisfactory", 0.8, "=1", "=1"])
    ws.append(["HR", "Protect", None, None, None])  # spacer row: skipped
    ws.append(["Compliance", "Govern", "Please attach the SOC 2 report.", "Satisfactory", None])  # blank weight
    buf = io.BytesIO()
    wb.save(buf)
    rows = read_questionnaire(buf.getvalue())
    assert [(r["text"], r["weight"]) for r in rows] == [("Do you hold a SOC 2?", 0.8),
                                                         ("Please attach the SOC 2 report.", 0)]
    ws.append(["X", "Prevent", "Bad function?", None, 0.3])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(WorkbookError):
        read_questionnaire(buf.getvalue())
    with pytest.raises(WorkbookError):
        read_questionnaire(b"not a workbook")


# --- storage ------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "vra.db")
    monkeypatch.setattr(db, "DOCS_DIR", tmp_path / "documents")
    return tmp_path


def test_seeded_questions_carry_weights(tmp_db):
    qs = db.list_questions()
    assert round(sum(q["weight"] for q in qs), 2) == 30.1
    assert qs[0]["nist_function"] == "Govern" and qs[0]["section"] == "Information Security Policies"


def test_backfill_upgrades_v1_questionnaire(tmp_db):
    db.list_questions()
    with db.connect() as conn:  # make it look like a database from before weights existed
        conn.execute("UPDATE questionnaire_questions SET weight = 0.3, nist_function = '', section = 'Governance & Policy'")
        conn.execute("UPDATE questionnaire_questions SET section = 'My renamed area' WHERE id = 2")
        conn.execute("UPDATE questionnaire_questions SET text = 'Reworded by admin?' WHERE id = 3")
        conn.execute("DELETE FROM meta WHERE key = 'questionnaire_weights_v2'")
    qs = {q["id"]: q for q in db.list_questions()}
    assert (qs[1]["weight"], qs[1]["nist_function"], qs[1]["section"]) == (1.0, "Govern", "Information Security Policies")
    assert qs[2]["section"] == "My renamed area" and qs[2]["weight"] == 0.3  # admin's section kept
    assert qs[3]["weight"] == 0.3 and qs[3]["nist_function"] == ""  # reworded: untouched


def test_weight_validation_and_import(tmp_db):
    assert db.parse_weight("30%") == 0.3 and db.parse_weight("") == 0.0 and db.parse_weight(1) == 1.0
    for bad in (1.5, -0.1, "lots"):
        with pytest.raises(ValueError):
            db.parse_weight(bad)
    qid = db.add_question({"section": "New", "text": "Do you use AI?"})
    assert db.list_questions()[-1]["weight"] == 0.3  # standard weight for new questions
    with pytest.raises(ValueError):
        db.update_question(qid, {"nist_function": "Prevent"})
    db.replace_questionnaire([
        {"section": "A", "text": "Q1?", "nist_function": "govern", "weight": "0.8"},
        {"section": "A", "text": "Q2?", "weight": ""},
    ])
    assert [(q["nist_function"], q["weight"]) for q in db.list_questions()] == [("Govern", 0.8), ("", 0.0)]


def test_review_responses_and_score(tmp_db):
    from app.review import manual_results, summarize

    vid = db.add_vendor("Acme", "SaaS", "Sec")
    qs = db.list_questions()
    results = manual_results(qs)
    results[0]["status"] = "Answered"
    rid = db.save_review(vid, "manual", None, [], results, summarize(results), [])
    review = db.latest_review(vid)
    assert review["responses"][qs[0]["id"]] == SATISFACTORY
    assert score_review(review)["overall"] == round(1.0 / 30.1, 4)

    db.update_review_responses(rid, {q["id"]: SATISFACTORY for q in qs})
    assert score_review(db.latest_review(vid))["overall"] == 1.0
    with pytest.raises(ValueError):
        db.update_review_responses(rid, {qs[0]["id"]: "Maybe"})

    # Later weight edits don't change a saved review's score.
    db.update_question(qs[0]["id"], {"weight": 0.1})
    assert score_review(db.latest_review(vid), db.list_questions())["possible"] == 30.1


def test_old_review_without_weights_uses_current_questionnaire():
    review = {"results": [{"question_id": 7, "section": "A", "question": "Q?", "status": "Answered"}],
              "responses": {}}
    rows = review_items(review, [{"id": 7, "weight": 0.8, "nist_function": "Detect"}])
    assert rows[0]["weight"] == 0.8 and rows[0]["nist_function"] == "Detect"
    assert rows[0]["response"] == SATISFACTORY
