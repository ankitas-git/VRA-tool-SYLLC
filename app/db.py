"""SQLite persistence for vendors and assessments."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "vra.db"
DOCS_DIR = DATA_DIR / "documents"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    answers_json TEXT NOT NULL DEFAULT '{}',
    inherent REAL,
    control REAL,
    residual REAL,
    tier TEXT,
    review_months INTEGER,
    recommendation TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES vendors(id)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL,
    doc_type TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    issued_on TEXT,
    expires_on TEXT,
    notes TEXT NOT NULL DEFAULT '',
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES vendors(id)
);
"""

SCHEMA += """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questionnaire_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section TEXT NOT NULL,
    text TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    guidance TEXT NOT NULL DEFAULT '',
    requires_document INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS questionnaire_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    changed_by TEXT NOT NULL DEFAULT 'admin',
    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS document_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL,
    method TEXT NOT NULL,
    model TEXT,
    document_ids_json TEXT NOT NULL DEFAULT '[]',
    results_json TEXT NOT NULL DEFAULT '[]',
    summary_json TEXT NOT NULL DEFAULT '{}',
    notes_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES vendors(id)
);
"""

# Columns added after the first release; applied to existing databases on connect.
MIGRATIONS = [
    ("assessments", "evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("questionnaire_questions", "weight", "REAL NOT NULL DEFAULT 0.3"),
    ("questionnaire_questions", "nist_function", "TEXT NOT NULL DEFAULT ''"),
    ("document_reviews", "responses_json", "TEXT NOT NULL DEFAULT '{}'"),
]

# Section names used by the first release of the default questionnaire, before
# it was aligned with the scoring workbook's control areas.
_V1_SECTIONS = {
    "Governance & Policy", "Certifications & Assurance", "Human Resources Security",
    "Asset Management", "Access Control", "Cryptography", "Physical & Environmental Security",
    "Operations Security", "Incident Response", "Network Security",
    "Application Security & SDLC", "Business Continuity & DR", "Supplier Management",
}


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, column, decl in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    _seed_questionnaire(conn)
    _backfill_weights(conn)
    return conn


def _seed_questionnaire(conn: sqlite3.Connection) -> None:
    """Copy the default questionnaire into the database once.

    Seeding is recorded in `meta`, so an admin who deletes questions does not
    get them back on the next start.
    """
    if conn.execute("SELECT 1 FROM meta WHERE key = 'questionnaire_seeded'").fetchone():
        return
    _insert_default_questions(conn)
    conn.execute("INSERT INTO meta (key, value) VALUES ('questionnaire_seeded', '1')")
    conn.commit()


def _backfill_weights(conn: sqlite3.Connection) -> None:
    """One-time upgrade for questionnaires seeded before weights existed.

    Questions whose text still matches a default question get that question's
    weight, NIST function and control area. Sections an admin renamed, and
    questions an admin added or reworded, are left alone (they keep the
    standard 0.3 weight until an admin sets one).
    """
    if conn.execute("SELECT 1 FROM meta WHERE key = 'questionnaire_weights_v2'").fetchone():
        return
    from app.company_questionnaire import DEFAULT_QUESTIONS

    defaults = {" ".join(t.split()).lower(): (area, nist, w) for area, nist, w, t, _ in DEFAULT_QUESTIONS}
    for row in conn.execute("SELECT id, section, text FROM questionnaire_questions").fetchall():
        match = defaults.get(" ".join(row["text"].split()).lower())
        if not match:
            continue
        area, nist, weight = match
        section = area if row["section"] in _V1_SECTIONS else row["section"]
        conn.execute(
            "UPDATE questionnaire_questions SET weight = ?, nist_function = ?, section = ? WHERE id = ?",
            (weight, nist, section, row["id"]),
        )
    conn.execute("INSERT INTO meta (key, value) VALUES ('questionnaire_weights_v2', '1')")
    conn.commit()


def _insert_default_questions(conn: sqlite3.Connection) -> None:
    from app.company_questionnaire import DEFAULT_QUESTIONS, needs_document

    for i, (area, nist, weight, text, keywords) in enumerate(DEFAULT_QUESTIONS, start=1):
        conn.execute(
            """
            INSERT INTO questionnaire_questions
                (section, nist_function, weight, text, keywords, requires_document, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (area, nist, weight, text, ", ".join(keywords), int(needs_document(text)), i * 10),
        )


def add_vendor(name: str, category: str, owner: str, website: str = "", notes: str = "") -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO vendors (name, category, owner, website, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name.strip(), category.strip(), owner.strip(), website.strip(), notes.strip()),
        )
        return int(cur.lastrowid)


def list_vendors() -> List[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT v.*,
                       (SELECT a.tier FROM assessments a
                        WHERE a.vendor_id = v.id AND a.status = 'completed'
                        ORDER BY a.id DESC LIMIT 1) AS latest_tier,
                       (SELECT a.residual FROM assessments a
                        WHERE a.vendor_id = v.id AND a.status = 'completed'
                        ORDER BY a.id DESC LIMIT 1) AS latest_residual,
                       (SELECT a.due_date FROM assessments a
                        WHERE a.vendor_id = v.id AND a.status = 'completed'
                        ORDER BY a.id DESC LIMIT 1) AS next_review
                FROM vendors v
                ORDER BY v.name COLLATE NOCASE
                """
            )
        )


