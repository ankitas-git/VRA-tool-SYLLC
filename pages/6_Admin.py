from __future__ import annotations

import io
import json

import pandas as pd
import streamlit as st

from app.auth import require_admin
from app.db import (
    add_question,
    delete_question,
    list_question_changes,
    list_questions,
    replace_questionnaire,
    reset_questionnaire,
    update_question,
)
from app.questionnaire_admin import CSV_COLUMNS, diff_questions

st.set_page_config(page_title="Admin — VRA-tool-SYLLC", layout="wide")
st.title("Admin: security questionnaire")
st.caption(
    "The questionnaire the document review checks vendor evidence against. "
    "Changes apply to new reviews; past reviews keep the questions they were run with."
)

if not require_admin():
    st.stop()

questions = list_questions(active_only=False)
active = sum(q["active"] for q in questions)
c1, c2, c3 = st.columns(3)
c1.metric("Questions", len(questions))
c2.metric("Active", active)
c3.metric("Sections", len({q["section"] for q in questions}))

tab_edit, tab_import, tab_log = st.tabs(["Edit questions", "Import / export", "Change log"])

with tab_edit:
    st.write(
        "Edit cells directly. Add a question in the empty row at the bottom; select rows and press "
        "Delete to remove them. Untick **active** to keep a question but leave it out of reviews. "
        "**keywords** (comma-separated) are used only by the offline keyword scan; "
        "**guidance** tells the AI reviewer what a complete answer looks like."
    )
    sections = sorted({q["section"] for q in questions})
    df = pd.DataFrame(questions, columns=["id", *CSV_COLUMNS]) if questions else pd.DataFrame(columns=["id", *CSV_COLUMNS])
    df["requires_document"] = df["requires_document"].astype(bool)
    df["active"] = df["active"].astype(bool)
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="question_editor",
        height=600,
        column_order=["id", "sort_order", "section", "text", "requires_document", "active", "keywords", "guidance"],
        column_config={
            "id": st.column_config.NumberColumn("id", disabled=True, width="small"),
            "sort_order": st.column_config.NumberColumn("order", step=10, width="small"),
            "section": st.column_config.TextColumn(
                "section", required=True,
                help="Existing sections: " + ", ".join(sections),
            ),
            "text": st.column_config.TextColumn("question", width="large", required=True),
            "requires_document": st.column_config.CheckboxColumn("asks for doc", default=False),
            "active": st.column_config.CheckboxColumn("active", default=True),
            "keywords": st.column_config.TextColumn("keywords", width="medium"),
            "guidance": st.column_config.TextColumn("guidance", width="medium"),
        },
    )
    rows = edited.to_dict("records")
    try:
        adds, updates, deletes = diff_questions(questions, rows)
        error = None
    except ValueError as exc:
        adds, updates, deletes, error = [], [], [], str(exc)
    if error:
        st.error(error)
    pending = len(adds) + len(updates) + len(deletes)
    if pending:
        st.info(f"Unsaved: {len(adds)} new, {len(updates)} changed, {len(deletes)} deleted.")
    confirm_delete = True
    if deletes:
        confirm_delete = st.checkbox(f"Confirm deleting {len(deletes)} question(s)")
    if st.button("Save changes", type="primary", disabled=not pending or bool(error) or not confirm_delete):
        for data in adds:
            add_question(data)
        for qid, fields in updates:
            update_question(qid, fields)
        for qid in deletes:
            delete_question(qid)
        st.session_state.pop("question_editor", None)
        st.success("Questionnaire saved.")
        st.rerun()

with tab_import:
    export = pd.DataFrame(questions, columns=CSV_COLUMNS) if questions else pd.DataFrame(columns=CSV_COLUMNS)
    st.download_button(
        "Export questionnaire (CSV)",
        export.to_csv(index=False).encode("utf-8"),
        file_name="syllc_security_questionnaire.csv",
        mime="text/csv",
    )
    st.divider()
    st.write(
        "**Import** replaces the whole questionnaire. The CSV needs `section` and `text` columns; "
        f"optional columns are {', '.join(c for c in CSV_COLUMNS if c not in ('section', 'text'))}. "
        "If `requires_document` is blank it is set from the question wording."
    )
    upload = st.file_uploader("Questionnaire CSV", type=["csv"])
    if upload is not None:
        try:
            incoming = pd.read_csv(io.BytesIO(upload.getvalue()), dtype=str, keep_default_na=False)
            missing = {"section", "text"} - set(incoming.columns)
            if missing:
                raise ValueError(f"Missing column(s): {', '.join(sorted(missing))}")
            incoming = incoming[[c for c in CSV_COLUMNS if c in incoming.columns]]
            incoming = incoming[incoming["text"].str.strip() != ""]
            for col in ("requires_document", "active"):
                if col in incoming.columns:
                    incoming[col] = incoming[col].map(
                        lambda v: "" if str(v).strip() == "" else str(v).strip().lower() in ("1", "true", "yes", "y")
                    )
            st.write(f"{len(incoming)} questions in {incoming['section'].nunique()} sections.")
            st.dataframe(incoming.head(20), use_container_width=True, hide_index=True)
            if st.checkbox("Replace the current questionnaire with this file"):
                if st.button("Import", type="primary"):
                    records = [
                        {k: v for k, v in r.items() if not (k == "sort_order" and str(v).strip() == "")}
                        for r in incoming.to_dict("records")
                    ]
                    n = replace_questionnaire(records)
                    st.session_state.pop("question_editor", None)
                    st.success(f"Imported {n} questions.")
                    st.rerun()
        except Exception as exc:
            st.error(f"Could not import: {exc}")
    st.divider()
    st.write("**Reset** restores the default SYLLC questionnaire that shipped with the app.")
    if st.checkbox("I want to discard all edits and restore the defaults"):
        if st.button("Reset to default questionnaire"):
            reset_questionnaire()
            st.session_state.pop("question_editor", None)
            st.success("Questionnaire reset.")
            st.rerun()

with tab_log:
    changes = list_question_changes()
    if not changes:
        st.info("No changes yet.")
    else:
        def fmt(v):
            if not v:
                return ""
            d = json.loads(v)
            return "; ".join(f"{k}: {str(x)[:80]}" for k, x in d.items())

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "when": c["changed_at"],
                        "action": c["action"],
                        "question": c["question_id"],
                        "before": fmt(c["before_json"]),
                        "after": fmt(c["after_json"]),
                    }
                    for c in changes
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
