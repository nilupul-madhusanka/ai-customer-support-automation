import streamlit as st
from datetime import datetime, timezone

from models.ticket import CATEGORIES, PRIORITIES, STATUSES, EMAIL_STATUSES
from services.ai_service import analyze_inquiry, require_gemini_config, model_policy
from services.config import ConfigurationError, read_only
from services.errors import public_error
from services.email_service import build_reply
from services.storage import get_repository
from services.ticket_service import approve_ticket, delivery_preflight, process_new, retry_ticket, send_approved_email

st.set_page_config(page_title="Support Review", page_icon="💬", layout="wide")
st.title("Support Review")
st.caption("AI-assisted triage and response drafts · Human approval required · Approved replies are emailed")


def display_error(exc):
    st.error(public_error(exc))


def utc_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()


try:
    locked = read_only()
except ConfigurationError as exc:
    display_error(exc)
    st.stop()
st.caption(f"Google Sheets · {'Read-only' if locked else 'Changes enabled'} · Gmail SMTP acceptance is tracked separately from approval")


with st.sidebar:
    st.subheader("Workspace")
    st.caption("Source: Google Sheets · Analysis: Gemini")
    st.caption("Planned sources: WhatsApp Business API and website customer requests.")
    limit = st.number_input("Tickets per batch", min_value=1, max_value=100, value=6)
    try:
        policy = model_policy()
        mode = "Automatic Gemini model discovery" if policy.auto_discover else "Configured Gemini models"
        st.caption(f"{mode} · up to {policy.max_attempts} attempts per inquiry, {policy.seconds}s request budget. No automatic rate-limit retries.")
    except ConfigurationError as exc:
        st.warning(public_error(exc))
    if locked:
        st.info("Read-only preview. Changes are disabled.")
    if st.button("Process new inquiries", disabled=locked, type="primary"):
        try:
            repository = get_repository()
            require_gemini_config()
            with st.spinner("Preparing response drafts…"):
                progress = st.empty()
                result = process_new(repository, lambda message: analyze_inquiry(message, report=progress.caption),
                                     limit=limit, report=progress.caption)
            st.session_state["notice"] = f"Prepared {result.succeeded} drafts; {result.failed} errors; {result.skipped} skipped/deferred."
            if result.stopped_reason:
                st.session_state["warning"] = result.stopped_reason
            st.rerun()
        except Exception as exc:
            display_error(exc)
    st.button("Refresh tickets", on_click=lambda: None)

try:
    repository = get_repository()
    rows = repository.load()
except Exception as exc:
    display_error(exc)
    st.stop()

if "notice" in st.session_state:
    st.info(st.session_state.pop("notice"))
if "warning" in st.session_state:
    st.warning(st.session_state.pop("warning"))

columns = st.columns(5)
columns[0].metric("Total inquiries", len(rows))
for column, status in zip(columns[1:], ("NEW", "DRAFTED", "APPROVED", "ERROR")):
    column.metric(status.title(), sum(row["status"] == status for row in rows))

st.subheader("Inquiries")
search = st.text_input("Search name, email, or inquiry ID").strip().casefold()
filters = st.columns(3)
status = filters[0].selectbox("Status", ["All", *STATUSES])
priority = filters[1].selectbox("Priority", ["All", *PRIORITIES])
category = filters[2].selectbox("Category", ["All", *CATEGORIES])
delivery = st.selectbox("Delivery", ["All", "Unsent approved", "Uncertain", *[value for value in EMAIL_STATUSES if value]])
visible = [row for row in rows if all(value == "All" or row[field] == value for field, value in
                                     (("status", status), ("priority", priority), ("category", category)))
           and (not search or any(search in row[field].casefold() for field in ("id", "customer_name", "customer_email")))
           and (delivery == "All" or
                delivery == "Unsent approved" and row["status"] == "APPROVED" and row["email_status"] != "SENT" or
                delivery == "Uncertain" and row["status"] == "APPROVED" and row["email_status"] in ("SENDING", "UNKNOWN", "") or
                row["email_status"] == delivery)]
