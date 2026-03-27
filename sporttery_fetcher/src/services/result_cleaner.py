from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

RESULT_COLUMNS = [
    "issue_date",
    "match_no",
    "home_team",
    "away_team",
    "raw_id",
    "full_time_score",
    "result_match",
    "result_handicap",
    "data_source",
    "updated_at",
]

RAW_COLUMNS = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "handicap",
    "kickoff_time",
    "full_time_score",
    "result_match",
    "result_handicap",
    "raw_result_text",
    "result_generated_at",
    "raw_id",
    "data_source",
    "updated_at",
]

BAD_COLUMNS = RAW_COLUMNS + ["bad_reason"]

VALID_SCORE_RE = re.compile(r"^\d{1,2}-\d{1,2}$")
VALID_MATCH = {"主胜", "平", "客胜", "未开奖"}
VALID_HANDICAP = {"让胜", "让平", "让负", "未开奖"}
VALID_SOURCE = {"auto_result_fetch", "manual_entry", "history_fetch", "repair_script"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def result_paths(base_dir: Path | None = None) -> dict[str, Path]:
    root = base_dir or Path(__file__).resolve().parents[2]
    result_dir = root / "data" / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    return {
        "legacy": result_dir / "match_results.csv",
        "raw": result_dir / "raw_match_results.csv",
        "clean": result_dir / "clean_match_results.csv",
        "bad": result_dir / "bad_match_results.csv",
    }


def _read_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=columns)
    for c in columns:
        if c not in df.columns:
            df[c] = None
    return df[columns]


def _normalize_text(v: Any) -> str:
    return str(v or "").strip()


def _is_invalid_date_like_score(score: str) -> bool:
    if not VALID_SCORE_RE.match(score):
        return True
    a, b = [int(x) for x in score.split("-")]
    if a >= 20 and 1 <= b <= 12:
        return True
    if b >= 20 and 1 <= a <= 12:
        return True
    return False


def _derive_match(score: str) -> str:
    if not VALID_SCORE_RE.match(score):
        return "未开奖"
    home, away = [int(x) for x in score.split("-")]
    if home > away:
        return "主胜"
    if home == away:
        return "平"
    return "客胜"


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    raw_id = _normalize_text(row.get("raw_id"))
    match_no = _normalize_text(row.get("match_no"))
    issue_date = _normalize_text(row.get("issue_date"))
    home = _normalize_text(row.get("home_team"))
    away = _normalize_text(row.get("away_team"))

    if raw_id:
        return ("raw_id", raw_id)
    if match_no and issue_date:
        return ("match_no_issue_date", f"{match_no}|{issue_date}")
    if match_no and home and away:
        return ("match_no_teams", f"{match_no}|{home}|{away}")
    return ("invalid", "")


