# AI Customer Support Automation Agent

An online support workflow that reads customer inquiries from Google Sheets, uses Gemini to prepare analysis and reply drafts, and presents them in Streamlit for human review. Approval saves the reviewed response and attempts delivery through Gmail SMTP when configured.

Google Sheets is the only supported inquiry source in this version. Google Forms can feed the Sheet through the included Apps Script. WhatsApp Business API messages and website-integrated customer requests are planned for later updates; their connectors are not implemented yet.

## Workflow

Google Form → Apps Script → Google Sheets Inquiries → Gemini analysis → saved draft → human review → approval → Gmail SMTP.

The processor selects NEW inquiries, validates structured AI output, and saves DRAFTED or ERROR status. Repeat runs skip drafted, approved, and failed inquiries. Reviewers can edit replies, approve them, and explicitly retry failed analysis or email delivery. The application does not change customer accounts or resolve requests autonomously.

## Setup

Use Python 3.12 for the tested environment. Node.js 22 or later is required for the Apps Script checks (not for running the Python application). On Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
```

Configure `.env` with your Gemini key/model, Google Sheet ID, service account credential file, and optional Gmail SMTP credentials. Keep credentials outside version control.

1. Enable the Google Sheets API and create a service account.
2. Share the intended spreadsheet with the service account as Editor.
3. Create an `Inquiries` tab with the following headers in A1 through O1:

```text
id,received_at,customer_name,customer_email,message,status,category,priority,summary,draft_reply,final_reply,reviewed_at,error_message,email_status,emailed_at
```

New inquiries need a unique nonblank ID, received time, customer details, message, and `NEW` status. Leave workflow fields blank. An empty tab with the correct headers is valid. For Google Forms intake and email configuration, follow [email setup](docs/email_setup.md).

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_sheets
.\.venv\Scripts\python.exe main.py --limit 6
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The verification command only reads and validates the Sheet. The processor calls Gemini and saves drafts; it does not send email. Open [the dashboard](http://127.0.0.1:8501) to review and approve replies. Approval attempts email delivery when Gmail is configured.

## Configuration

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Gemini API credential |
| `GEMINI_MODEL` | Optional preferred model; automatically discovered candidates follow it |
| `GEMINI_AUTO_DISCOVER` | Automatically discover Gemini text-generation models; defaults to `true` |
| `GEMINI_FALLBACK_MODELS` | Optional preferred fallbacks before discovered models; may be left empty |
| `GEMINI_MAX_ATTEMPTS` | Maximum model attempts per inquiry, 1–5; default 3 |
| `GEMINI_TIME_BUDGET_SECONDS` | Request scheduling/timeout budget per inquiry, 1–120 seconds; default 90 |
| `DATA_SOURCE` | `sheets`; defaults to Sheets when omitted |
| `GOOGLE_SHEET_ID` | Spreadsheet ID |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Credential path; defaults to `credentials/service-account.json` |
| `READ_ONLY` | `true` disables processing, approval, and retry; default `false` |
| `ANALYSIS_AUDIT_PATH` | Redacted analysis history; defaults to `var/analysis_attempts.jsonl` |
| `SMTP_HOST`, `SMTP_PORT` | SMTP server; normally `smtp.gmail.com` and `587` |
| `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Gmail sender and app password; see email setup |

Earlier installations should set `DATA_SOURCE=sheets`, remove `CSV_PATH` and `DEMO_MODE`, and use `READ_ONLY=true` if changes should be disabled. File-backed processing, automatic seed records, simulated AI, and the `--demo` option have been removed. Existing local ticket files and backups are not read, imported, or deleted by the application. Legacy `DEMO` delivery statuses are no longer accepted in Sheets; inspect any such records before using them as live inquiries.

## Retry and review

```powershell
.\.venv\Scripts\python.exe main.py --retry TICKET_ID
```

This resets an ERROR inquiry to NEW without processing it. In the dashboard, approval preserves the original draft and saves the edited final response with a UTC timestamp. Email failures preserve approval. Uncertain deliveries require checking Gmail Sent and explicit confirmation before retrying, because SMTP and Sheets cannot commit together.

