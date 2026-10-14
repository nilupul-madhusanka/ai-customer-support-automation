# AI Customer Support Automation Assistant

A Python application that triages support inquiries and creates response drafts for human review. It uses Gemini structured output, Pydantic validation, CSV storage, a Streamlit dashboard, and an optional Google Sheets adapter. Human approval saves the reviewed response and sends it through Gmail SMTP when configured. Offline demo never sends email. See [email setup](docs/email_setup.md) for Google Form, Apps Script, Sheet headers, and Gmail configuration.

## What is this project for?

Small businesses often collect support requests in a spreadsheet or file. Someone must read each message, decide how urgent it is, categorize it, and write a reply. This project automates that first pass while keeping final review with a person.

For example, a customer cannot activate a purchased account and needs it today. The assistant can suggest **Technical Support / High**, summarize the problem, and draft a response asking for details needed to investigate. A reviewer checks the suggestion, edits the wording, and records approval.

This is also an internship portfolio project demonstrating Python, API integration, structured AI output, repeatable automation, error handling, and a human review interface. It is an AI-assisted workflow. The application does not change customer accounts or resolve inquiries autonomously.

## Workflow and features

Google Form / CSV / Google Sheets → select NEW tickets → Gemini analysis → Pydantic validation → save draft → Streamlit review → save approved response → Gmail SMTP.

The lifecycle is `NEW → DRAFTED → APPROVED`. Failed analyses become `ERROR`. After resolving the cause, a reviewer explicitly resets an ERROR ticket to NEW. Drafted and approved records are skipped on later runs.

- Four suggested categories: Billing, Technical Support, Sales, General.
- Three suggested priorities: Low, Medium, High.
- Dashboard counts and filters by status, category, and priority.
- Original inquiry, summary, generated draft, editable reviewed response, and UTC approval timestamp.
- CSV or Sheets storage with unique IDs; these sources are not synchronized.
- Confirmed error reset, read-only preview, and clearly labeled offline fixtures.

**Stack:** Python 3.12, Google Gen AI SDK, Pydantic, Streamlit, Google Sheets API, python-dotenv, pytest.

## Current verified status

Checked against the [project guide](AI_Customer_Support_Automation_Project_Guide.md) on **13 October 2026**:

| Capability | Verification |
|---|---|
| CSV batches and repeat runs | Six-ticket offline batch and automated tests pass |
| Validation, error/reset, edited approval | Tests pass, including final reply and review timestamp |
| Dashboard process/edit/approve/filter flow | Automated Streamlit interaction test passes |
| Gemini structured analysis | Prior live synthetic requests returned valid results; current model/account access rechecked |
| Sheets read/write and retry | Six-row live read, T001 draft write/readback, explicit retry, and processed-ticket skip verified |
| Dashboard with configured Sheets source | Live counts and review form loaded without changing tickets |
| Local dashboard server | HTTP 200 health response |
| Automated checks | **21 tests passed**; installed packages report no dependency conflicts |

The current local configuration uses **Sheets** and `gemini-3.8-flash`. At the last check, T001 was DRAFTED and five tickets were NEW. Statuses change as you use the app. The dashboard starts in **Offline demo** mode; turn it off to view the configured Sheet.

The core MVP works, but the guide's full portfolio checklist is still in progress: screenshots, a demo recording, meaningful feature-level Git history, and GitHub publication remain. A six-ticket *live AI* batch, manual approval against the live Sheet, and classification accuracy evaluation have not been completed in this audit. See the [verification report](docs/project_verification.md).

## Quick start on this computer

The local `.venv` was created using the desktop application's bundled Python 3.12 runtime because the normal Windows Python commands were unavailable. Run from this project folder:

