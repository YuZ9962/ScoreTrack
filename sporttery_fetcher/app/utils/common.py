from __future__ import annotations

"""
Shared utility functions used across the app layer.

Centralises repeated helpers that previously appeared in multiple service
modules (prediction_store, chatgpt_store, result_evaluator, etc.) to avoid
duplication and keep each module focused on its own responsibility.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from filelock import FileLock


def sales_day_key(issue_date: object, match_no: object) -> str:
    """Return a composite key of the form ``YYYY-MM-DD_<match_no>``.

    Used as a stable identifier that links predictions to results across
    different CSV stores.
    """
    issue = str(issue_date or "").strip()
    no = str(match_no or "").strip()
    if issue and no:
        return f"{issue}_{no}"
    return ""


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def csv_lock(path: Path, timeout: float = 10.0) -> Generator[None, None, None]:
    """Acquire an exclusive file-system lock around *path* before CSV writes.

    The companion ``.lock`` file is placed next to the target file.  Using a
    real file-system lock (via ``filelock``) protects against concurrent writes
    from both threads (Streamlit re-renders) *and* subprocesses (the fetch
    runner launched by ``fetch_runner.py``).
    """
    lock_path = str(path) + ".lock"
    lock = FileLock(lock_path, timeout=timeout)
    with lock:
        yield
