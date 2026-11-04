from __future__ import annotations

import pandas as pd
import streamlit as st

from app.db import list_documents, list_questions, list_reviews, list_vendors, read_document, save_review
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

# --- Show a review ------------------------------------------------------------
reviews = list_reviews(vendor_id)
if not reviews:
    st.stop()

review_labels = {
    f"#{r['id']} — {r['created_at']} — "
    f"{'AI review' if r['method'] == 'claude' else 'Keyword scan'} "
    f"({r['summary']['coverage_pct']}% coverage)": r
    for r in reviews
}
review = review_labels[st.selectbox("Review", list(review_labels.keys()))]
results = review["results"]
summary = review["summary"]
counts = summary["counts"]

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
        }
        for r in results
    ]
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
