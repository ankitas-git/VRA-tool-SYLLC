from __future__ import annotations

import streamlit as st

from app.db import list_vendors, save_assessment
from app.questionnaire import CONTROL_QUESTIONS, INHERENT_QUESTIONS
from app.scoring import score_assessment

st.set_page_config(page_title="Assess — VRA-tool-SYLLC", layout="wide")
st.title("Run assessment")

vendors = list_vendors()
if not vendors:
    st.warning("Add a vendor first.")
    st.stop()

options = {f"{v['name']} (#{v['id']})": v["id"] for v in vendors}
label = st.selectbox("Vendor", list(options.keys()))
vendor_id = options[label]

answers = {}

st.subheader("Inherent risk")
st.caption("What could go wrong given the data, access, and business dependency.")
for q in INHERENT_QUESTIONS:
    labels = [c["label"] for c in q["choices"]]
    picked = st.radio(q["prompt"], labels, key=q["id"])
    answers[q["id"]] = next(c["value"] for c in q["choices"] if c["label"] == picked)

st.subheader("Control environment")
st.caption("Evidence of how the vendor reduces that risk.")
for q in CONTROL_QUESTIONS:
    labels = [c["label"] for c in q["choices"]]
    picked = st.radio(q["prompt"], labels, key=q["id"])
    answers[q["id"]] = next(c["value"] for c in q["choices"] if c["label"] == picked)

if st.button("Score and save", type="primary"):
    scores = score_assessment(answers)
    assessment_id = save_assessment(vendor_id, answers, scores)
    st.success(f"Saved assessment #{assessment_id}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Inherent", scores["inherent"])
    c2.metric("Control strength", scores["control"])
    c3.metric("Residual", scores["residual"])
    c4.metric("Tier", scores["tier"])
    st.write(f"Reassess in **{scores['review_months']} months**.")
    st.info(scores["recommendation"])
    st.write("Domain scores")
    st.json(scores["domains"])