def get_vendor(vendor_id: int) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()


def save_assessment(
    vendor_id: int,
    answers: Dict[str, int],
    scores: Dict[str, Any],
    status: str = "completed",
    evidence: Optional[Dict[str, Any]] = None,
) -> int:
    due = None
    months = scores.get("review_months")
    if months:
        due = (date.today() + timedelta(days=int(months) * 30)).isoformat()
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO assessments (
                vendor_id, status, answers_json, inherent, control, residual,
                tier, review_months, recommendation, due_date, evidence_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                vendor_id,
                status,
                json.dumps(answers),
                scores.get("inherent"),
                scores.get("control"),
                scores.get("residual"),
                scores.get("tier"),
                scores.get("review_months"),
                scores.get("recommendation"),
                due,
                json.dumps(evidence or {}),
            ),
        )
        return int(cur.lastrowid)


def list_assessments(vendor_id: Optional[int] = None) -> List[sqlite3.Row]:
    sql = """
        SELECT a.*, v.name AS vendor_name
        FROM assessments a
        JOIN vendors v ON v.id = a.vendor_id
    """
    params: tuple = ()
    if vendor_id is not None:
        sql += " WHERE a.vendor_id = ?"
        params = (vendor_id,)
    sql += " ORDER BY a.id DESC"
    with connect() as conn:
        return list(conn.execute(sql, params))


def get_assessment(assessment_id: int) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            """
            SELECT a.*, v.name AS vendor_name, v.category, v.owner
            FROM assessments a
            JOIN vendors v ON v.id = a.vendor_id
            WHERE a.id = ?
            """,
            (assessment_id,),
        ).fetchone()


def portfolio_rows() -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT v.name, v.category, v.owner, a.tier, a.residual, a.inherent,
                   a.control, a.due_date, a.created_at
            FROM assessments a
            JOIN vendors v ON v.id = a.vendor_id
            WHERE a.status = 'completed'
            AND a.id = (
                SELECT MAX(a2.id) FROM assessments a2
                WHERE a2.vendor_id = a.vendor_id AND a2.status = 'completed'
            )
            ORDER BY a.residual DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def latest_answers(vendor_id: int) -> Dict[str, int]:
    """Answers from the vendor's most recent completed assessment, or {}."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT answers_json FROM assessments
            WHERE vendor_id = ? AND status = 'completed'
            ORDER BY id DESC LIMIT 1
            """,
            (vendor_id,),
        ).fetchone()
    return json.loads(row["answers_json"]) if row else {}


# --- Security documents -----------------------------------------------------


def add_document(
    vendor_id: int,
    doc_type: str,
    original_name: str,
    data: bytes,
    content_type: str = "",
    issued_on: Optional[str] = None,
    expires_on: Optional[str] = None,
    notes: str = "",
) -> int:
    """Write the file under data/documents/<vendor_id>/ and record it."""
    from app.documents import safe_filename

    vendor_dir = DOCS_DIR / str(int(vendor_id))
    vendor_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{safe_filename(original_name)}"
    (vendor_dir / stored_name).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    try:
        with connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO documents (
                    vendor_id, doc_type, original_name, stored_name, content_type,
                    size_bytes, sha256, issued_on, expires_on, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vendor_id,
                    doc_type,
                    original_name,
                    stored_name,
                    content_type or "",
                    len(data),
                    digest,
                    issued_on,
                    expires_on,
                    notes.strip(),
                ),
            )
            return int(cur.lastrowid)
    except Exception:
        (vendor_dir / stored_name).unlink(missing_ok=True)
        raise


