> Historical review, preserved from 15 October 2026. Findings and recommendations here describe that revision. See [the updated review](../project_review_2026-10-15.md) for current status.

# Project code and development review

Date: 15 October 2026 (Asia/Colombo)  
Reviewed revision: `e43543b` (`remove google_apps_script.js`)

## Assessment

The project has a credible local MVP foundation. Its core sequence—load inquiries, analyze NEW records, validate structured output, save drafts, obtain human approval, and attempt email—is clearly separated into services and covered by useful tests. It is ready for continued local development with one writer. Shared operation needs stronger record claiming, access control, and delivery tracking.

The highest-value next work is to reconcile the removed intake component, repair fallback behavior, make partial approval outcomes explicit, and improve the reviewer's operational dashboard. The existing service boundaries are suitable for these changes.

This review produced this report only. Application code, configuration, original data, and earlier verification reports were preserved. Recommendations and proposed layouts below have not been implemented.

## Scope and verification

Reviewed all tracked Python modules, tests, configuration templates, dependency files, dashboard source, setup documentation, and recent Git history. The working tree was clean at the start.

| Check | Result |
|---|---|
| Python test suite | **37 passed in 13.39 seconds**, including both dashboard interaction tests |
| Apps Script check | **Failed before assertions**: `google_apps_script.js` is missing |
| Python syntax | All 18 Python files parsed successfully |
| Dependency lock comparison | All 68 locked packages match the installed environment |
| Dependency metadata consistency | No missing or incompatible mandatory dependencies found in the installed environment |
| Documentation file links | README links to a missing project guide |
| Additional failure probes | Reproduced fallback interruption, concurrent duplicate sending, partial approval persistence, permissive stored-row validation, and transient delivery guidance |

The first sandboxed dashboard test attempts stalled while Python created a Windows socket pair. Those runs were stopped. The complete suite then passed outside the sandbox. This was an execution restriction, not an application test failure.

`pip check` could not run because this local virtual environment has no pip module. Dependency consistency was instead checked from installed package metadata, evaluating mandatory requirements and version constraints. This does not establish fresh-install portability or dependency vulnerability status.

Checks used synthetic temporary records and mocked AI/SMTP services. No live AI requests, Google Sheet writes, customer messages, or deployment were performed. Dashboard findings use source inspection and interaction tests; a browser screenshot, narrow-screen layout review, and accessibility audit were not performed. Existing live verification statements in older documents were not reverified.