if not visible:
    st.info("No inquiries match these filters.")
else:
    st.dataframe([{field: row[field] for field in ("id", "received_at", "customer_name", "customer_email", "status", "category", "priority", "email_status", "summary")}
                  for row in visible], hide_index=True, width="stretch")
    selected = st.selectbox("Open inquiry", [row["id"] for row in visible], key="ticket")
    ticket = next(row for row in visible if row["id"] == selected)
    st.subheader(f"{selected} · {ticket['customer_name']}")
    if ticket.get("customer_email"):
        st.caption(f"📧 {ticket['customer_email']}")
    st.text(ticket["message"])
    if ticket["summary"]:
        st.caption("Suggested analysis — review against the original inquiry")
        st.text(ticket["summary"])
    if ticket["status"] == "DRAFTED":
        with st.expander("Original generated draft"):
            st.text(ticket["draft_reply"])
        st.caption("Review the complete outgoing email before approval. Approval saves the reply and attempts sending when Gmail is configured.")
        reply = st.text_area("Review and edit response", value=ticket["draft_reply"],
                             height=180, max_chars=1200, key=f"reply_{selected}")
        reason = delivery_preflight(ticket)
        if reason:
            st.info(reason + " You can still save approval.")
        with st.expander("Complete outgoing email preview"):
            try:
                preview = build_reply(ticket["customer_email"], ticket["customer_name"], selected, reply.strip())
                st.text(f"To: {preview['To']}\nFrom: {preview['From']}\nSubject: {preview['Subject']}")
                st.text(preview.get_content())
            except ValueError:
                st.info("Configure a valid customer email and SMTP sender to see the full email preview.")
        submitted = st.button("Approve reply" if reason else "Approve and send email", disabled=locked)
        if submitted:
            try:
                outcome = approve_ticket(repository, selected, reply)
                st.session_state["notice"] = outcome.message
                if not outcome.delivery.tracking_saved or outcome.delivery.smtp_accepted is not True:
                    st.session_state["warning"] = outcome.message
                st.rerun()
            except Exception as exc:
                display_error(exc)
    elif ticket["status"] == "APPROVED":
        st.success("Reviewed and approved")
        st.text(ticket["final_reply"])
        st.caption(f"Reviewed at {utc_time(ticket['reviewed_at'])} (UTC)")
        if ticket["email_status"] == "SENT":
            st.success(f"Email accepted by Gmail at {utc_time(ticket['emailed_at'])} (UTC).")
        else:
            recovery = ticket["error_message"] or "Approved response has no confirmed email send recorded."
            uncertain = ticket["email_status"] in ("SENDING", "UNKNOWN", "")
            if uncertain:
                st.warning("Delivery is uncertain. Check Gmail Sent before confirming a retry; a duplicate is possible.")
            else:
                st.warning(delivery_preflight(ticket) or recovery)
            confirmed = False
            if uncertain:
                confirmed = st.checkbox("I checked Gmail Sent and want to retry; this may send a duplicate", key=f"email_retry_{selected}")
            if st.button("Send approved email", disabled=locked or (uncertain and not confirmed)):
                try:
                    outcome = send_approved_email(repository, selected, confirm_uncertain=confirmed)
                    st.session_state["notice"] = outcome.message
                    if not outcome.tracking_saved:
                        st.session_state["warning"] = outcome.message
                    st.rerun()
                except Exception as exc:
                    display_error(exc)
    elif ticket["status"] == "ERROR":
        st.error(ticket["error_message"])
        confirmed = st.checkbox("I have addressed the issue and want to reset this ticket", key=f"retry_{selected}")
        if st.button("Reset to NEW", disabled=locked or not confirmed):
            try:
                retry_ticket(repository, selected)
                st.rerun()
            except Exception as exc:
                display_error(exc)
    else:
        st.info("This inquiry is waiting to be processed.")
