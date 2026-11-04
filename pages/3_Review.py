from __future__ import annotations

import pandas as pd
import streamlit as st

from app.db import (
    list_documents,
    list_questions,
    list_reviews,
    list_vendors,
    read_document,
    save_review,
    update_review_responses,
)
from app.questionnaire_scoring import (
    RESPONSES,
    SATISFACTORY,
    fmt_pct,
    review_items,
    score_review,
    suggested_response,
)
from app.workbook import write_scored_workbook
from app.documents import DOC_TYPES_BY_ID
from app.review import (
    ANSWERED,
    NOT_ANSWERED,
    NOT_REVIEWED,
    PARTIAL,
    STATUSES,
    ReviewError,
    ai_configured,
    claude_review,
    follow_up_request,
    keyword_review,
    manual_results,
    prepare_docs,
    review_model,
    summarize,
)

st.set_page_config(page_title="Document review — VRA-tool-SYLLC", layout="wide")
st.title("Document review")
st.caption(
    "Check the vendor's uploaded documents against the SYLLC security questionnaire "
    "and see which questions they answer."
)

ICON = {ANSWERED: "✅", PARTIAL: "🟡", NOT_ANSWERED: "❌", NOT_REVIEWED: "⚪"}

vendors = list_vendors()
if not vendors:
    st.warning("Add a vendor first.")
    st.stop()

options = {f"{v['name']} (#{v['id']})": v for v in vendors}
label = st.selectbox("Vendor", list(options.keys()))
vendor = options[label]
vendor_id = vendor["id"]

questions = list_questions()
doc_rows = list_documents(vendor_id)

c1, c2 = st.columns(2)
c1.metric("Questionnaire questions", len(questions))
c2.metric("Documents on file", len(doc_rows))

if not questions:
    st.warning("The questionnaire has no active questions. An admin can add them on the Admin page.")
    st.stop()

# --- Run a review -------------------------------------------------------------
with st.expander("Run a new review", expanded=not list_reviews(vendor_id)):
    if not doc_rows:
        st.info("No documents uploaded for this vendor yet. Upload them on the Documents page.")
        st.page_link("pages/2_Documents.py", label="Go to Documents", icon="📎")
    else:
        st.write("Documents to review:")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "file": d["original_name"],
                        "type": DOC_TYPES_BY_ID.get(d["doc_type"], {}).get("label", d["doc_type"]),
                        "size_kb": round(d["size_bytes"] / 1024, 1),
                    }
                    for d in doc_rows
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        methods = ["AI review (Claude)", "Keyword scan (offline)"]
        method = st.radio(
            "Method",
            methods,
            index=0 if ai_configured() else 1,
            help=(
                "The AI review reads each document and judges whether it answers each question, "
                "quoting the evidence. The keyword scan only finds where topics are mentioned."
            ),
        )
        if method == methods[0]:
            if ai_configured():
                st.caption(
                    f"Uses `{review_model()}`. Documents are sent to the Anthropic API. "
                    f"{len(questions)} questions are reviewed in batches; expect a few minutes."
                )
            else:
                st.warning("Set `ANTHROPIC_API_KEY` before starting the app to use the AI review.")
        if st.button("Run review", type="primary"):
            docs = prepare_docs(
                doc_rows,
                read_document,
                lambda t: DOC_TYPES_BY_ID.get(t, {}).get("label", t),
            )
            bar = st.progress(0.0, text="Starting…")
            try:
                if method == methods[0]:
                    results, notes = claude_review(
                        questions, docs, progress=lambda f, m: bar.progress(f, text=m)
                    )
                    used_method, model = "claude", review_model()
                else:
                    results, notes = keyword_review(questions, docs)
                    used_method, model = "keyword", None
                bar.progress(1.0, text="Done")
                save_review(
                    vendor_id,
                    used_method,
                    model,
                    [d["id"] for d in docs],
                    results,
                    summarize(results),
                    notes,
                )
                st.rerun()
            except ReviewError as exc:
                bar.empty()
                st.error(str(exc))
    st.divider()
    st.caption(
        "Or score the questionnaire by hand, without reviewing documents: every question starts "
        "as Unsatisfactory and you set the responses below."
    )
    if st.button("Start manual scoring"):
        results = manual_results(questions)
        save_review(vendor_id, "manual", None, [d["id"] for d in doc_rows], results, summarize(results), [])
        st.rerun()