def list_documents(vendor_id: Optional[int] = None) -> List[sqlite3.Row]:
    sql = """
        SELECT d.*, v.name AS vendor_name
        FROM documents d
        JOIN vendors v ON v.id = d.vendor_id
    """
    params: tuple = ()
    if vendor_id is not None:
        sql += " WHERE d.vendor_id = ?"
        params = (vendor_id,)
    sql += " ORDER BY d.id DESC"
    with connect() as conn:
        return list(conn.execute(sql, params))


def get_document(document_id: int) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()


def document_path(doc: sqlite3.Row) -> Path:
    return DOCS_DIR / str(int(doc["vendor_id"])) / doc["stored_name"]


def read_document(document_id: int) -> Optional[bytes]:
    doc = get_document(document_id)
    if not doc:
        return None
    path = document_path(doc)
    return path.read_bytes() if path.exists() else None


def delete_document(document_id: int) -> bool:
    doc = get_document(document_id)
    if not doc:
        return False
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    document_path(doc).unlink(missing_ok=True)
    return True


# --- Company questionnaire (admin-managed) -----------------------------------

QUESTION_FIELDS = (
    "section", "nist_function", "weight", "text", "keywords", "guidance",
    "requires_document", "sort_order", "active",
)


def list_questions(active_only: bool = True) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM questionnaire_questions"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY sort_order, id"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def _clean_question(fields: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: fields[k] for k in QUESTION_FIELDS if k in fields}
    for k in ("section", "text", "keywords", "guidance"):
        if k in out:
            out[k] = "" if out[k] is None else str(out[k]).strip()
    for k in ("requires_document", "active"):
        if k in out:
            out[k] = int(bool(out[k]))
    if "sort_order" in out:
        out["sort_order"] = int(out["sort_order"] or 0)
    if "weight" in out:
        out["weight"] = parse_weight(out["weight"])
    if "nist_function" in out:
        from app.company_questionnaire import NIST_FUNCTIONS

        nf = "" if out["nist_function"] is None else str(out["nist_function"]).strip()
        match = next((f for f in NIST_FUNCTIONS if f.lower() == nf.lower()), None)
        if nf and not match:
            raise ValueError(f"NIST function must be one of {', '.join(NIST_FUNCTIONS)} (got '{nf}').")
        out["nist_function"] = match or ""
    if not out.get("text", "x") or not out.get("section", "x"):
        raise ValueError("Every question needs a section and question text.")
    return out


def parse_weight(value: Any) -> float:
    """Weights run from 0 (not scored) to 1. Accepts 0.3, "0.3" or "30%"."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0
    if isinstance(value, str):
        v = value.strip()
        w = float(v.rstrip("%")) / 100 if v.endswith("%") else float(v)
    else:
        w = float(value)
    if w != w or w < 0 or w > 1:  # NaN or out of range
        raise ValueError(f"Weight must be between 0 and 1 (got {value}).")
    return round(w, 4)


def _log_change(conn, question_id, action, before, after, changed_by) -> None:
    conn.execute(
        """
        INSERT INTO questionnaire_changes (question_id, action, before_json, after_json, changed_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            question_id,
            action,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            changed_by,
        ),
    )


def add_question(fields: Dict[str, Any], changed_by: str = "admin") -> int:
    from app.company_questionnaire import STANDARD_WEIGHT

    data = _clean_question(
        {"keywords": "", "guidance": "", "requires_document": 0, "active": 1,
         "weight": STANDARD_WEIGHT, "nist_function": "", **fields}
    )
    if "sort_order" not in data:
        with connect() as conn:
            top = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM questionnaire_questions").fetchone()[0]
        data["sort_order"] = int(top) + 10
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    with connect() as conn:
        cur = conn.execute(f"INSERT INTO questionnaire_questions ({cols}) VALUES ({marks})", tuple(data.values()))
        qid = int(cur.lastrowid)
        _log_change(conn, qid, "add", None, data, changed_by)
        return qid


