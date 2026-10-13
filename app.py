import streamlit as st

from models.ticket import CATEGORIES, PRIORITIES, STATUSES
from services.ai_service import analyze_inquiry, analyze_offline, require_gemini_config
from services.config import ConfigurationError, read_only
from services.storage import get_repository
from services.ticket_service import approve_ticket, process_new, retry_ticket

st.set_page_config(page_title="Support Review", page_icon="💬", layout="wide")
st.title("Support Review")
st.caption("AI-assisted triage and response drafts · Human approval required · No messages are sent")


def display_error(exc):
    st.error(str(exc) if isinstance(exc, (ConfigurationError, ValueError)) else
             f"Operation failed ({type(exc).__name__}). Check configuration, source access, and provider availability.")


with st.sidebar:
    st.subheader("Workspace")
    offline = st.toggle("Offline demo", value=True)
    if offline:
        st.info("Uses deterministic examples, not AI. Demo records are stored separately.")
    else:
        st.caption("Uses the configured CSV or Google Sheet and your Gemini account.")
    limit = st.number_input("Tickets per batch", min_value=1, max_value=100, value=6)
    if read_only():
        st.info("Read-only preview. Changes are disabled.")
    if st.button("Process new inquiries", disabled=read_only(), type="primary"):
        try:
            repository = get_repository(offline=offline)
            if not offline:
                require_gemini_config()
            with st.spinner("Preparing response drafts…"):
                result = process_new(repository, analyze_offline if offline else analyze_inquiry, limit=limit)
            st.session_state["notice"] = f"Prepared {result.succeeded} drafts; {result.failed} errors."
            st.rerun()
        except Exception as exc:
            display_error(exc)
    st.button("Refresh tickets", on_click=lambda: None)

try:
    repository = get_repository(offline=offline)
    rows = repository.load()
except Exception as exc:
    display_error(exc)
    st.stop()

if "notice" in st.session_state:
    st.success(st.session_state.pop("notice"))

columns = st.columns(5)
columns[0].metric("Total inquiries", len(rows))
for column, status in zip(columns[1:], ("NEW", "DRAFTED", "APPROVED", "ERROR")):
    column.metric(status.title(), sum(row["status"] == status for row in rows))

st.subheader("Inquiries")
filters = st.columns(3)
status = filters[0].selectbox("Status", ["All", *STATUSES])
priority = filters[1].selectbox("Priority", ["All", *PRIORITIES])
category = filters[2].selectbox("Category", ["All", *CATEGORIES])
visible = [row for row in rows if all(value == "All" or row[field] == value for field, value in
                                     (("status", status), ("priority", priority), ("category", category)))]
if not visible:
    st.info("No inquiries match these filters.")
else:
    st.dataframe([{field: row[field] for field in ("id", "customer_name", "status", "category", "priority", "summary")}
                  for row in visible], hide_index=True, width="stretch")
    selected = st.selectbox("Open inquiry", [row["id"] for row in visible], key=f"ticket_{offline}")
    ticket = next(row for row in visible if row["id"] == selected)
    st.subheader(f"{selected} · {ticket['customer_name']}")
    st.text(ticket["message"])
    if ticket["summary"]:
        st.caption("Suggested analysis — review against the original inquiry")
        st.text(ticket["summary"])
    if ticket["status"] == "DRAFTED":
        with st.expander("Original generated draft"):
            st.text(ticket["draft_reply"])
        with st.form(f"review_{offline}_{selected}"):
            reply = st.text_area("Review and edit response", value=ticket["draft_reply"],
                                 height=180, max_chars=1200)
            submitted = st.form_submit_button("Approve reviewed reply", disabled=read_only())
        if submitted:
            try:
                approve_ticket(repository, selected, reply)
                st.session_state["notice"] = f"Approved {selected}. The response has been saved."
                st.rerun()
            except Exception as exc:
                display_error(exc)
    elif ticket["status"] == "APPROVED":
        st.success("Reviewed and approved")
        st.text(ticket["final_reply"])
        st.caption(f"Reviewed at {ticket['reviewed_at']} (UTC)")
    elif ticket["status"] == "ERROR":
        st.error(ticket["error_message"])
        confirmed = st.checkbox("I have addressed the issue and want to reset this ticket", key=f"retry_{offline}_{selected}")
        if st.button("Reset to NEW", disabled=read_only() or not confirmed):
            try:
                retry_ticket(repository, selected)
                st.rerun()
            except Exception as exc:
                display_error(exc)
    else:
        st.info("This inquiry is waiting to be processed.")