# --- Show a review ------------------------------------------------------------
reviews = list_reviews(vendor_id)
if not reviews:
    st.stop()

METHOD_LABEL = {"claude": "AI review", "keyword": "Keyword scan", "manual": "Manual scoring"}
review_labels = {
    f"#{r['id']} — {r['created_at']} — {METHOD_LABEL.get(r['method'], r['method'])} "
    f"(score {fmt_pct(score_review(r, questions)['overall'])})": r
    for r in reviews
}
review = review_labels[st.selectbox("Review", list(review_labels.keys()))]
results = review["results"]
summary = review["summary"]
counts = summary["counts"]

score = score_review(review, questions)

# --- Weighted score -------------------------------------------------------------
st.subheader("Questionnaire score")
st.caption(
    "Each question adds its weight when the response is Satisfactory and nothing when it is "
    "Unsatisfactory. Score = points earned ÷ points possible, overall, per NIST function and "
    "per control area. Responses start from the document review (only fully answered questions "
    "are Satisfactory) and can be changed below."
)
s1, s2, s3 = st.columns(3)
s1.metric("Overall score", fmt_pct(score["overall"]))
s2.metric("Points", f"{score['actual']:.1f} / {score['possible']:.1f}")
s3.metric("Satisfactory responses", f"{score['satisfactory']} / {score['satisfactory'] + score['unsatisfactory']}")

pct_col = st.column_config.ProgressColumn("score", min_value=0, max_value=1, format="percent")


def group_table(groups, label):
    return pd.DataFrame(
        [
            {label: g["name"], "score": g["score"], "points": f"{g['actual']:.1f} / {g['possible']:.1f}",
             "questions": g["questions"]}
            for g in groups
        ]
    )


g1, g2 = st.columns([2, 3])
with g1:
    st.write("**Score by NIST function**")
    st.dataframe(group_table(score["by_nist_function"], "NIST function"), use_container_width=True,
                 hide_index=True, column_config={"score": pct_col})
with g2:
    st.write("**Score by control area**")
    st.dataframe(group_table(score["by_control_area"], "control area"), use_container_width=True,
                 hide_index=True, column_config={"score": pct_col})

items = review_items(review, questions)
with st.expander("Set responses"):
    resp_df = pd.DataFrame(
        [
            {
                "question_id": it["question_id"],
                "control area": it["control_area"],
                "NIST": it["nist_function"],
                "question": it["question"],
                "weight": it["weight"],
                "document review": it["review_status"],
                "response": it["response"],
            }
            for it in items
        ]
    )
    edited = st.data_editor(
        resp_df,
        key=f"responses_{review['id']}",
        use_container_width=True,
        hide_index=True,
        height=500,
        disabled=["question_id", "control area", "NIST", "question", "weight", "document review"],
        column_config={
            "question_id": None,
            "question": st.column_config.TextColumn(width="large"),
            "weight": st.column_config.NumberColumn(format="%.2f", width="small"),
            "response": st.column_config.SelectboxColumn(options=RESPONSES, required=True),
        },
    )
    new_responses = dict(zip(edited["question_id"], edited["response"]))
    changed = sum(1 for it in items if new_responses.get(it["question_id"]) != it["response"])
    b1, b2 = st.columns(2)
    if b1.button(f"Save responses ({changed} changed)", type="primary", disabled=not changed):
        update_review_responses(review["id"], new_responses)
        st.rerun()
    if b2.button("Reset to the document review's suggestions"):
        update_review_responses(
            review["id"], {it["question_id"]: suggested_response(it["review_status"]) for it in items}
        )
        st.session_state.pop(f"responses_{review['id']}", None)
        st.rerun()

st.subheader("Does the evidence answer the questionnaire?")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Coverage", f"{summary['coverage_pct']}%")
m2.metric("Answered", counts.get(ANSWERED, 0))
m3.metric("Partially answered", counts.get(PARTIAL, 0))
m4.metric("Not answered", counts.get(NOT_ANSWERED, 0))
m5.metric("Not reviewed", counts.get(NOT_REVIEWED, 0))