```powershell
.\.venv\Scripts\python.exe main.py --demo
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

The dashboard starts in **Offline demo** mode. Click **Process new inquiries**, open a drafted inquiry, edit its response, and approve it. Offline suggestions are deterministic examples, not AI output. Demo changes persist in `data/demo_tickets.csv`, independently of live records. Repeating the processor skips previously drafted and approved inquiries.

To process NEW tickets in the configured source (currently Sheets), run:

```powershell
.\.venv\Scripts\python.exe main.py --limit 6
```

Open [the dashboard](http://127.0.0.1:8501), turn **Offline demo off**, and select a drafted inquiry. Review the original message and analysis, edit the reply, and click **Approve reviewed reply**. This saves `final_reply` and a UTC `reviewed_at` timestamp, then attempts email when Gmail is configured. Delivery status and manual retries appear in the approved-ticket view. Complete [email setup](docs/email_setup.md) first, including the two new Sheet headers.

## Setup on another computer

Install Python 3.12, then:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe main.py --demo
.\.venv\Scripts\python.exe -m streamlit run app.py
```

On macOS/Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
cp .env.example .env
.venv/bin/python main.py --demo
.venv/bin/python -m streamlit run app.py
```

The macOS/Linux instructions follow the same Python workflow but have not been tested on those systems. Do not overwrite an existing `.env` when repeating setup.

`requirements.txt` specifies supported version ranges; `requirements-lock.txt` captures the environment tested on Windows with Python 3.12. If a platform cannot install the lock, install `requirements.txt` and run the tests before creating a new lock.

## Use Gemini

1. Create an API key in [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Copy `.env.example` to `.env` if it does not exist. Put your key in **only** the local `.env`, and choose a model available to your account. `gemini-3.8-flash` was verified with a synthetic inquiry on this account; availability and pricing can change. The guide's original `gemini-2.5-flash` returned a provider error stating that it is unavailable to new users.
3. Choose `DATA_SOURCE=csv` for file-backed tickets or `DATA_SOURCE=sheets` for your configured Sheet. The current local configuration is Sheets. Run:

```powershell
.\.venv\Scripts\python.exe main.py --limit 6
```

In CSV mode, the working file `data/tickets.csv` is initialized from the unchanged six-ticket synthetic sample if missing. In Sheets mode, the processor uses the configured `Inquiries` tab. Disable **Offline demo** in the dashboard to review live results. The system requires a configured key/model before beginning a live batch, limits messages to 6,000 characters, sets a 30-second request timeout, and disables automatic request retries. API charges and quotas depend on your account.

The SDK request follows the [official Google Gen AI Python SDK](https://googleapis.github.io/python-genai/) JSON Schema interface (`response_json_schema`), with strict local Pydantic validation. This avoids sending the unsupported `additional_properties` field through the older response schema channel. Real Gemini calls require credentials and are separate from unit tests.

## Configuration reference

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Local Gemini key |
| `GEMINI_MODEL` | Model available to your account |
| `DATA_SOURCE` | `csv` or `sheets` |
| `CSV_PATH` | Working CSV path; default `data/tickets.csv` |
| `GOOGLE_SHEET_ID` | Spreadsheet ID for Sheets mode |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Credential JSON path; default `credentials/service-account.json` |
| `DEMO_MODE` | `true` disables processing, approval, and retry |
| `SMTP_HOST`, `SMTP_PORT` | Gmail SMTP host and STARTTLS port; smtp.gmail.com / 587 |
| `SMTP_USER`, `SMTP_PASSWORD` | Sender Gmail address and Google App Password |
| `SMTP_FROM` | Sender display name and mailbox; defaults to SMTP_USER |

Restart the dashboard after editing `.env`. Environment variables set outside the application take precedence over the file.

## Google Sheets (optional)

1. Enable the Sheets API in your Google Cloud project.
2. Create a service account and, if your organization allows it, save its credential JSON as `credentials/service-account.json`.
3. Create an `Inquiries` tab. Import `data/sample_inquiries.csv` with its exact fifteen headers. For an existing 13-column Sheet, add `email_status` in N1 and `emailed_at` in O1.
4. Share only this synthetic demo spreadsheet with the service account as Editor.
5. Set `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_FILE`, and `DATA_SOURCE=sheets` in `.env`.
6. Run the live processor and review the same data with offline mode disabled.

The adapter validates duplicate IDs and headers, pads omitted trailing cells, finds the current row by ticket ID, and writes with `RAW` input so replies are not interpreted as formulas. It uses only the Sheets scope. CSV and Sheets are separate sources; the application does not synchronize them. On this account, live reads, draft writes, error/reset/retry, and repeat-run protection have been verified against the synthetic demo Sheet.

For a new empty demo Sheet, `python -m scripts.verify_sheets --initialize` guards against overwriting data, initializes the expected tab, and verifies one live draft. This command makes a Gemini call for one NEW ticket and switches local configuration to Sheets after successful verification. Do not use it to seed a Sheet containing unrelated data.

The supplied Sheet is already initialized. Running this tool again can process the next NEW ticket; it is a workflow verification tool, not a read-only connection check. On this computer, invoke it using `.\.venv\Scripts\python.exe -m scripts.verify_sheets --initialize`.

## Retry and read-only preview

Failed requests become `ERROR`; exception types are saved without raw API payloads or customer content. Fix the underlying issue, then reset a single failed ticket:

```powershell
.\.venv\Scripts\python.exe main.py --retry T001
# For offline records, add --demo.
```

The dashboard provides the same reset with a confirmation checkbox. Resetting does not immediately call the API. Only `ERROR` tickets may be reset, and only `DRAFTED` tickets may be approved. Empty or overlong reviewed responses are rejected.

For a fresh offline walkthrough, stop the dashboard and rename `data/demo_tickets.csv` to an unused backup filename. The next `main.py --demo` run recreates six synthetic NEW records without changing the configured live source. Preserve live and approved records when staging demos.

Set `DEMO_MODE=true` for a read-only preview that disables processing, approval, and retry in both business services and the dashboard. It still initializes a missing local CSV from synthetic samples. This local application has no user authentication; keep it bound to localhost. A private hosted workflow needs authentication before allowing edits.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests cover persisted batches, skipped repeat runs, failure/retry, review transitions, input/output validation, read-only guards, storage failures, mocked Gemini and Sheets calls, and the dashboard's process/edit/approve/filter flow. No test requires API credentials or contacts customers.

The expanded checks also reject malformed CSV rows/headers and missing IDs, and verify that mixed-status batches preserve approved, drafted, and failed tickets.

## Project structure

| Location | Responsibility |
|---|---|
| `main.py` | CLI batch processing and explicit retry |
| `app.py` | Dashboard and human review interface |
| `models/ticket.py` | Analysis contract, columns, stored-row validation |
| `services/ai_service.py` | Gemini requests and offline fixtures |
| `services/ticket_service.py` | Processing, approval, and retry rules |
| `services/storage.py` | CSV repository and source selection |
| `services/sheets_service.py` | Google Sheets repository |
| `services/config.py` | Configuration and read-only guard |
| `services/email_service.py` | Gmail SMTP with verified STARTTLS |
| `google_apps_script.js` | Google Form submission intake into Inquiries |
| `scripts/verify_sheets.py` | Guarded initialization and live workflow verification |
| `data/sample_inquiries.csv` | Six fictional seed inquiries |
| `tests/` | Workflow, validation, API, and dashboard checks |

See [architecture](docs/architecture.md), [demo walkthrough](docs/demo_script.md), and [development status](docs/development_status.md). The original project guide remains unchanged.

## Limitations

CSV and Sheets assume one writer at a time. Status checks and atomic CSV replacement do not provide concurrent worker locks. Sheets updates replace a whole row. A crash after analysis but before saving can cause another API call on retry. Structured outputs do not guarantee factual correctness, so a reviewer remains responsible for drafts. Classification accuracy and prompt-injection resistance have not been evaluated. Fresh installation on a second computer and deployment have not been verified.

Next steps are screenshots and a demo recording, manual live approval and a six-ticket live batch, accuracy evaluation, and improved error guidance. A database, audit history, authentication, automatic bounded retries, category charts, agent frameworks, and deployment are future extensions.
