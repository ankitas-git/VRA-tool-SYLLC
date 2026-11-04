"""Turn an edited questionnaire table into add / update / delete operations."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

EDITABLE = ("section", "text", "keywords", "guidance", "requires_document", "sort_order", "active")
CSV_COLUMNS = ["section", "text", "keywords", "guidance", "requires_document", "sort_order", "active"]


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip())


def _norm(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k in EDITABLE:
        v = row.get(k)
        if k in ("requires_document", "active"):
            out[k] = int(bool(v)) if not _blank(v) else (1 if k == "active" else 0)
        elif k == "sort_order":
            out[k] = int(v) if not _blank(v) else None
        else:
            out[k] = "" if _blank(v) else str(v).strip()
    return out


def diff_questions(
    original: List[Dict[str, Any]], edited: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Tuple[int, Dict[str, Any]]], List[int]]:
    """Compare the saved questions with the edited table.

    Rows without an id are new. Rows whose id disappeared were deleted.
    Fully blank new rows are ignored. Raises ValueError for rows missing
    a section or question text.
    """
    by_id = {int(q["id"]): q for q in original}
    adds: List[Dict[str, Any]] = []
    updates: List[Tuple[int, Dict[str, Any]]] = []
    seen = set()
    for i, row in enumerate(edited, start=1):
        rid = row.get("id")
        data = _norm(row)
        if _blank(rid):
            if not data["section"] and not data["text"]:
                continue
            if not data["section"] or not data["text"]:
                raise ValueError(f"New row {i}: section and question text are both required.")
            if data["sort_order"] is None:
                data.pop("sort_order")
            adds.append(data)
            continue
        qid = int(rid)
        seen.add(qid)
        if qid not in by_id:
            continue
        if not data["section"] or not data["text"]:
            raise ValueError(f"Question #{qid}: section and question text are both required.")
        before = _norm(by_id[qid])
        if data["sort_order"] is None:
            data["sort_order"] = before["sort_order"]
        changed = {k: v for k, v in data.items() if before[k] != v}
        if changed:
            updates.append((qid, changed))
    deletes = [qid for qid in by_id if qid not in seen]
    return adds, updates, deletes