def update_question(question_id: int, fields: Dict[str, Any], changed_by: str = "admin") -> bool:
    """Apply changed fields; returns False when nothing actually changed."""
    data = _clean_question(fields)
    with connect() as conn:
        row = conn.execute("SELECT * FROM questionnaire_questions WHERE id = ?", (question_id,)).fetchone()
        if not row:
            raise KeyError(question_id)
        before = {k: row[k] for k in data}
        changed = {k: v for k, v in data.items() if before[k] != v}
        if not changed:
            return False
        sets = ", ".join(f"{k} = ?" for k in changed)
        conn.execute(
            f"UPDATE questionnaire_questions SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (*changed.values(), question_id),
        )
        _log_change(conn, question_id, "update", {k: before[k] for k in changed}, changed, changed_by)
        return True


def delete_question(question_id: int, changed_by: str = "admin") -> None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM questionnaire_questions WHERE id = ?", (question_id,)).fetchone()
        if not row:
            return
        conn.execute("DELETE FROM questionnaire_questions WHERE id = ?", (question_id,))
        _log_change(conn, question_id, "delete", dict(row), None, changed_by)


def reset_questionnaire(changed_by: str = "admin") -> None:
    """Replace every question with the shipped default set."""
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM questionnaire_questions").fetchone()[0]
        conn.execute("DELETE FROM questionnaire_questions")
        _insert_default_questions(conn)
        _log_change(conn, None, "reset", {"questions": count}, None, changed_by)


def replace_questionnaire(rows: List[Dict[str, Any]], changed_by: str = "admin") -> int:
    """Bulk import: replace all questions with `rows` (validated first).

    A blank weight imports as 0 (not scored), as a blank weight cell does in
    the scoring workbook.
    """
    clean = []
    for i, r in enumerate(rows, start=1):
        r = {"keywords": "", "guidance": "", "active": 1, "sort_order": i * 10,
             "weight": 0, "nist_function": "", **r}
        if "requires_document" not in r or r["requires_document"] in ("", None):
            from app.company_questionnaire import needs_document

            r["requires_document"] = needs_document(str(r.get("text", "")))
        clean.append(_clean_question(r))
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM questionnaire_questions").fetchone()[0]
        conn.execute("DELETE FROM questionnaire_questions")
        for data in clean:
            cols = ", ".join(data)
            marks = ", ".join("?" for _ in data)
            conn.execute(f"INSERT INTO questionnaire_questions ({cols}) VALUES ({marks})", tuple(data.values()))
        _log_change(conn, None, "import", {"questions": count}, {"questions": len(clean)}, changed_by)
    return len(clean)


def list_question_changes(limit: int = 200) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM questionnaire_changes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# --- Document reviews ---------------------------------------------------------


def save_review(
    vendor_id: int,
    method: str,
    model: Optional[str],
    document_ids: List[int],
    results: List[Dict[str, Any]],
    summary: Dict[str, Any],
    notes: Optional[List[str]] = None,
    responses: Optional[Dict[Any, str]] = None,
) -> int:
    """Save a review. `responses` defaults to the review's suggested responses."""
    from app.questionnaire_scoring import suggested_response

    if responses is None:
        responses = {r["question_id"]: suggested_response(r["status"]) for r in results}
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO document_reviews
                (vendor_id, method, model, document_ids_json, results_json, summary_json,
                 notes_json, responses_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vendor_id,
                method,
                model,
                json.dumps(document_ids),
                json.dumps(results),
                json.dumps(summary),
                json.dumps(notes or []),
                json.dumps({str(k): v for k, v in responses.items()}),
            ),
        )
        return int(cur.lastrowid)


def update_review_responses(review_id: int, responses: Dict[Any, str]) -> None:
    from app.questionnaire_scoring import RESPONSES

    bad = {v for v in responses.values() if v not in RESPONSES}
    if bad:
        raise ValueError(f"Invalid response(s): {', '.join(sorted(bad))}")
    with connect() as conn:
        conn.execute(
            "UPDATE document_reviews SET responses_json = ? WHERE id = ?",
            (json.dumps({str(k): v for k, v in responses.items()}), review_id),
        )


def _review_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["documents"] = json.loads(d.pop("document_ids_json") or "[]")
    for k in ("results", "summary", "notes"):
        d[k] = json.loads(d.pop(f"{k}_json") or "null")
    d["responses"] = {int(k): v for k, v in json.loads(d.pop("responses_json") or "{}").items()}
    return d


def list_reviews(vendor_id: int) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM document_reviews WHERE vendor_id = ? ORDER BY id DESC", (vendor_id,)
        ).fetchall()
    return [_review_row(r) for r in rows]


def latest_review(vendor_id: int) -> Optional[Dict[str, Any]]:
    reviews = list_reviews(vendor_id)
    return reviews[0] if reviews else None
