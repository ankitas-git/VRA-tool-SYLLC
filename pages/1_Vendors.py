from __future__ import annotations

import pandas as pd
import streamlit as st

from app.db import add_vendor, list_vendors

st.set_page_config(page_title="Vendors — VRA-tool-SYLLC", layout="wide")
st.title("Vendors")

with st.form("new_vendor", clear_on_submit=True):
    st.subheader("Add vendor")
    name = st.text_input("Legal / product name", placeholder="Acme Cloud Inc.")
    col1, col2 = st.columns(2)
    with col1:
        category = st.selectbox(
            "Category",
            ["SaaS", "Infrastructure", "Professional services", "Payments", "HR", "Other"],
        )
        owner = st.text_input("Internal owner", placeholder="Name or team")
    with col2:
        website = st.text_input("Website")
        notes = st.text_area("Notes", height=80)
    submitted = st.form_submit_button("Save vendor")
    if submitted:
        if not name.strip():
            st.error("Name is required.")
        else:
            add_vendor(name, category, owner, website, notes)
            st.success(f"Added {name}.")
            st.rerun()

rows = list_vendors()
if rows:
    df = pd.DataFrame([dict(r) for r in rows])
    show = df[
        ["id", "name", "category", "owner", "latest_tier", "latest_residual", "next_review"]
    ]
    st.dataframe(show, use_container_width=True, hide_index=True)
else:
    st.info("No vendors yet.")
