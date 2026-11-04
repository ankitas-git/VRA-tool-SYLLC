"""Weighted questionnaire score, matching SYLLC's scoring workbook.

Per question (workbook columns E-G):
    Actual   = weight if the response is "Satisfactory", else 0
    Possible = weight

Overall score         = sum(Actual) / sum(Possible)
Score by NIST function = the same ratio over that function's questions
Score by control area  = the same ratio over that area's questions

A question with weight 0 (blank in the workbook) is informational: it adds
nothing to Actual or Possible. A group with no weighted questions has no
score (the workbook would show #DIV/0!).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.company_questionnaire import NIST_FUNCTIONS, STANDARD_WEIGHT

SATISFACTORY = "Satisfactory"
UNSATISFACTORY = "Unsatisfactory"
RESPONSES = [SATISFACTORY, UNSATISFACTORY]


def suggested_response(review_status: str) -> str:
    """Response suggested by the document review.

    Only a fully answered question is Satisfactory: the workbook is pass/fail,
    so a partial answer earns nothing until an analyst marks it Satisfactory.
    """
    return SATISFACTORY if review_status == "Answered" else UNSATISFACTORY


def _ratio(actual: float, possible: float) -> Optional[float]:
    return round(actual / possible, 4) if possible else None


def _group(items: List[Dict[str, Any]], key: str, order: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, float]] = {}
    for it in items:
        g = groups.setdefault(it[key] or "(none)", {"actual": 0.0, "possible": 0.0, "questions": 0})
        g["actual"] += it["actual"]
        g["possible"] += it["possible"]
        g["questions"] += 1
    names = list(groups)
    if order:
        names = [n for n in order if n in groups] + [n for n in names if n not in order]
    return [
        {
            "name": n,
            "actual": round(groups[n]["actual"], 4),
            "possible": round(groups[n]["possible"], 4),
            "score": _ratio(groups[n]["actual"], groups[n]["possible"]),
            "questions": int(groups[n]["questions"]),
        }
        for n in names
    ]


def score_questionnaire(questions: Iterable[Mapping[str, Any]], responses: Mapping[Any, str]) -> Dict[str, Any]:
    """Score questions against responses keyed by question id.

    `questions` need: id (or question_id), weight, nist_function, and
    control_area (or section). A missing response counts as Unsatisfactory,
    as an unanswered row does in the workbook.
    """
    items = []
    for q in questions:
        qid = q.get("question_id", q.get("id"))
        weight = q.get("weight")
        weight = STANDARD_WEIGHT if weight is None else float(weight)
        response = responses.get(qid, responses.get(str(qid), UNSATISFACTORY))
        items.append(
            {
                "question_id": qid,
                "control_area": q.get("control_area") or q.get("section") or "",
                "nist_function": q.get("nist_function") or "",
                "weight": weight,
                "response": response,
                "actual": weight if response == SATISFACTORY else 0.0,
                "possible": weight,
            }
        )
    actual = sum(i["actual"] for i in items)
    possible = sum(i["possible"] for i in items)
    return {
        "overall": _ratio(actual, possible),
        "actual": round(actual, 4),
        "possible": round(possible, 4),
        "satisfactory": sum(1 for i in items if i["response"] == SATISFACTORY),
        "unsatisfactory": sum(1 for i in items if i["response"] != SATISFACTORY),
        "by_nist_function": _group(items, "nist_function", NIST_FUNCTIONS),
        "by_control_area": _group(items, "control_area"),
        "items": items,
    }


def fmt_pct(score: Optional[float]) -> str:
    return "n/a" if score is None else f"{score * 100:.1f}%"


def review_items(review: Mapping[str, Any], current_questions: Iterable[Mapping[str, Any]] = ()) -> List[Dict[str, Any]]:
    """Scoring rows for a saved review.

    Weights and NIST functions are taken from the review's own snapshot, so
    later questionnaire edits don't change past scores. Reviews saved before
    weights existed fall back to the current questionnaire.
    """
    current = {q["id"]: q for q in current_questions}
    responses = review.get("responses") or {}
    rows = []
    for r in review["results"]:
        q = current.get(r["question_id"], {})
        weight = r.get("weight")
        if weight is None:
            weight = q.get("weight", STANDARD_WEIGHT)
        rows.append(
            {
                "question_id": r["question_id"],
                "control_area": r["section"],
                "nist_function": r.get("nist_function") or q.get("nist_function", ""),
                "question": r["question"],
                "weight": float(weight),
                "review_status": r["status"],
                "response": responses.get(r["question_id"]) or suggested_response(r["status"]),
                "note": r.get("missing") or "",
                "answer": r.get("answer") or "",
                "evidence": "\n".join(
                    f"{e['document']}: \u201c{e['excerpt']}\u201d" for e in r.get("evidence") or []
                ),
            }
        )
    return rows


def score_review(review: Mapping[str, Any], current_questions: Iterable[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    rows = review_items(review, current_questions)
    return score_questionnaire(rows, {r["question_id"]: r["response"] for r in rows})
