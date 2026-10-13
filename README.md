# AI Customer Support Automation Assistant

A Python application that triages support inquiries and creates response drafts for human review. It uses Gemini structured output, Pydantic validation, CSV storage, a Streamlit dashboard, and an optional Google Sheets adapter. Approval saves a reviewed response; it never sends email.

## Quick start on this computer

The local `.venv` was created using the desktop application's bundled Python 3.12 runtime because the normal Windows Python commands were unavailable. Run from this project folder:

```powershell
.\.venv\Scripts\python.exe main.py --demo
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

The dashboard starts in **Offline demo** mode. Click **Process new inquiries**, open a drafted inquiry, edit its response, and approve it. Offline suggestions are deterministic examples, not AI output. Demo changes persist in `data/demo_tickets.csv`, independently of live records. Repeating the processor skips previously drafted and approved inquiries.

## Setup on another computer

Install Python 3.12, then:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
```

`requirements.txt` specifies supported version ranges; `requirements-lock.txt` captures the environment tested on Windows with Python 3.12. If a platform cannot install the lock, install `requirements.txt` and run the tests before creating a new lock.

## Use Gemini

1. Create an API key in [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Copy `.env.example` to `.env` if it does not exist. Put your key in **only** the local `.env`, and choose a model available to your account. `gemini-2.5-flash` is the guide's example, not a guarantee of availability or free access.
3. Leave `DATA_SOURCE=csv`. Run:

```powershell
.\.venv\Scripts\python.exe main.py --limit 6
```

The working CSV `data/tickets.csv` is initialized from the unchanged six-ticket synthetic sample. Disable **Offline demo** in the dashboard to review those live results. The system requires a configured key/model before beginning a live batch, limits messages to 6,000 characters, sets a 30-second request timeout, and disables automatic request retries. API charges and quotas depend on your account.

The SDK request follows the [official Google Gen AI Python SDK](https://googleapis.github.io/python-genai/) structured response schema interface. Real Gemini calls require credentials and are separate from unit tests.

## Google Sheets (optional)

1. Enable the Sheets API in your Google Cloud project.
2. Create a service account and, if your organization allows it, save its credential JSON as `credentials/service-account.json`.
3. Create an `Inquiries` tab. Import `data/sample_inquiries.csv` with its exact twelve headers.
4. Share only this synthetic demo spreadsheet with the service account as Editor.
5. Set `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_FILE`, and `DATA_SOURCE=sheets` in `.env`.
6. Run the live processor and review the same data with offline mode disabled.

The adapter validates duplicate IDs and headers, pads omitted trailing cells, finds the current row by ticket ID, and writes with `RAW` input so replies are not interpreted as formulas. It uses only the Sheets scope. CSV and Sheets are separate sources; the application does not synchronize them. The adapter has mocked tests; verification against a real Sheet requires your credentials.

## Retry and read-only preview

Failed requests become `ERROR`; exception types are saved without raw API payloads or customer content. Fix the underlying issue, then reset a single failed ticket:

```powershell
.\.venv\Scripts\python.exe main.py --retry T001
# For offline records, add --demo.
```

The dashboard provides the same reset with a confirmation checkbox. Resetting does not immediately call the API. Only `ERROR` tickets may be reset, and only `DRAFTED` tickets may be approved. Empty or overlong reviewed responses are rejected.

Set `DEMO_MODE=true` for a read-only preview that disables processing, approval, and retry in both business services and the dashboard. It still initializes a missing local CSV from synthetic samples. This local application has no user authentication; keep it bound to localhost. A private hosted workflow needs authentication before allowing edits.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests cover persisted batches, skipped repeat runs, failure/retry, review transitions, input/output validation, read-only guards, storage failures, mocked Gemini and Sheets calls, and the dashboard's process/edit/approve/filter flow. No test requires API credentials or contacts customers.

See [architecture](docs/architecture.md), [demo walkthrough](docs/demo_script.md), and [development status](docs/development_status.md). The original project guide remains unchanged.

## Limitations

CSV and Sheets assume one writer at a time. Status checks and atomic CSV replacement do not provide concurrent worker locks. A crash after analysis but before saving can cause another API call on retry. Structured outputs do not guarantee factual correctness, so a reviewer remains responsible for drafts. Live provider accuracy, quota behavior, and Sheet permissions require integration verification. Screenshots and a demo recording should be captured after that verification if presented as real AI results.
