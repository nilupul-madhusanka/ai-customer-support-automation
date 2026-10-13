# Development status

Implemented from the project guide:

- Typed analysis schema and stored-row validation.
- Gemini SDK adapter with timeout and validated structured output.
- CSV processing, separate immutable seed data, and repeat-run protection.
- Streamlit filters, review/edit/approve flow, approved response display, and explicit error retry.
- Optional Google Sheets adapter with stable ID lookup and RAW writes.
- Offline demo fixtures, read-only guard, configuration templates, architecture, demo walkthrough, and automated tests.

Current status after the overall project audit:

- Gemini and Sheets credentials work; live analysis and draft read/write were verified in the follow-ups below.
- The configured Sheets view and draft review form load correctly. This audit preserved all live ticket values.
- The expanded automated suite passes **21 tests**; installed dependencies report no conflicts.
- Full live-batch/manual approval evaluation, screenshots, demo recording, feature-level Git history, and GitHub publication remain. See `project_verification.md` for the acceptance mapping.

No credentials were created, no live AI requests were made, no customer messages were sent, and no public deployment was created during initial implementation.

## Initial local verification

- Python 3.12.14 project environment created and dependencies installed.
- `python -m pytest -q`: **16 passed** (13 October 2026), including Streamlit process/edit/approve/filter testing.
- First offline CLI run: 6 drafted, 0 errors.
- Second offline CLI run: 0 drafted, 6 skipped.
- Live CLI without a key: configuration error before any live ticket is processed.
- Dependency versions captured in `requirements-lock.txt`.
- Git repository initialized locally; publishing and commits remain to be arranged.

The default sandbox blocked the test framework's temporary directories; tests passed when executed with approved filesystem access.

## Earlier credential verification follow-up

- Gemini key authenticated successfully and a live synthetic invoice inquiry returned a validated Billing / Low result.
- Changed the configured model to `gemini-3.8-flash`, following the provider's replacement recommendation for this account.
- Fixed the SDK request to use `response_json_schema`; all 16 automated tests pass after the change.
- Google service-account authentication and spreadsheet metadata access succeeded. The initial token timing rejection did not recur on subsequent checks; local clock and token lifetime checks were normal.
- At that earlier check, the spreadsheet had one empty `Sheet1` tab. It was subsequently initialized in the authorized follow-up below.
- Verification did not modify spreadsheet data or process live CSV tickets.

## Authorized Sheets initialization and live workflow

- Renamed the empty `Sheet1` tab to `Inquiries` and populated the twelve required headers and six synthetic tickets, after user approval.
- Confirmed that all six rows read back through the project repository with valid headers and unique IDs.
- Gemini initially returned a server error for T001. The workflow correctly saved ERROR; one explicit reset/retry then saved a validated Technical Support / High draft.
- Read the draft back from Sheets and verified that a repeat run scoped to the processed ticket skipped it without another AI call or write.
- T001 is DRAFTED awaiting human review. The remaining five tickets are NEW. No replies were approved or sent during verification.
- Switched local `DATA_SOURCE` to `sheets` after successful read/write verification.
- Added `python -m scripts.verify_sheets --initialize` for guarded empty-Sheet initialization and one-ticket live verification. Existing valid Inquiries data is preserved on reruns. Running this tool may analyze the next NEW ticket; `--retry-ticket T001` explicitly resets an ERROR ticket before verification.
