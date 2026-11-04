from __future__ import annotations

import streamlit as st

from app.db import latest_review, list_documents, list_vendors, save_assessment
from app.documents import evidence_gaps, required_doc_types
from app.questionnaire import CONTROL_QUESTIONS, INHERENT_QUESTIONS, questions_by_id
from app.scoring import score_assessment
from app.ui import checklist_table, upload_form

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

st.subheader("Security documents")
st.caption(
    "Upload the vendor's security evidence. The request list follows the inherent-risk "
    "answers above, and strong control answers are checked against what is on file."
)
inherent_answers = {q["id"]: answers[q["id"]] for q in INHERENT_QUESTIONS}
control_answers = {q["id"]: answers[q["id"]] for q in CONTROL_QUESTIONS}
required = required_doc_types(inherent_answers)
docs = [dict(d) for d in list_documents(vendor_id)]
rows = checklist_table(required, docs)
outstanding = [r for r in rows if r["status"] in ("Missing", "Expired")]
if outstanding:
    st.warning("Please upload: " + ", ".join(r["document"] for r in outstanding) + ".")
with st.expander("Upload a document", expanded=bool(outstanding)):
    upload_form(
        vendor_id,
        key=f"assess_{vendor_id}",
        default_type=outstanding[0]["doc_type"] if outstanding else None,
    )

review = latest_review(vendor_id)
if review:
    st.info(
        f"Latest questionnaire review (#{review['id']}, {review['created_at']}): "
        f"{review['summary']['coverage_pct']}% coverage, "
        f"{review['summary']['total'] - review['summary']['counts'].get('Answered', 0)} question(s) not fully answered."
    )
else:
    st.caption("No questionnaire review yet for this vendor. Run one on the Review page.")
st.page_link("pages/3_Review.py", label="Review documents against the questionnaire", icon="🔍")

gaps = evidence_gaps(control_answers, docs)
qmap = questions_by_id()
for g in gaps:
    st.warning(
        f"**Unverified claim** — {qmap[g['question_id']]['prompt']} "
        f"No current supporting document. Upload one of: {', '.join(g['needs_one_of'])}."
    )

if st.button("Score and save", type="primary"):
    scores = score_assessment(answers)
    evidence = {
        "requested": required,
        "outstanding": [r["doc_type"] for r in outstanding],
        "document_ids": [d["id"] for d in docs],
        "gaps": gaps,
        "questionnaire_review_id": review["id"] if review else None,
        "questionnaire_coverage_pct": review["summary"]["coverage_pct"] if review else None,
    }
    assessment_id = save_assessment(vendor_id, answers, scores, evidence=evidence)
    st.success(f"Saved assessment #{assessment_id}")
    if outstanding or gaps:
        st.warning(
            f"Saved with {len(outstanding)} outstanding document(s) and "
            f"{len(gaps)} unverified control claim(s)."
        )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Inherent", scores["inherent"])
    c2.metric("Control strength", scores["control"])
    c3.metric("Residual", scores["residual"])
    c4.metric("Tier", scores["tier"])
    st.write(f"Reassess in **{scores['review_months']} months**.")
    st.info(scores["recommendation"])
    st.write("Domain scores")
    st.json(scores["domains"])
