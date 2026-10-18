# Project core workflow review and fixes

Original review: 15 October 2026. Follow-up and remediation: **18 October 2026 (Asia/Colombo)**.

Reviewed baseline: `e43543b`, plus the current uncommitted online-only changes and this remediation. This report describes the working tree, not a new commit or deployed release. The [original report](reviews/project_review_2026-10-15_original.md) is preserved as historical evidence; its CSV/demo recommendations no longer describe the product scope.

## Current assessment

The core workflow is suitable for continued local development using Google Sheets with one installation. The original defects have been fixed or mitigated for this local operating model. Automated tests cover the previously reproduced failures. This is not a claim of production readiness, distributed single-writer safety, live account compatibility, or measured AI accuracy.

Google Sheets is the only supported inquiry source. Google Forms intake uses the maintained root-level `google_apps_script.js`. WhatsApp Business API and website customer-request connectors remain planned for later releases. Offline demonstrations, file-backed inquiry processing, synthetic runtime analysis, and automatic seed records remain removed.

## Original findings: disposition

| Finding | Current status | Implementation and evidence |
| --- | --- | --- |
| F1: missing Form intake source | Fixed in the current working tree | The maintained Apps Script source is present at the project root; setup references it and `node --test tests/test_apps_script.cjs` passes. Its restoration was already present when this follow-up began and was preserved. No external Google trigger was changed. |
| F2: fallback traversal and unbounded work | Fixed; automatic discovery added at user request | Removed guessed fallback names. Gemini's model catalog now supplies general-purpose text candidates automatically; preferred/manual models remain first. Metadata is cached five minutes per credential fingerprint. Missing/incompatible candidates, server failures, timeouts, and bad output can advance to another candidate in automatic mode. Authentication, 429, and provider Retry-After stop without evasion. Attempts and shared request timeouts remain bounded. Actual model/outcome metadata is recorded without provider payloads. |
| F3: approval saved but generic failure displayed | Fixed | `ApprovalResult` and `DeliveryResult` distinguish approval, send attempt, SMTP acceptance, tracking persistence, and last known delivery state. Intent-write, failure-tracking, and acceptance-tracking failures return explicit partial outcomes. The dashboard reruns with saved approval and a warning. |
| F4: concurrent duplicate email actions | Mitigated for this local release; shared-use blocker remains | A nonblocking OS lock covers complete operations across threads/processes using the same project directory, keyed by Sheet ID. Direct adapter writes use it too. Send claims also check expected email state. Simultaneous send/process tests and a subprocess lock test pass. Separate installations and external Sheet edits are not coordinated; transactional claims/outbox are still required before shared hosting. |
| F5: raw validation text in dashboard | Fixed | Only explicit application errors are exposed through `public_error`. `StoredTicket` failures become safe row/field diagnostics, never raw Pydantic input or provider text. UI and CLI use the same message boundary. Sentinel-value regression checks pass. |
| F6: weak stored approval validation | Fixed with explicit legacy handling | Typed stored tickets enforce 1–1200-character approved replies, valid timezone-aware review/email timestamps, safe unique IDs, and status-dependent delivery/review fields. Date-only legacy received dates and blank historical approved email status remain readable. Old 13-column Sheets remain read-only until N/O headers are added. Invalid records are rejected, not silently migrated. |
| F7: recovery reasons vanish after refresh | Fixed | Missing recipient and SMTP reasons are persisted without erasing uncertain delivery state. The dashboard recomputes preflight guidance when reopening unsent approvals. Reload tests cover persisted reasons and UI recovery guidance. |
| F8: stale docs and incomplete verification | Fixed for the working tree | README, architecture, setup, status, and current verification agree with the online-only application. The old review is explicitly historical. Required Python and intake checks are documented separately and included in `.github/workflows/checks.yml`, alongside dependency and syntax/link checks. Hosted CI has not yet run. |

## Second review of the core logic

The follow-up reread `models/ticket.py`, AI configuration and analysis, storage/update validation, the Sheets adapter, processing/approval/retry services, SMTP message construction, the dashboard, CLI, verification script, and intake source/tests. The focus was what happens when an external call partially succeeds, fails, repeats, or races.

Additional corrections made during this pass:

