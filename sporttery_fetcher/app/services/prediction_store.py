from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

PREDICTION_COLUMNS = [
    "issue_date",
    "match_no",
    "sales_day_key",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "raw_id",
    "gemini_prompt",
    "gemini_raw_text",
    "raw_text",
    "gemini_match_main_pick",
    "gemini_match_secondary_pick",
    "gemini_handicap_main_pick",
    "gemini_handicap_secondary_pick",
    "gemini_score_1",
    "gemini_score_2",
    "gemini_summary",
    "gemini_model",
    "gemini_thinking_level",
    "gemini_generated_at",
    "prediction_source",
    "prediction_status",
    "is_manual",
    "prediction_remark",
    "data_source",
]

LEGACY_COLUMN_MAPPING = {
    "gemini_match_result": "gemini_match_main_pick",
    "gemini_handicap_result": "gemini_handicap_main_pick",
}


def _sales_day_key(issue_date: object, match_no: object) -> str:
    issue = str(issue_date or "").strip()
    no = str(match_no or "").strip()
    if issue and no:
        return f"{issue}_{no}"
    return ""


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for legacy_col, new_col in LEGACY_COLUMN_MAPPING.items():
        if new_col not in out.columns and legacy_col in out.columns:
            out[new_col] = out[legacy_col]

    if "raw_text" not in out.columns and "gemini_raw_text" in out.columns:
        out["raw_text"] = out["gemini_raw_text"]

    if "prediction_source" not in out.columns:
        out["prediction_source"] = "auto_gemini"
    if "prediction_status" not in out.columns:
        out["prediction_status"] = "success"
    if "is_manual" not in out.columns:
        out["is_manual"] = False
    if "prediction_remark" not in out.columns:
        out["prediction_remark"] = None
    if "data_source" not in out.columns:
        out["data_source"] = "auto"
    if "sales_day_key" not in out.columns:
        out["sales_day_key"] = out.apply(lambda r: _sales_day_key(r.get("issue_date"), r.get("match_no")), axis=1)

    for col in PREDICTION_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[PREDICTION_COLUMNS]


def prediction_file(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(__file__).resolve().parents[2]
    file_path = root / "data" / "predictions" / "gemini_predictions.csv"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    return file_path


def load_predictions(base_dir: Path | None = None) -> pd.DataFrame:
    file_path = prediction_file(base_dir)
    if not file_path.exists():
        return pd.DataFrame(columns=PREDICTION_COLUMNS)
    try:
        df = pd.read_csv(file_path)
    except Exception:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)
    return _ensure_columns(df)


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {k: row.get(k) for k in PREDICTION_COLUMNS}
    for key in ["issue_date", "match_no", "raw_id", "home_team", "away_team"]:
        value = normalized.get(key)
        normalized[key] = "" if value is None else str(value).strip()
    normalized["sales_day_key"] = _sales_day_key(normalized.get("issue_date"), normalized.get("match_no"))
    if normalized.get("raw_text") in (None, ""):
        normalized["raw_text"] = normalized.get("gemini_raw_text")
    if not str(normalized.get("data_source") or "").strip():
        normalized["data_source"] = "auto"
    return normalized


def save_prediction(row: dict[str, Any], base_dir: Path | None = None) -> Path:
    file_path = prediction_file(base_dir)
    current_df = load_predictions(base_dir)
    new_row = _normalize_row(row)

    key_raw_id = new_row.get("raw_id", "")
    key_issue_date = new_row.get("issue_date", "")

    if key_raw_id:
        dedup_mask = ~(
            (current_df["issue_date"].astype(str) == key_issue_date)
            & (current_df["raw_id"].astype(str) == key_raw_id)
        )
    else:
        dedup_mask = ~(
            (current_df["issue_date"].astype(str) == key_issue_date)
            & (current_df["match_no"].astype(str) == new_row.get("match_no", ""))
            & (current_df["home_team"].astype(str) == new_row.get("home_team", ""))
            & (current_df["away_team"].astype(str) == new_row.get("away_team", ""))
        )

    kept_df = current_df[dedup_mask].copy()
    out_df = pd.concat([kept_df, pd.DataFrame([new_row])], ignore_index=True)
    out_df = _ensure_columns(out_df)
    out_df.to_csv(file_path, index=False, encoding="utf-8-sig")
    return file_path


def delete_predictions(matches: list[dict[str, str]], base_dir: Path | None = None) -> int:
    if not matches:
        return 0
    file_path = prediction_file(base_dir)
    if not file_path.exists():
        return 0
    df = load_predictions(base_dir)
    if df.empty:
        return 0

    keep_mask = pd.Series([True] * len(df))
    for m in matches:
        issue_date = str(m.get("issue_date", "") or "").strip()
        raw_id = str(m.get("raw_id", "") or "").strip()
        match_no = str(m.get("match_no", "") or "").strip()
        home = str(m.get("home_team", "") or "").strip()
        away = str(m.get("away_team", "") or "").strip()
        if raw_id:
            keep_mask &= ~(
                (df["issue_date"].astype(str) == issue_date)
                & (df["raw_id"].astype(str) == raw_id)
            )
        else:
            keep_mask &= ~(
                (df["issue_date"].astype(str) == issue_date)
                & (df["match_no"].astype(str) == match_no)
                & (df["home_team"].astype(str) == home)
                & (df["away_team"].astype(str) == away)
            )

    new_df = df[keep_mask].copy()
    deleted = len(df) - len(new_df)
    _ensure_columns(new_df).to_csv(file_path, index=False, encoding="utf-8-sig")
    return deleted
