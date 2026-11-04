"""VRA-tool-SYLLC — vendor risk assessment dashboard."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.db import list_documents, list_vendors, portfolio_rows
from app.documents import doc_status

st.set_page_config(page_title="VRA-tool-SYLLC", layout="wide")
st.title("Vendor Risk Assessments")
st.caption("SYLLC — intake, score, and track third-party residual risk.")

vendors = list_vendors()
portfolio = portfolio_rows()
completed = [v for v in vendors if v["latest_tier"]]
open_count = len(vendors) - len(completed)
critical = sum(1 for v in vendors if v["latest_tier"] == "Critical")
high = sum(1 for v in vendors if v["latest_tier"] == "High")

doc_statuses = [doc_status(d["expires_on"]) for d in list_documents()]

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Vendors", len(vendors))
c2.metric("Assessed", len(completed))
c3.metric("Not yet assessed", open_count)
c4.metric("Critical / High", critical + high)
c5.metric(
    "Docs expired / expiring",
    f"{doc_statuses.count('Expired')} / {doc_statuses.count('Expiring soon')}",
)

st.subheader("Portfolio")
if not portfolio:
    st.info("Add a vendor, then run an assessment. Use the pages in the sidebar.")
else:
    df = pd.DataFrame(portfolio)
    st.dataframe(df, use_container_width=True, hide_index=True)
    counts = df["tier"].value_counts().reindex(
        ["Critical", "High", "Moderate", "Low"]
    ).fillna(0)
    st.bar_chart(counts)

st.page_link("pages/1_Vendors.py", label="Manage vendors", icon="🏢")
st.page_link("pages/2_Documents.py", label="Upload security documents", icon="📎")
st.page_link("pages/3_Assess.py", label="Run an assessment", icon="📝")
st.page_link("pages/4_History.py", label="Assessment history", icon="📂")
