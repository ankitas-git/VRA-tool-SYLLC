from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app.db import get_assessment, list_assessments
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
