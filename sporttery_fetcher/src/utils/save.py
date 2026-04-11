from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import settings
from src.utils.schemas import PROCESSED_MATCH_COLUMNS


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_json(records: list[dict[str, Any]], issue_date: str) -> Path:
    output = settings.data_raw_dir / f"{issue_date}_matches.json"
    _ensure_parent(output)
    with output.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return output


def save_csv(records: list[dict[str, Any]], issue_date: str) -> Path:
    output = settings.data_processed_dir / f"{issue_date}_matches.csv"
    _ensure_parent(output)
    with output.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=PROCESSED_MATCH_COLUMNS)
        writer.writeheader()
        for row in records:
            writer.writerow({h: row.get(h) for h in PROCESSED_MATCH_COLUMNS})
    return output


def save_html_snapshot(html: str, tag: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = settings.snapshots_dir / f"{tag}_{ts}.html"
    _ensure_parent(output)
    with output.open("w", encoding="utf-8") as f:
        f.write(html)
    return output