The dashboard previews the full outgoing email, including its recipient, sender, subject, greeting, and reference. **Approve and send email** appears when recipient and basic SMTP settings are present; **Approve reply** saves approval when sending is not ready. Delivery status and search filters help find unsent or uncertain approvals. Approval, SMTP acceptance, and successful delivery-status persistence are separate outcomes.

If an approval write loses its response, the service tries to confirm the saved reply. It never sends email on that recovery path. Refresh the Sheet before choosing the next action. If analysis stops partway through a batch, completed drafts stay saved and the UI/CLI reports processed and deferred totals.

Automatic fallback discovers general-purpose Gemini models through the model-list API using your configured key, caches the catalog for five minutes per credential fingerprint, and prefers stable Flash candidates before Pro/preview candidates. Specialized image/audio/live/embedding models are excluded. Preferred models are tried first, then deduplicated discovered candidates, within the total attempt/time budget. The dashboard and CLI show each model attempt. Catalog membership does not guarantee current serving capacity or structured-output compatibility; generation still validates the schema. See Google's [model API](https://ai.google.dev/api/models) and [structured output documentation](https://ai.google.dev/gemini-api/docs/structured-output).

Temporary server failures, per-model timeouts, missing candidates, incompatible fallback requests, and invalid/empty responses in automatic mode can advance to the next candidate. Each request receives a share of the remaining time so later candidates have a chance. Authentication, rate limits, provider retry guidance, and non-timeout connection failures stop the batch and leave unprocessed tickets NEW. Discovery failure can still use explicitly configured models; without any candidate it reports a discovery error. SDK automatic retries are disabled. The budget limits scheduling and request timeouts; it is not a hard wall-clock cancellation guarantee for the synchronous SDK. Set `GEMINI_AUTO_DISCOVER=false` to use only explicitly configured models.

Check model discovery without reading inquiries or generating replies:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_models
```

Redacted local history records ticket ID, timestamp, correlation ID, model attempts/outcomes, and the successful model. It excludes customer messages, generated replies, credentials, and provider payloads. `GENERATED` records mean analysis succeeded, not that the Sheet write committed. Keep `var/` private, writable, and outside version control. This is diagnostic storage, not an offline inquiry source or a transactional audit/outbox.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.check_project
node --test tests/test_apps_script.cjs
```

Tests exercise the Sheets adapter using mocked Google API responses, mocked Gemini output, dashboard interactions, concurrent writers, storage failures, and controlled SMTP behavior. External AI, Sheets, and SMTP clients are blocked by default and must be explicitly mocked. The final suite does not contact live services. The checked-in quality workflow runs Python, intake, syntax/link, and dependency checks. See the current [verification](docs/project_verification.md), [review](docs/project_review_2026-10-15.md), [architecture](docs/architecture.md), and [development status](docs/development_status.md).

## Limits and planned work

The application enforces one writer per Sheet within the same local project directory using a nonblocking OS lock across threads and processes. A busy action is rejected with refresh/retry guidance. Keep `var/locks` in place while the app runs. This does not coordinate separate checkouts, computers, manual Sheet edits/sorting, or external scripts. Sheets updates replace a whole row and do not provide transactional claims; shared hosting still needs a transactional repository/outbox and authentication.

Stored records enforce reply lengths, timezone-aware review/email timestamps, safe IDs, and status-dependent review/delivery fields. Date-only legacy received dates remain readable; 13-column headers are readable but cannot be written until N/O are added. Blank historical approved email status remains uncertain and requires reconciliation. Malformed records are rejected with a safe Sheet row/field diagnostic; they are never silently rewritten. Check existing historical records before using the stricter validation.

Legacy ISO received timestamps without a timezone are interpreted using the spreadsheet's **File → Settings → Time zone**, preserving their local clock time. Reading does not modify source data; a later normal workflow write can save the equivalent value with an explicit offset. Review/email times remain strict. Ambiguous daylight-saving times require an explicit offset.

AI output requires human review. Messages are limited to 6,000 characters and reviewed replies to 1,200. Provider quotas and API costs apply. The app has no user authentication; keep local access restricted until authentication is added for hosting.

Upcoming integrations are WhatsApp Business API intake and website customer requests. Channel-specific replies, authentication, deployment, transactional audit/outbox history, and accuracy evaluation require further work.
