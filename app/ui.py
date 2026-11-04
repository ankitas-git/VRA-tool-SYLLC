"""Streamlit widgets shared across pages."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

import pandas as pd
import streamlit as st

from app.db import add_document
from app.documents import (
    ALLOWED_EXTENSIONS,
    DOC_TYPES,
    DOC_TYPES_BY_ID,
    MAX_UPLOAD_BYTES,
    checklist,
    default_expiry,
    validate_upload,
)

STATUS_ICON = {"Current": "✅", "Expiring soon": "⚠️", "Expired": "❌", "Missing": "⬜"}


def checklist_table(required: List[str], documents) -> List[dict]:
    rows = checklist(required, [dict(d) for d in documents])
    df = pd.DataFrame(rows)
    if not df.empty:
        df["status"] = df["status"].map(lambda s: f"{STATUS_ICON.get(s, '')} {s}")
        st.dataframe(df[["document", "status"]], use_container_width=True, hide_index=True)
    return rows


def upload_form(vendor_id: int, key: str, default_type: Optional[str] = None) -> None:
    """Form to upload one security document for a vendor."""
    type_ids = [d["id"] for d in DOC_TYPES]
    index = type_ids.index(default_type) if default_type in type_ids else 0
    # The type picker sits outside the form so its description updates as you choose.
    doc_type = st.selectbox(
        "Document type",
        type_ids,
        index=index,
        format_func=lambda t: DOC_TYPES_BY_ID[t]["label"],
        key=f"doctype_{key}",
    )
    st.caption(DOC_TYPES_BY_ID[doc_type]["description"])
    with st.form(f"upload_{key}", clear_on_submit=True):
        uploads = st.file_uploader(
            "Files",
            type=[e.lstrip(".") for e in sorted(ALLOWED_EXTENSIONS)],
            accept_multiple_files=True,
            help=f"Max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB per file. All files get the type and dates chosen here.",
        )
        c1, c2 = st.columns(2)
        with c1:
            issued = st.date_input(
                "Report / issue date",
                value=None,
                max_value=date.today(),
                help="Used to work out when the document expires.",
            )
        with c2:
            expires = st.date_input(
                "Expiry date (optional)",
                value=None,
                help="Leave blank to use the default validity for this document type.",
            )
        notes = st.text_input("Notes", placeholder="e.g. covers period Jan–Dec, bridge letter attached")
        if st.form_submit_button("Upload document", type="primary"):
            if not uploads:
                st.error("Choose at least one file to upload.")
                return
            problems = {}
            for up in uploads:
                errs = validate_upload(up.name, up.getvalue())
                if errs:
                    problems[up.name] = errs
            if problems:
                for name, errs in problems.items():
                    for e in errs:
                        st.error(f"{name}: {e}")
                st.error("Nothing was uploaded. Fix or remove the files above and try again.")
                return
            exp = expires or default_expiry(doc_type, issued)
            for up in uploads:
                add_document(
                    vendor_id,
                    doc_type,
                    up.name,
                    up.getvalue(),
                    content_type=up.type or "",
                    issued_on=issued.isoformat() if issued else None,
                    expires_on=exp.isoformat() if exp else None,
                    notes=notes,
                )
            st.success(f"Uploaded {len(uploads)} file(s) as {DOC_TYPES_BY_ID[doc_type]['label']}.")
            st.rerun()
