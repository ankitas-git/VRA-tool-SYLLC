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

# Columns added after the first release; applied to existing databases on connect.
MIGRATIONS = [
    ("assessments", "evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
]


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
    return conn


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
