from __future__ import annotations

import pandas as pd
import streamlit as st

from app.db import delete_document, latest_answers, list_documents, list_vendors, read_document
from app.documents import DOC_TYPES_BY_ID, doc_status, required_doc_types
from app.ui import STATUS_ICON, checklist_table, upload_form

st.set_page_config(page_title="Documents — VRA-tool-SYLLC", layout="wide")
st.title("Security documents")
st.caption("Request and collect the vendor's security evidence before scoring the assessment.")

vendors = list_vendors()
if not vendors:
    st.warning("Add a vendor first.")
    st.stop()

options = {f"{v['name']} (#{v['id']})": v["id"] for v in vendors}
label = st.selectbox("Vendor", list(options.keys()))
vendor_id = options[label]

answers = latest_answers(vendor_id)
required = required_doc_types(answers)
docs = list_documents(vendor_id)

st.subheader("Requested documents")
if answers:
    st.caption("Based on the inherent-risk answers in this vendor's latest assessment.")
else:
    st.caption(
        "Baseline request. More documents are requested once an assessment records "
        "the vendor's data sensitivity, access, and criticality."
    )
rows = checklist_table(required, docs)
outstanding = [r for r in rows if r["status"] in ("Missing", "Expired")]
if outstanding:
    st.warning(
        "Please upload: " + ", ".join(r["document"] for r in outstanding) + "."
    )
else:
    st.success("All requested documents are on file.")

st.subheader("Upload a document")
first_missing = outstanding[0]["doc_type"] if outstanding else None
upload_form(vendor_id, key=f"docs_{vendor_id}", default_type=first_missing)

st.subheader("On file")
if not docs:
    st.info("No documents uploaded for this vendor yet.")
    st.stop()

table = pd.DataFrame(
    [
        {
            "id": d["id"],
            "type": DOC_TYPES_BY_ID.get(d["doc_type"], {}).get("label", d["doc_type"]),
            "file": d["original_name"],
            "size_kb": round(d["size_bytes"] / 1024, 1),
            "issued": d["issued_on"],
            "expires": d["expires_on"],
            "status": f"{STATUS_ICON[doc_status(d['expires_on'])]} {doc_status(d['expires_on'])}",
            "uploaded": d["uploaded_at"],
        }
        for d in docs
    ]
)
st.dataframe(table, use_container_width=True, hide_index=True)

doc_ids = {f"#{d['id']} — {d['original_name']}": d for d in docs}
pick = st.selectbox("Select a document", list(doc_ids.keys()))
doc = doc_ids[pick]
st.caption(f"SHA-256: `{doc['sha256']}`" + (f" · Notes: {doc['notes']}" if doc["notes"] else ""))
c1, c2 = st.columns(2)
with c1:
    data = read_document(doc["id"])
    if data is None:
        st.error("The stored file is missing from disk.")
    else:
        st.download_button(
            "Download",
            data=data,
            file_name=doc["original_name"],
            mime=doc["content_type"] or "application/octet-stream",
        )
with c2:
    confirm = st.checkbox("Confirm delete", key=f"confirm_del_{doc['id']}")
    if st.button("Delete document", disabled=not confirm):
        delete_document(doc["id"])
        st.success("Deleted.")
        st.rerun()