1. **An approval write can commit and lose its response.** On an exception, the service reads back the exact reply, timestamp, and approval fields. If confirmed, it reports saved approval with no email attempt. If readback is unavailable or inconsistent, it reports unknown approval and tells the reviewer to refresh. It never sends email on this recovery path. Tests cover commit-then-timeout and write-plus-readback failure.
2. **Global provider failures must not turn every selected inquiry into ERROR.** Classified auth/configuration/rate-limit/connection/exhausted-budget failures stop the batch, preserve remaining NEW records, and report already completed and deferred totals. Empty/invalid model output remains a per-ticket failure requiring an explicit reset.
3. **Batch storage failures need partial results.** A failure saving audit or draft state stops further work and returns completed/deferred totals, without disguising it as an AI failure or rewriting prior successful drafts. A lost save response requires a refresh before retrying.
4. **Human review must include the actual outgoing message.** Preview and SMTP now share `build_reply`, including sender, recipient, subject, greeting, signature, and ticket reference. Edited reply text updates the preview before approval. Delivery status/filtering and search expose unsent or uncertain approvals.
5. **Timestamp and validation presentation must remain accurate.** Review/email timestamps are normalized to UTC for UTC-labeled UI output. Safe validation messages identify actual Sheet row numbers even when blank rows are present. Invalid READ_ONLY values fail closed.
6. **Tests must never inherit live clients accidentally.** AI, Sheets, and SMTP clients are now blocked by default unless explicitly mocked. New UI checks identify actions by label rather than position.

The AI prompt retains a clear human-review boundary: customer text is untrusted, output must match strict category/priority/length/schema rules, and drafts must not invent policies, refunds, resolutions, or timelines. These constraints reduce some failure modes; they do not measure or guarantee factual correctness or instruction-attack resistance.

## Core invariants now checked

| Stage | Invariant |
| --- | --- |
| Source load | Valid schema, unique safe IDs, deliberate legacy header behavior, safe diagnostics; no local source fallback |
| Processing | Only NEW records are analyzed; one local writer; bounded model policy; schema validation before saving |
| Retry | Only ERROR → NEW; clear previous analysis; no implicit processing or send |
| Approval | Preserve original draft; validate edited response; save approval before any SMTP attempt |
| Delivery claim | Require APPROVED; expected email state; save SENDING before contacting SMTP |
| Definite SMTP rejection | Preserve approval/final reply; record FAILED when possible; provide recovery guidance |
| Uncertain SMTP outcome | Record UNKNOWN or retain SENDING; require Gmail Sent reconciliation and explicit confirmation |
| Accepted but tracking failed | Report known SMTP acceptance and failed persistence; do not automatically resend |
| Repeat/concurrent actions | SENT skips sending; stale workflow/email state conflicts; competing local operations report busy |
| Diagnostics | No customer message, draft, credential, or provider payload in analysis attempt history |

## Verification on 18 October 2026

| Check | Result |
| --- | --- |
| Python suite | **106 passed in 4.09 seconds**, including automatic discovery, candidate filtering/caching, fallback after 504/timeouts, legacy timestamps, dashboard, provider failure, partial-write, and concurrency checks |
| Apps Script intake | **Passed** as a separate Node test-file harness; covers setup, duplicate headers, incomplete submissions, repeat events, and recovery after append |
| Python syntax and local Markdown links | Checked using `python -m scripts.check_project`; counts are printed by that command |
| Dependency lock | All **68** locked package versions match the installed environment |
| Mandatory dependency metadata | No missing/incompatible mandatory requirements found in installed distributions |
| Git diff whitespace | Checked with `git diff --check` |
| Runtime | Python 3.12.14; Node v24.21.0. CI targets Python 3.12 and Node 22 on Linux but has not been executed here |

The final suite blocks external AI/Sheets/SMTP by default. During development, one new dashboard test selected the process button by positional index while intending to refresh, and reached Gemini using a synthetic inquiry from a mocked repository. That test was corrected and the external-client guards were added. No live Sheet writes or customer emails occurred. The final passing suite made no live-service calls. This follow-up did not perform a live end-to-end acceptance run.

