from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app.db import get_assessment, list_assessments
from app.documents import DOC_TYPES_BY_ID
from app.questionnaire import questions_by_id

st.set_page_config(page_title="History — VRA-tool-SYLLC", layout="wide")
st.title("Assessment history")

rows = list_assessments()
if not rows:
    st.info("No assessments yet.")
    st.stop()

df = pd.DataFrame([dict(r) for r in rows])
st.dataframe(
    df[
        [
            "id",
            "vendor_name",
            "status",
            "inherent",
            "control",
            "residual",
            "tier",
            "due_date",
            "created_at",
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

ids = [r["id"] for r in rows]
selected = st.selectbox("Open assessment", ids)
detail = get_assessment(selected)
if detail:
    st.subheader(f"{detail['vendor_name']} — #{detail['id']}")
    st.write(detail["recommendation"] or "")
    answers = json.loads(detail["answers_json"] or "{}")
    qmap = questions_by_id()
    lines = []
    for qid, value in answers.items():
        q = qmap.get(qid)
        if not q:
            continue
        label = next((c["label"] for c in q["choices"] if c["value"] == value), str(value))
        lines.append({"domain": q["domain"], "question": q["prompt"], "answer": label, "score": value})
    st.dataframe(pd.DataFrame(lines), use_container_width=True, hide_index=True)

    evidence = json.loads(detail["evidence_json"] or "{}") if "evidence_json" in detail.keys() else {}
    st.subheader("Evidence at time of assessment")
    if not evidence:
        st.caption("No document evidence was recorded for this assessment.")
    else:
        label = lambda t: DOC_TYPES_BY_ID.get(t, {}).get("label", t)
        if evidence.get("questionnaire_score") is not None:
            st.metric("Questionnaire score at the time", f"{evidence['questionnaire_score'] * 100:.1f}%")
        c1, c2, c3 = st.columns(3)
        c1.metric("Documents requested", len(evidence.get("requested", [])))
        c2.metric("Outstanding", len(evidence.get("outstanding", [])))
        c3.metric("Unverified claims", len(evidence.get("gaps", [])))
        if evidence.get("outstanding"):
            st.write("Outstanding: " + ", ".join(label(t) for t in evidence["outstanding"]))
        for g in evidence.get("gaps", []):
            q = qmap.get(g["question_id"])
            st.write(f"- Unverified: {q['prompt'] if q else g['question_id']}")
