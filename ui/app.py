"""RiskDesk Streamlit UI: limits, run an investigation, approval queue.

Run:  streamlit run ui/app.py
"""

import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from riskdesk import audit  # noqa: E402
from riskdesk.agents import graph  # noqa: E402
from riskdesk.config import APPROVAL_PATH  # noqa: E402
from riskdesk.guardrails import approval  # noqa: E402
from riskdesk.tools import Session, limit_status  # noqa: E402

st.set_page_config(page_title="RiskDesk", layout="wide")


@st.cache_resource
def base_session():
    return Session.base()


s = base_session()
st.title("RiskDesk")
st.caption("Synthetic book. Python computes every number; agents explain and draft. Nothing is applied without a named reviewer.")

tab_limits, tab_invest, tab_queue = st.tabs(["Limits", "Investigate", "Approval queue"])

with tab_limits:
    rows = limit_status(s)
    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch")
    ok, n = audit.verify()
    st.write(f"Audit chain: {'intact' if ok else 'BROKEN'} ({n} entries)")

with tab_invest:
    if st.button("Run breach investigation on the current book"):
        res = graph.investigate(s, approval_path=APPROVAL_PATH)
        if res["status"] != "breach":
            st.success("No breach in the current book.")
        else:
            st.write(f"Desk {res['desk']}, metric {res['metric']}, utilisation {res['utilisation']:.0%}")
            st.write(f"Classification: {res['classification']}. Escalated: {res['escalate']}. Queue: {res['queue']}.")
            st.write(res["report"]["summary"] if res["report"] else "No valid report: sent to human review.")
            st.caption(f"Run {res['run_id']}. Drafter: {res['drafter']}.")

with tab_queue:
    pending = approval.pending(APPROVAL_PATH)
    if not pending:
        st.info("Nothing pending.")
    for item in pending:
        with st.expander(f"{item['kind']} · {item['desk']} · {item['id']}"):
            st.json(item["payload"])
            reviewer = st.text_input("Reviewer name", key=f"r_{item['id']}")
            note = st.text_input("Note", key=f"n_{item['id']}")
            c1, c2 = st.columns(2)
            if c1.button("Approve", key=f"a_{item['id']}"):
                try:
                    approval.decide(APPROVAL_PATH, item["id"], reviewer, True, note)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            if c2.button("Reject", key=f"x_{item['id']}"):
                try:
                    approval.decide(APPROVAL_PATH, item["id"], reviewer, False, note)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
