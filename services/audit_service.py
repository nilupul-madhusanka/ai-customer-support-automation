"""Redacted local analysis-attempt history; never an inquiry source."""
from datetime import datetime, timezone
import json
import os
from uuid import uuid4

from services.config import project_path


def record_analysis(ticket_id, *, model=None, attempts=(), outcome):
    path = project_path(os.getenv("ANALYSIS_AUDIT_PATH", "var/analysis_attempts.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"schema_version": 1, "analysis_id": uuid4().hex,
              "ticket_id": ticket_id, "at": datetime.now(timezone.utc).isoformat(),
              "model": model, "attempts": list(attempts), "outcome": outcome}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")
        file.flush()
        os.fsync(file.fileno())