The sandbox restricted temporary files and Windows socket creation, so the full suite was run with approval outside that restriction. Dependency consistency was checked from installed metadata because the local environment does not provide pip. Fresh installation, dependency vulnerability review, visual/browser accessibility checks, account-specific model availability, deployed Google triggers, and hosted CI remain unverified.

Reproduction commands (project root):

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.check_project
node --test tests/test_apps_script.cjs
git diff --check
```

For a read-only live source check, use `python -m scripts.verify_sheets`; it does not initialize data, call AI, or change local configuration. For intentional live end-to-end acceptance, follow [email setup](email_setup.md).

## Configuration and migration notes

After a reported startup error, a read-only check of B2 confirmed a legacy value `2026-10-13T09:00:00` without an offset, in a Sheet configured for Asia/Colombo. The adapter now interprets legacy ISO received datetimes in the actual spreadsheet timezone; it does not guess the machine timezone or relax reviewed/email times. Ten regression cases cover offsets, date-only values, different zones, invalid values, and daylight-saving ambiguity. A subsequent **read-only live check validated all 11 inquiries**, with 0 NEW inquiries, without changing records, calling Gemini, or sending email. This confirms source access/validation only, not end-to-end acceptance.

- Google Sheet columns remain A:O; no model metadata columns were added or live data rewritten.
- At the user's request, automatic model discovery now defaults to enabled (`GEMINI_AUTO_DISCOVER=true`). Optional preferred/manual models are followed by discovered candidates, filtered for general-purpose Gemini text generation and cached five minutes. Discovery does not prove current capacity or structured-output compatibility. A metadata-only live check found 18 eligible candidates; with the current preferred model the first candidates are gemini-3.8-flash, gemini-3.7-flash, and gemini-3.6-flash. No customer inquiries or generation calls were used for that check. Set discovery to false to retain explicit-only behavior.
- Maximum generation attempts default to 3; the shared request scheduling/time budget now defaults to 90 seconds. Each attempt receives a share of remaining time to reserve time for later candidates. SDK automatic retries remain disabled. Rate limits/auth failures still stop rather than rotating models to evade them. Synchronous transport and cleanup overhead mean this is not a hard wall-clock cancellation guarantee.
- `var/analysis_attempts.jsonl` stores redacted model/outcome history with schema version and correlation ID. It is diagnostic storage, not an offline source, transaction log, or delivery outbox. A GENERATED event does not prove the subsequent Sheet save succeeded. Failed audit writes stop processing before draft persistence. Define retention/rotation before sustained use.
- Lock files in `var/locks` must remain in place while processes run. OS locks are released on process exit. Use one local project directory for cooperating writers; do not edit/sort/delete live ticket rows during writes.
- Existing invalid historical records may now be rejected. Repair them deliberately using the safe row/field diagnostic; preserve original data. Blank approved delivery status is intentionally uncertain. Never set SENT merely to bypass reconciliation.
- Existing unrelated local records/backups and credentials were preserved. No commit, push, deployment, service-account change, or live intake installation was performed.

## Remaining work and release boundaries

1. **Before shared hosting:** transactional repository/revisions, durable claims/outbox, reviewer authentication/authorization, audit attribution, monitored delivery reconciliation, backups/restore, and secret/retention procedures. Local file locking does not solve coordination across computers, separate checkouts, or manual edits.
2. **Before AI quality claims:** a labeled evaluation set with held-out cases, category/priority metrics, urgent-case misses, unsupported promises, instruction attacks, review edit rates, latency, and request counts. Schema correctness is not task accuracy. Do not present uncalibrated confidence scores.
3. **Operational follow-up:** fresh setup and hosted CI, real account/model readiness, one controlled Form → Sheet → Gemini → review → inbox acceptance run, visual/narrow-screen and keyboard checks, diagnostic log rotation, and larger-source API-read performance measurement.
4. **Later product updates:** WhatsApp Business API and website request connectors, conversation threading, maintained knowledge retrieval, assignments/escalations, and bounce/inbox delivery tracking. These are not implemented by this remediation.

Further queue-layout work, saved reviewer drafts, category/priority corrections, and analytics remain roadmap items. The current update implements operational visibility and full email review needed for the fixed core outcomes without expanding into those features.
