from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

PREDICTION_COLUMNS = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "raw_id",
    "gemini_prompt",
    "gemini_raw_text",
    "gemini_match_result",
    "gemini_handicap_result",
    "gemini_score_1",
    "gemini_score_2",
    "gemini_summary",
    "gemini_model",
    "gemini_thinking_level",
    "gemini_generated_at",
]



def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
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
