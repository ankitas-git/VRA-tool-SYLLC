"""Admin sign-in for the Streamlit pages.

The admin password comes from the VRA_ADMIN_PASSWORD environment variable or
`admin_password` in .streamlit/secrets.toml. With neither set, admin features
stay locked.
"""

from __future__ import annotations

import hmac
import os
from typing import Optional

import streamlit as st


def admin_password() -> Optional[str]:
    pw = os.getenv("VRA_ADMIN_PASSWORD")
    if pw:
        return pw
    try:
        return st.secrets.get("admin_password") or None
    except Exception:  # no secrets file
        return None


def is_admin() -> bool:
    return bool(st.session_state.get("is_admin"))


def require_admin() -> bool:
    """Render a sign-in form unless already signed in. Returns True for admins."""
    if is_admin():
        c1, c2 = st.columns([4, 1])
        c1.success("Signed in as admin.")
        if c2.button("Sign out"):
            st.session_state.pop("is_admin", None)
            st.rerun()
        return True
    expected = admin_password()
    if not expected:
        st.warning(
            "Admin access is not configured. Set the `VRA_ADMIN_PASSWORD` environment variable, "
            "or add `admin_password = \"...\"` to `.streamlit/secrets.toml`, then restart the app."
        )
        return False
    with st.form("admin_login"):
        entered = st.text_input("Admin password", type="password")
        if st.form_submit_button("Sign in"):
            if hmac.compare_digest(entered.encode(), expected.encode()):
                st.session_state["is_admin"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False
