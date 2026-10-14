# Reproducible demo (60–90 seconds)

1. Explain the problem: first-pass support review is repetitive, while final replies need human judgment.
2. Show six synthetic inquiries in `data/sample_inquiries.csv`.
3. Run `main.py --demo` and explicitly say this is an **offline workflow demonstration**, using fixtures rather than Gemini.
4. Repeat the command. Show zero new drafts and six skipped records.
5. Open the dashboard in Offline demo mode. Inspect suggested category, priority, summary, and original message.
6. Edit a draft. Approve it. Filter to APPROVED and show the saved edited response and review timestamp.
7. Explain that Offline demo records approval without email; live approval sends the reviewed reply through configured Gmail SMTP. See email_setup.md.

For a real AI demonstration, configure Gemini, run `main.py` without `--demo`, disable Offline demo in the dashboard, and describe the live model used. Claim Google Sheets integration has been verified only after completing its live checklist.

Offline records persist across demos. To repeat from scratch, stop the dashboard and rename `data/demo_tickets.csv` to a backup filename; the next demo initializes new records from the sample. Do not reset live or approved records merely to stage a demo.

Suggested screenshots: original sample, CLI first/second run, dashboard overview, and edited approved response. Label offline screenshots accordingly and keep credentials outside every capture.
