from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def sales_day_key(issue_date: object, match_no: object) -> str:
    """Return a composite key of the form ``YYYY-MM-DD_<match_no>``."""
    issue = str(issue_date or "").strip()
    no = str(match_no or "").strip()
    return f"{issue}_{no}" if (issue and no) else ""