def _normalize_row(row: dict[str, Any], default_source: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    out = {k: row.get(k) for k in RAW_COLUMNS}
    out["issue_date"] = _normalize_text(out.get("issue_date"))
    out["match_no"] = _normalize_text(out.get("match_no"))
    out["home_team"] = _normalize_text(out.get("home_team"))
    out["away_team"] = _normalize_text(out.get("away_team"))
    out["raw_id"] = _normalize_text(out.get("raw_id")) or None
    out["full_time_score"] = _normalize_text(out.get("full_time_score"))

    src = _normalize_text(out.get("data_source")) or default_source
    out["data_source"] = src if src in VALID_SOURCE else default_source
    out["updated_at"] = _normalize_text(out.get("updated_at")) or _now_iso()

    key_type, _ = _row_key(out)
    if key_type == "invalid":
        bad = {**out, "bad_reason": "唯一键缺失(raw_id/match_no+issue_date/match_no+teams)"}
        return None, bad

    score = out["full_time_score"]
    if not score or _is_invalid_date_like_score(score):
        bad = {**out, "bad_reason": f"full_time_score 非法或疑似日期片段: {score}"}
        return None, bad

    result_match = _normalize_text(out.get("result_match"))
    if result_match not in VALID_MATCH:
        result_match = _derive_match(score)

    result_handicap = _normalize_text(out.get("result_handicap"))
    if result_handicap not in VALID_HANDICAP:
        result_handicap = "未开奖"

    clean = {
        "issue_date": out["issue_date"],
        "match_no": out["match_no"],
        "home_team": out["home_team"],
        "away_team": out["away_team"],
        "raw_id": out["raw_id"],
        "full_time_score": score,
        "result_match": result_match,
        "result_handicap": result_handicap,
        "data_source": out["data_source"],
        "updated_at": out["updated_at"],
    }

    return clean, None


def _dedup_clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    df = pd.DataFrame(rows)
    if "updated_at" not in df.columns:
        df["updated_at"] = _now_iso()
    df["_updated_ts"] = pd.to_datetime(df["updated_at"], errors="coerce")
    df = df.sort_values("_updated_ts", ascending=True)

    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for _, r in df.iterrows():
        row = r.to_dict()
        key = _row_key(row)
        if key[0] == "invalid":
            continue
        buckets[key] = {k: row.get(k) for k in RESULT_COLUMNS}

    return list(buckets.values())


def rebuild_clean_results(base_dir: Path | None = None, source_mode: str = "repair_script") -> dict[str, int]:
    paths = result_paths(base_dir)
    raw_df = _read_csv(paths["raw"], RAW_COLUMNS)
    if raw_df.empty and paths["legacy"].exists():
        legacy_df = pd.read_csv(paths["legacy"])
        for c in RAW_COLUMNS:
            if c not in legacy_df.columns:
                legacy_df[c] = None
        raw_df = legacy_df[RAW_COLUMNS]

    clean_rows: list[dict[str, Any]] = []
    bad_rows: list[dict[str, Any]] = []

    for _, row in raw_df.iterrows():
        clean, bad = _normalize_row(row.to_dict(), source_mode)
        if clean:
            clean_rows.append(clean)
        if bad:
            bad_rows.append(bad)

    dedup_clean = _dedup_clean_rows(clean_rows)

    clean_df = pd.DataFrame(dedup_clean, columns=RESULT_COLUMNS)
    bad_df = pd.DataFrame(bad_rows, columns=BAD_COLUMNS)

    clean_df.to_csv(paths["clean"], index=False, encoding="utf-8-sig")
    bad_df.to_csv(paths["bad"], index=False, encoding="utf-8-sig")
    clean_df.to_csv(paths["legacy"], index=False, encoding="utf-8-sig")

    return {
        "raw_rows": len(raw_df),
        "clean_rows": len(clean_df),
        "bad_rows": len(bad_df),
    }


def append_raw_results(records: list[dict[str, Any]], data_source: str, base_dir: Path | None = None) -> dict[str, int]:
    paths = result_paths(base_dir)
    src = data_source if data_source in VALID_SOURCE else "repair_script"

    normalized_raw = []
    for r in records:
        out = {k: r.get(k) for k in RAW_COLUMNS}
        out["data_source"] = src
        out["updated_at"] = _normalize_text(out.get("updated_at")) or _now_iso()
        normalized_raw.append(out)

    new_df = pd.DataFrame(normalized_raw, columns=RAW_COLUMNS)
    old_df = _read_csv(paths["raw"], RAW_COLUMNS)
    merged = pd.concat([old_df, new_df], ignore_index=True)
    merged.to_csv(paths["raw"], index=False, encoding="utf-8-sig")

    stats = rebuild_clean_results(base_dir, source_mode=src)
    stats["appended_raw"] = len(new_df)
    return stats


def load_clean_results(base_dir: Path | None = None) -> pd.DataFrame:
    paths = result_paths(base_dir)
    return _read_csv(paths["clean"], RESULT_COLUMNS)
