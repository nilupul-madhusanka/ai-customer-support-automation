# Gmail replies after human approval

Google Form → spreadsheet Apps Script → Inquiries → Gemini draft → Streamlit review → approve → Gmail SMTP.

Apps Script collects the request. Python sends the persisted, human-reviewed `final_reply` immediately after approval. Do not add an Apps Script onEdit email sender: changes made through the Sheets API do not trigger edit handlers, and a second sender could duplicate replies. Google documents this restriction at https://developers.google.com/apps-script/guides/triggers/installable#restrictions.

## 1. Update your existing Inquiries headers

Keep columns A through M in their existing order. Add **N1 = email_status** and **O1 = emailed_at**. Leave those columns blank for existing tickets. The full header row is:

```text
id,received_at,customer_name,customer_email,message,status,category,priority,summary,draft_reply,final_reply,reviewed_at,error_message,email_status,emailed_at
```

The app can read the old 13-column sheet, but requires the two new headers before making changes. It never rewrites your live headers automatically. Review and email timestamps must be ISO timestamps with a timezone (for example `2026-10-18T10:30:00Z`); approved replies must contain 1–1200 characters. Legacy date-only received dates remain readable. Correct invalid historical rows manually; do not fill a missing email status with SENT without reconciling delivery.

One writer is enforced across threads/processes in the same project directory. Other installations and manual Sheet edits are outside that lock. Do not sort, delete, or edit source rows while Python is writing.

## 2. Update Apps Script

Legacy ISO received timestamps without an offset, such as `2026-10-13T09:00:00`, are interpreted using the spreadsheet timezone from **File → Settings**. Reading does not change the Sheet. A later normal workflow update may save the equivalent timestamp with an explicit offset. Review/email timestamps still require explicit timezones. Locale-specific text dates remain invalid; use ISO text rather than guessing day/month order.

Paste the entire `google_apps_script.js` file from the project into **Extensions → Apps Script**, replacing the previous intake code, and save it. Select **setupFormIntake** from the function dropdown, click **Run**, and authorize Google access using the spreadsheet owner's account. This installs the spreadsheet **On form submit** trigger and imports valid missed submissions as NEW. Running setup again does not create another trigger or duplicate tickets imported by this script. It only manages onFormSubmit triggers owned by the account running setup; remove any duplicate intake triggers installed by other accounts separately.

The linked Google Form must use these exact question titles:

1. Customer Name
2. Customer Email (required; enable email validation)
3. Describe your issue

Test future submissions using the actual form. Run **setupFormIntake**, rather than onFormSubmit, in the editor. New rows should appear in Inquiries as NEW with 15 columns. The script uses a document lock to avoid repeated ticket IDs from simultaneous form submissions; Python still requires a single writer. Keep the form-response tab as an append-only record.

If your response tab contains two Customer Email columns, the script reads both by position and uses the populated valid answer. It rejects conflicting email answers. In the Google Form editor, keep just one required Customer Email question for future responses; preserve old response columns. Blank-email submissions remain in the response tab and are skipped, with a reason in the execution log. For missed responses, run **importPendingFormResponses**; it does not call AI or send email.

If a new submission still does not create a ticket, open **Apps Script → Executions** to see the failure. Confirm the trigger source is **From spreadsheet**, rather than From form, and that authorization succeeded. This project cannot inspect or change your installed Apps Script code through its Sheets service account; paste and run setup in your Google account.

## 3. Configure Gmail locally

Enable 2-Step Verification and create a [Google App Password](https://support.google.com/accounts/answer/185833). Availability depends on account and organization settings. Use the app password, not your normal Google password. Paste it only into the project's local `.env`; do not share it in chat or commit it.

```env
DATA_SOURCE=sheets
READ_ONLY=false
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-address@gmail.com
SMTP_PASSWORD=your-16-character-app-password
SMTP_FROM=Support Team <your-address@gmail.com>
```

Replace the sample values. Enter the generated app password without the display spaces. Keep your existing GOOGLE_SHEET_ID, service account file, and Gemini settings. Use the same Gmail address in SMTP_USER and SMTP_FROM. Restart Streamlit after changing `.env`.

## 4. Check one complete request

1. Submit the form using an email address you control.
2. Open Streamlit; the dashboard connects directly to Google Sheets.
3. Click **Refresh tickets**, then **Process new inquiries**.
4. Open the DRAFTED ticket, review and edit the response.
5. Inspect the **Complete outgoing email preview**, then click **Approve and send email**. If sending is not ready, **Approve reply** saves approval with recovery guidance.
6. Confirm email_status becomes SENT and emailed_at is filled. Check the receiving inbox and spam folder.

SENT means the SMTP server accepted the message, not that delivery to the inbox is guaranteed. No live customer email has been sent as part of implementing or testing this feature.

## Failures and retries

An SMTP failure keeps the ticket APPROVED and preserves its final reply. It does not run AI again. The approved-ticket view offers **Send approved email** when delivery has not been recorded. Fix Gmail settings and restart the dashboard before retrying configuration failures.

- NOT_SENT: approval saved, but no sending attempt completed (for example, missing configuration).
- SENDING: intent saved before SMTP; a crash or storage failure may leave this value behind.
- SENT: SMTP acceptance and timestamp recorded; further send actions skip the ticket.
- FAILED: configuration, recipient, or SMTP rejection prevented acceptance.
- UNKNOWN: a connection error made acceptance uncertain.

For SENDING, UNKNOWN, or old approved tickets with a blank email status, check the sender's Gmail Sent folder first. Confirm the retry checkbox only after checking; resending can create a duplicate. SMTP and Sheets cannot commit atomically, so exactly-once delivery is not guaranteed. No retries run automatically.

If customer_email is missing or malformed, correct the source record before sending. The app treats original customer details as immutable during normal workflow updates.

READ_ONLY=true prevents processing, approvals, and retries.

Approval and delivery are separate results. A failure saving send intent reports **Approval saved** and confirms email was not attempted. If saving FAILED/UNKNOWN/SENT fails, the warning tells you whether SMTP acceptance is known and requires checking Gmail Sent before retrying. If an approval write loses its response, Python tries to read back the exact saved approval and never attempts email on that recovery path.

Delivery recovery guidance is stored on the ticket and recomputed for missing recipient/SMTP settings when reopening it. Use the **Delivery** filter to find unsent or uncertain approvals. The preview and actual sender use the same message builder, so the greeting, signature, subject, and reference are included in review.