Reproduction commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/test_apps_script.cjs
```

The second command must be included in verification while the intake test remains supported; Python pytest does not execute it.

## Prioritized findings

P2 means a concrete defect or operational constraint to address in a planned development iteration. P3 means a smaller consistency or usability issue. The concurrency finding becomes a release blocker before shared operation or background workers are introduced.

| ID | Priority | Finding | Evidence |
|---|---|---|---|
| F1 | P2 | Documented Form intake cannot be reproduced from this checkout | Missing source; Node check fails; setup still requires it |
| F2 | P2 | An unavailable fallback prevents later models being attempted | Mocked primary 503 followed by fallback 404 stops after two calls |
| F3 | P2 | Approval can succeed while the dashboard reports a generic operation failure | Failure saving SENDING leaves APPROVED / NOT_SENT and raises |
| F4 | P2 / shared-use blocker | Concurrent email actions can send the same reply twice | Two synchronized callers produced two mocked SMTP sends |
| F5 | P3 | Raw validation errors can include source values in the dashboard | Pydantic ValidationError is a ValueError; its rendered text includes input fragments |
| F6 | P3 | Stored approval fields do not enforce all service-level constraints | A 1,201-character final reply and an invalid review timestamp were accepted |
| F7 | P3 | Some email recovery guidance disappears after refresh | Missing SMTP returns a notice without persisting a reason |
| F8 | P3 | Documentation describes older behavior and removed files | Email architecture, test count, guide link, and Git-status claims are stale |

### F1 — Reconcile the removed intake component

References: `tests/test_apps_script.cjs:55`, `docs/email_setup.md:19`, `README.md:176`.

The latest commit explicitly removed `google_apps_script.js`, but the remaining test imports it and the setup guide tells a new user to paste it into Apps Script. The test currently fails with ENOENT. The documented Google Form → Inquiries setup cannot be followed from a fresh checkout.

This does not prove an already-installed external Apps Script has stopped running; the installed Google project was not inspected. It is a repository reproducibility and verification failure.

Action: decide the supported intake contract. If Form intake remains part of the product, restore or relocate its maintained source and update references. If removal is intentional, document the externally managed intake dependency or replacement and revise the test and setup instructions accordingly. The review leaves the deliberate deletion intact.

Acceptance: the complete documented intake setup is available, and the intake check either passes against maintained source or is replaced by a meaningful check for the new boundary.

### F2 — Repair fallback traversal and bound its total work

References: `services/ai_service.py:70`, `services/ai_service.py:84`, `services/ai_service.py:88`.

The code attempts fallbacks after server errors and rate limits. Any other ClientError immediately escapes. In a reproduced sequence—primary 503, first fallback 404, then an available candidate—the third candidate is never reached. An unavailable hardcoded fallback can therefore defeat the intended recovery path.

The primary plus five distinct fallback entries also permits six requests per ticket when the configured model is outside the list. With 30-second request timeouts, request waiting alone can approach 180 seconds per ticket, or 18 minutes for six tickets, excluding other overhead. This is a planning estimate, not a measured latency guarantee. The dashboard displays one spinner throughout the batch. SDK retries are disabled, but application-level model attempts still occur automatically.

Action: classify provider failures using structured status codes. Distinguish primary model misconfiguration, unavailable fallback candidates, authentication failures, malformed requests, and quota exhaustion. Skip an unavailable fallback candidate when appropriate, fail fast on global configuration/authentication failures, and use a configured allowlist with an overall attempt/time budget. Persist the model actually used and the analysis attempt outcome. Respect any provider retry guidance instead of immediately repeating every request across all candidates.

Acceptance: mocked sequences cover primary success, 503 → fallback success, 503 → fallback 404 → later success, authentication failure, rate limit exhaustion, invalid JSON, and empty output. The attempt budget is enforced and visible to the reviewer. Actual model availability still requires account-specific verification.

### F3 — Report approval persistence separately from sending

References: `services/ticket_service.py:62`, `services/ticket_service.py:69`, `services/ticket_service.py:101`, `app.py:87`.

Approval is committed before `send_approved_email` runs. If the send-intent update fails, the exception escapes `approve_ticket`. The dashboard displays a generic error and does not perform its success rerun, although approval and the final response are already saved.

A synthetic save failure at the SENDING update left the row APPROVED / NOT_SENT, with zero SMTP calls. This is a valid partial outcome, but the interface does not communicate it. A reviewer may assume approval failed and repeat the action.

Action: return a structured result separating approval persistence, send attempt, SMTP acceptance, and tracking persistence. After approval has committed, display an explicit message such as “Approval saved. Email was not attempted because delivery tracking could not be saved.” Refresh the persisted ticket state while retaining a useful warning. Extend this treatment to failures saving FAILED or UNKNOWN after an SMTP exception.

Acceptance: injected storage failures at every delivery stage show the correct persisted approval state, never send before intent is saved, and retain the existing uncertainty protection after SMTP acceptance.

### F4 — Enforce one writer before enabling shared workflows

References: `services/ticket_service.py:79`, `services/ticket_service.py:101`, `services/storage.py:23`, `services/storage.py:46`, `services/sheets_service.py:58`.

Two callers can both read APPROVED / NOT_SENT, then both set SENDING and send. Each update checks only ticket status APPROVED, which remains unchanged throughout delivery. A synchronized in-memory reproduction using the real workflow and `apply_changes` made two SMTP calls and ended with SENT.

This is consistent with the documented single-writer limitation; ordinary sequential repeat sends are correctly skipped. Multiple dashboard sessions or a CLI process alongside the dashboard can violate that assumption. CSV atomic replacement prevents partial file writes but does not prevent lost concurrent updates. Sheets ID lookup protects against rows moved before the read, while a sort/delete between read and write can still invalidate its row number.

Action for continued local use: enforce one active writer across the complete operation, with a clearly reported busy state. Before shared use, introduce transactional record claims and revisions, durable send attempts, and a delivery outbox. Validate both workflow revision and expected email state when claiming a send. A database transaction can make claiming atomic; it cannot make external SMTP acceptance and a local commit atomic. Keep uncertain delivery reconciliation and use provider idempotency support if available.

Acceptance: simultaneous process, approval, and send requests produce one accepted claim; stale actions receive a conflict; concurrent updates do not overwrite unrelated changes. Uncertain sends require reconciliation rather than automatic resend.

### F5 — Use controlled messages for validation failures

References: `app.py:14`, `models/ticket.py:42`.

`display_error` renders the full string of every ValueError. Pydantic ValidationError belongs to that family and can include the rejected input. A synthetic invalid stored summary appeared in the exception text. Thus malformed imported analysis can expose source fragments in the error panel and produce a confusing technical message. This was not demonstrated as disclosure to a new unauthorized party; the dashboard already displays inquiry data.

Action: expose only explicit application error messages. Translate validation errors into safe field names, row/ticket identifiers, and recovery steps. If diagnostic logging is added, omit input values, credentials, and full customer messages. Reserve detailed diagnostics for an appropriately protected channel.

Acceptance: malformed stored records show an actionable ticket/field error without printing a sentinel input value; known safe configuration guidance still appears.

### F6 — Align stored-row validation with the approval contract

References: `models/ticket.py:25`, `models/ticket.py:43`, `services/ticket_service.py:60`.

The service limits reviewed responses to 1–1,200 characters, but stored-row validation only checks nonblank final text and a nonempty review timestamp. A 1,201-character final response and `reviewed_at='not-a-date'` passed validation. Manually edited Sheets/CSV records can consequently bypass rules that dashboard approval enforces; the sending service trusts their stored final response.

Action: introduce a typed stored-ticket contract with explicit status-dependent rules, timestamp parsing/timezone requirements, final-response limits, and valid email-state combinations. Keep a deliberate migration path for legacy records. Add strict address requirements at the point a record becomes eligible for sending, so missing historical contact data remains diagnosable.

Acceptance: invalid final text and timestamps are rejected with a safe ticket identifier; legacy migration fixtures and valid existing records continue to load.

### F7 — Preserve delivery recovery reasons

References: `services/ticket_service.py:92`, `services/ticket_service.py:94`, `app.py:103`.

Missing customer email or SMTP configuration returns useful text but stores no reason. After the one-time notice is consumed, APPROVED / NOT_SENT falls back to “no confirmed email send recorded.” The reviewer loses the specific fix needed.

Action: persist a safe reason code or recompute a precise preflight diagnosis whenever an approved unsent ticket is opened. Show distinct guidance for missing recipient, missing sender configuration, rejected send, and uncertain acceptance. Keep delivery errors separate from analysis errors when the data model is extended.

Acceptance: reload an approved ticket with missing SMTP or recipient information and still see the correct next step.

### F8 — Establish one current verification summary

References: `README.md:30`, `README.md:41`, `README.md:102`, `docs/architecture.md:17`, `docs/project_verification.md:32`.

The README links to a removed guide; architecture says no outgoing messaging service exists; older status summaries say 21 tests; Git descriptions refer to one initial commit although the repository now has multiple commits. Historical reports can retain their dated evidence, but readers need a current summary. SDK retry settings and automatic fallback attempts should also be explained separately.

Action: update current setup/architecture pages, label prior verification records as historical, and link to this dated review. Replace source/account-specific live status statements with dated observations and reproducible commands. Describe the Node check and its runtime requirement whenever Apps Script testing is supported.

Acceptance: local Markdown links resolve, documented components exist or have an explicit external ownership boundary, and the current verification section reports Python and intake results separately.

## Error-handling report

| Failure | Current behavior | Recommended next step |
|---|---|---|
| Missing Gemini key/model | UI/CLI preflight before analysis | Retain; expose configuration readiness without revealing values |
| Blank or oversized inquiry | Validation fails; ticket becomes ERROR during processing | Preserve a safe `INPUT_INVALID` reason and precise recovery instruction |
| AI schema/JSON failure | ERROR; raw provider exception text is not persisted | Add a safe structured reason and attempt metadata |
| Provider busy/rate limited | Several model attempts, then ERROR | Repair traversal, use a total budget, and distinguish transient failure from invalid configuration |
| Provider-wide authentication/configuration issue | Nonempty key passes preflight; failures can mark each selected ticket ERROR | Stop the batch on a classified global failure and preserve unattempted tickets as NEW |
| Malformed CSV/Sheet or duplicate IDs | Whole-source load fails | Keep validation strict; identify the offending record/field and offer a read-only diagnostic view |
| Analysis result cannot be saved | Batch aborts, avoiding false AI error labels | Report completed/failed/deferred totals when a partial batch has already committed |
| Stale ticket status | Expected-status check rejects action | Present a conflict message and refresh current state |
| Approval saved, send-intent save fails | Approval persists; exception escapes | F3: show partial success and safe recovery |
| Missing SMTP/recipient | Approval remains saved; sending is skipped | F7: retain a specific recovery reason |
| Definite SMTP rejection | APPROVED / FAILED; final reply retained | Retain behavior; map authentication, address, TLS, and rejection failures to separate safe actions |
| SMTP connection outcome uncertain | UNKNOWN or residual SENDING; confirmation required | Retain conservative handling and reconciliation instructions |
| SMTP accepted, SENT tracking save fails | Warning returned; SENDING remains | Retain; show this as delivery uncertainty in the queue |
| Read-only preview | Business operations blocked; missing demo CSV can still initialize | Keep this documented distinction visible in the mode label |

Introduce a small set of domain error codes—such as INPUT_INVALID, SOURCE_INVALID, PROVIDER_AUTH, PROVIDER_BUSY, STORAGE_WRITE_FAILED, STALE_RECORD, SMTP_REJECTED, and DELIVERY_UNCERTAIN—with a safe message, affected ticket, recovery action, and retry eligibility. Add a correlation/attempt identifier for support diagnostics. The same error contract should serve the CLI and dashboard.

## Code structure and file management

### What is working

- UI and CLI share the workflow service instead of duplicating business rules.
- The repository protocol makes CSV and Sheets interchangeable at the service boundary.
- Strict analysis enums and length limits constrain AI output.
- CSV replacement uses a temporary file, flush, and fsync; Sheets uses RAW writes.
- Approval persists edited text and a UTC timestamp while retaining the original draft.
- SMTP uses verified STARTTLS and explicit envelope addresses.
- Offline fixtures are separate from live records; tests block real SMTP.
- `.env`, credentials, working CSVs, and existing backup files are ignored by Git. This is a current tracking check, not a full history secret scan.

### Suggested organization

Keep the current shallow project structure while the application remains small. The next useful separation is presentation helpers, error contracts, and typed workflow results.

| Area | Recommendation | Reason |
|---|---|---|
| `app.py` | Extract queue, detail, review form, and delivery-status rendering into `ui/` when implementing the dashboard iteration | Makes independent UI changes easier without mixing business rules into rendering |
| `services/config.py` | Load and validate typed settings once, including booleans, source, SMTP port, and model policy | Avoid scattered parsing and inconsistent readiness checks |
| `models/ticket.py` | Separate analysis payload, stored ticket, and workflow result contracts as fields grow | Makes status-dependent validation and partial outcomes explicit |
| Repository layer | Add record lookup/claim operations alongside bulk load when transactional storage is introduced | Current processing repeatedly reads the entire source |
| Intake integration | Put maintained intake code and setup instructions under one documented owner/location | Resolves F1 and prevents orphan tests |
| `scripts/verify_sheets.py` | Separate a read-only connection check from initialization, AI processing, and source switching | The present verification tool can mutate data and local `.env`, even without `--initialize` |
| `tests/` | Group workflow, repository, integration-adapter, and UI checks as the suite expands | Makes required verification visible and avoids omitting the Node check |
| `requirements.txt` / lock | Retain both declared ranges and the verified lock; document Python and any Node requirement | Preserves the currently matching environment and fresh-install instructions |
| Automation configuration | Add a checked-in quality workflow for supported Python and intake checks | Prevents a passing Python-only run from hiding a broken integration artifact |
| `docs/` | Maintain architecture, setup, current status, roadmap, and dated reviews with distinct purposes | Reduces stale statements copied between several reports |

The Sheets path currently performs an initial full read and approximately two full reads plus one write per ticket, before additional UI reads. For small batches this is understandable; for larger sources it increases latency and API work. Preserve conflict protection when optimizing rather than simply removing rereads.

### Data and backup policy

Keep `data/sample_inquiries.csv` as the versioned synthetic fixture. Continue ignoring operational ticket files and credential material. Existing `.before-email.bak` files should be retained until their recovery purpose is reviewed; they were not deleted.

When more runtime artifacts are introduced, use a deliberate layout such as:

```text
data/sample_inquiries.csv     versioned synthetic seed
var/data/                    ignored operational files or local database
var/backups/                 ignored dated snapshots
var/logs/                    ignored redacted diagnostics
docs/reviews/                dated reports when enough accumulate
docs/roadmap.md              active development sequence
```

Treat this as a migration: support existing configured paths, test backup/restore, document retention and permissions, and avoid silently creating a new empty operational source. Add a schema version and migration procedure before expanding the fixed 15-column format with model, assignment, audit, or job fields.

## Dashboard improvement proposal

The existing dashboard supports the main task with counts, filters, a table, inquiry selection, editing, and approval. The next iteration should make the work queue, complete outgoing message, and delivery outcome easier to understand.

### Proposed layout

```text
Support Review       [Offline demo | Live CSV/Sheets] [Read-only] [Refresh]
Needs review | New | High priority pending | Unsent approved | Errors

