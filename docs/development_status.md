# Development status

The current scope is online customer support intake through Google Sheets, including Google Forms submissions collected by Apps Script. Gemini prepares drafts, Streamlit provides human review, and Gmail SMTP sends approved responses when configured.

Implemented: typed stored-row validation, stable-ID Sheets updates, structured AI analysis with configured fallback/attempt/time policy, redacted model-attempt history, batch stop/deferred outcomes, repeat-run protection, explicit analysis retries, reviewed response persistence, structured approval/delivery outcomes, local cross-thread/process writer exclusion, delivery/search filters, complete email preview, and read-only operation through `READ_ONLY`.

Offline demonstrations, simulated runtime analysis, CSV repositories, local seed data, and file-backed processing have been removed. Automated tests use mocked online services and synthetic records defined only in tests.

Planned for later updates: WhatsApp Business API messages and website-integrated customer requests. Neither connector is implemented in this release.

The 18 October follow-up fixes or locally mitigates findings F1–F8 from the [review](project_review_2026-10-15.md). Following timestamp compatibility and automatic model-discovery updates, the Python suite has 106 passing tests; the Apps Script harness passes separately. A read-only live source check validated 11 inquiries. A live model-metadata check discovered 18 eligible candidates without generating replies. Automatic discovery is enabled by default, with three attempts and a 90-second shared request budget. CI includes both test suites plus syntax/link and dependency checks, but the hosted CI run and a fresh installation have not been verified.

Live end-to-end acceptance, classification/prompt-injection evaluation, distributed concurrent operation, authentication, deployment, transactional claims/outbox, and a full reviewer audit trail remain separate validation or development work. See [verification](project_verification.md).