if counts.get(ANSWERED, 0) == summary["total"]:
    st.success("The documents answer every question in the questionnaire.")
else:
    open_n = summary["total"] - counts.get(ANSWERED, 0)
    st.warning(f"{open_n} of {summary['total']} questions are not fully answered by the documents.")

for note in review["notes"]:
    st.caption(f"ℹ️ {note}")

current_ids = {q["id"]: q["text"] for q in questions}
reviewed_ids = {r["question_id"]: r["question"] for r in results}
if current_ids != reviewed_ids:
    st.info("The questionnaire has changed since this review ran. Run a new review to check the current questions.")
reviewed_docs = set(review["documents"])
if reviewed_docs != {d["id"] for d in doc_rows}:
    st.info("Documents have been added or removed since this review ran.")

st.write("**By section**")
sec_rows = []
for section, c in summary["by_section"].items():
    total = sum(c.values())
    sec_rows.append(
        {
            "section": section,
            "answered": c.get(ANSWERED, 0),
            "partial": c.get(PARTIAL, 0),
            "not answered": c.get(NOT_ANSWERED, 0) + c.get(NOT_REVIEWED, 0),
            "coverage": (c.get(ANSWERED, 0) + 0.5 * c.get(PARTIAL, 0)) / total if total else 0,
        }
    )
st.dataframe(
    pd.DataFrame(sec_rows),
    use_container_width=True,
    hide_index=True,
    column_config={"coverage": st.column_config.ProgressColumn("coverage", min_value=0, max_value=1, format="percent")},
)

st.write("**Question by question**")
f1, f2 = st.columns(2)
status_filter = f1.multiselect("Status", STATUSES, default=[s for s in STATUSES if s != ANSWERED])
section_filter = f2.multiselect("Section", list(summary["by_section"].keys()))
shown = [
    r
    for r in results
    if r["status"] in status_filter and (not section_filter or r["section"] in section_filter)
]
st.caption(f"Showing {len(shown)} of {len(results)} questions.")
for n, r in enumerate(shown, start=1):
    title = f"{ICON[r['status']]} {r['question'][:140]}{'…' if len(r['question']) > 140 else ''}"
    with st.expander(title):
        st.caption(f"{r['section']} · {r['status']}" + (" · asks for a document" if r.get("requires_document") else ""))
        st.write(f"**Question:** {r['question']}")
        if r["answer"]:
            st.write(f"**What the documents say:** {r['answer']}")
        for e in r["evidence"]:
            st.markdown(f"> {e['excerpt']}\n>\n> — *{e['document']}*")
        if r["missing"]:
            st.write(f"**Still needed:** {r['missing']}")
        if r["follow_up"] and r["status"] != ANSWERED:
            st.write(f"**Ask the vendor:** {r['follow_up']}")

st.subheader("Export")
flat = pd.DataFrame(
    [
        {
            "section": r["section"],
            "question": r["question"],
            "status": r["status"],
            "answer": r["answer"],
            "evidence": " || ".join(f"{e['document']}: {e['excerpt']}" for e in r["evidence"]),
            "still_needed": r["missing"],
            "follow_up": r["follow_up"],
            "response": next(it["response"] for it in items if it["question_id"] == r["question_id"]),
            "weight": next(it["weight"] for it in items if it["question_id"] == r["question_id"]),
        }
        for r in results
    ]
)
st.download_button(
    "Download scored questionnaire (Excel, same layout as the scoring workbook)",
    write_scored_workbook(f"{vendor['name']} Vendor Risk Assessment", items),
    file_name=f"vendor_risk_assessment_{vendor_id}_{review['id']}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
d1, d2 = st.columns(2)
d1.download_button(
    "Download results (CSV)",
    flat.to_csv(index=False).encode("utf-8"),
    file_name=f"questionnaire_review_{vendor_id}_{review['id']}.csv",
    mime="text/csv",
)
d2.download_button(
    "Download vendor follow-up request (Markdown)",
    follow_up_request(vendor["name"], results).encode("utf-8"),
    file_name=f"follow_up_{vendor_id}_{review['id']}.md",
    mime="text/markdown",
)