[Search name / email / ID] [Status] [Priority] [Category] [Delivery]

Inquiry queue                       Selected inquiry
ID / age / priority / status        Customer and original message
Summary / delivery status           Suggested category, priority, summary
                                    Review editor | Complete email preview
                                    [Save review draft] [Approve and send email]

Recent batch progress / safe errors / recovery actions
```

This is a proposed information hierarchy, not a rendered or implemented design. Saving a review draft requires an explicit persistence contract before adding the control.

| Priority | Change | User benefit / acceptance |
|---|---|---|
| First | Show explicit source, offline/live mode, and read-only state in the header | Reviewer can identify where an action will write and whether email is enabled |
| First | Distinguish approval from SMTP acceptance everywhere | APPROVED is never presented as proof that a customer received a reply |
| First | Use truthful primary action labels | Live configured mode says “Approve and send email”; offline says “Approve demo reply”; unavailable email explains approval-only behavior |
| First | Preview the complete outgoing email | Reviewer sees To, From, subject, greeting, response, signature, and reference added by `send_reply`, rather than only `final_reply` |
| First | Add delivery status to the queue and filters | Approved unsent/failed/uncertain messages are discoverable without opening each ticket |
| First | Replace generic error panels with specific recovery cards | Each failure shows its ticket, safe reason, persisted state, and next action |
| Next | Use a queue beside inquiry details on wide screens; stack on narrow screens | Reduces scrolling between the source message and editor |
| Next | Open the selected table row directly, with a labeled fallback selector if needed | Reduces the current table-plus-ID-selector navigation overhead |
| Next | Add search and received-age sorting | Reviewer can find a customer and prioritize old or urgent work; requires validated timestamps |
| Next | Add editable reviewer category/priority and reviewed draft saving | Human corrections become persistent and can inform later AI evaluation |
| Next | Show progress per ticket, elapsed time, processed/failed/deferred counts, and next-ticket navigation | Reviewer understands long fallback batches and can continue reviewing efficiently |
| Later | Show queue age, review turnaround, provider latency, delivery failures, and category trends | Adds actionable operational visibility once reliable event timestamps exist |

Use labeled badges in addition to color, readable contrast, keyboard-accessible controls, and wrapping for long messages/addresses. Show local time with a timezone label while keeping stored timestamps in UTC. A follow-up visual review should cover narrow screens, empty/error/loading states, long content, and keyboard navigation.

Preserve the uncertainty confirmation for SENDING/UNKNOWN/legacy blank delivery states. Place send retries separately from approval and show the duplicate-send explanation at the action point. Present “SMTP accepted” accurately; inbox delivery and bounce tracking require additional integration.

## Development roadmap

| Phase | Work | Completion gate |
|---|---|---|
| 1. Stabilize the current local release | Resolve intake ownership; fix and test fallback traversal/budget; handle partial approval; persist recovery guidance; correct current docs; include every supported check in automation | Python and supported intake checks pass; reproduced failures have meaningful regression coverage; fresh setup instructions are internally consistent |
| 2. Improve reviewer workflow | Implement source/mode header, operational queue, email preview, safe recovery cards, search/sort, progress, and category/priority corrections | Representative review, failure, and retry tasks are verified through interaction tests and browser review |
| 3. Support shared operation | Transactional repository, migrations, atomic claims/revisions, durable jobs/outbox, authentication, reviewer attribution, audit events, backup/restore | Concurrent callers cannot duplicate a claimed task; crash recovery preserves uncertain delivery; access and restore procedures are tested |
| 4. Measure AI quality | Build a labeled synthetic/anonymized evaluation set spanning all categories/priorities, ambiguous requests, long inputs, and instruction attacks; record model/prompt versions | Report category/priority errors, urgent-case misses, unsupported claims, review edit rates, latency, and request usage against agreed acceptance thresholds |
| 5. Extend product capability | Approved knowledge retrieval, assignment/escalation, conversation threading, additional channels, bounce handling, notifications, deployment monitoring | Each integration has clear ownership, failure recovery, data handling, and measurable user value |

For evaluation, start with a manageable labeled set of roughly 50–100 varied cases and keep a held-out subset for changes to prompts/models. Human review remains essential even with schema-valid output. Do not expose numeric confidence as a reliable signal until it is measured and calibrated.

Add knowledge retrieval only from maintained business material, with source references in the reviewer view. Escalate policy-sensitive or unresolved requests for human handling. Agent frameworks are optional; adopt one when a specific multi-step workflow needs its capabilities and the added complexity is justified.

Before hosting, complete authentication/authorization, secure secret injection, operational data retention, backups, monitoring, and the shared-writer work. The existing localhost binding is appropriate for the current local review model.

## Suggested next development order

1. Resolve the missing intake contract and bring verification/documentation into agreement.
2. Repair fallback traversal and add an overall request budget with focused regression tests.
3. Make approval and delivery results explicit, including tracking-write failures and persistent recovery guidance.
4. Build the operational queue and full email preview on those clearer contracts.
5. Introduce transactional storage and access control before shared use or automated background processing.
6. Evaluate AI quality and then expand channels, retrieval, assignment, and analytics based on measured needs.
