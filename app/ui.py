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
    with st.form(f"upload_{key}", clear_on_submit=True):
        doc_type = st.selectbox(
            "Document type",
            type_ids,
            index=index,
            format_func=lambda t: DOC_TYPES_BY_ID[t]["label"],
        )
        st.caption(DOC_TYPES_BY_ID[doc_type]["description"])
        upload = st.file_uploader(
            "File",
            type=[e.lstrip(".") for e in sorted(ALLOWED_EXTENSIONS)],
            help=f"Max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
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
            if upload is None:
                st.error("Choose a file to upload.")
                return
            data = upload.getvalue()
            errors = validate_upload(upload.name, data)
            if errors:
                for e in errors:
                    st.error(e)
                return
            exp = expires or default_expiry(doc_type, issued)
            add_document(
                vendor_id,
                doc_type,
                upload.name,
                data,
                content_type=upload.type or "",
                issued_on=issued.isoformat() if issued else None,
                expires_on=exp.isoformat() if exp else None,
                notes=notes,
            )
            st.success(f"Uploaded {upload.name} as {DOC_TYPES_BY_ID[doc_type]['label']}.")
            st.rerun()
