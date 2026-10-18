# Current verification — 18 October 2026

The current working tree passed **106 Python tests in 4.09 seconds**, including automatic model discovery/fallback and legacy received-time compatibility. A prior read-only live Sheet check validated **11 inquiries, 0 NEW**. A subsequent model-metadata-only check discovered **18 eligible Gemini text candidates**; no inquiries were read or replies generated during that check. The separate Apps Script intake harness also passed. Python 3.12.14 and Node v24.21.0 were used. All 68 locked package versions matched the installed environment; mandatory dependency metadata was consistent. Syntax/local-link and diff whitespace checks are included in the final verification.

The suite covers the Sheets adapter, safe source/schema validation, padded cells, RAW writes, stable IDs, mixed-status batches, repeat-run protection, configured model traversal/budgets, auth/rate-limit stop behavior, analysis auditing, partial batch persistence, approval and SMTP tracking failures, lost write responses, concurrency exclusion across local threads/processes, read-only guards, complete email preview, filters, and dashboard recovery messages.

Final tests explicitly block live AI/Sheets/SMTP clients unless mocked. They establish behavior against controlled failures, not live Google authorization, account-specific model availability, classification accuracy, or inbox delivery. A development test accidentally reached Gemini with a synthetic inquiry before the client guards were added; the [updated review](project_review_2026-10-15.md) records the incident and correction. No live Sheet data was changed or customer email sent.

Run from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.check_project
node --test tests/test_apps_script.cjs
git diff --check
```

The checked-in quality workflow runs dependency installation/consistency, Python tests, syntax/link checks, and the Node intake check. Its hosted Linux execution and a fresh installation are not yet verified. The local Windows sandbox blocks some temporary-file/socket operations; the complete suite was run outside that restriction with approval.

`python -m scripts.verify_sheets` only reads the configured spreadsheet. For intentional live acceptance, submit a Google Form request using an address you control, process it, inspect the full email preview, approve, and reconcile the Sheet status with Gmail and the receiving inbox. See [email setup](email_setup.md).

Local writer serialization is verified only for processes/threads using the same project directory. Distributed writers, manual Sheet edits, outbox transactions, authentication, deployment, evaluation, accessibility, and larger-source performance are not established by these tests. WhatsApp Business API and website connectors remain future scope.
