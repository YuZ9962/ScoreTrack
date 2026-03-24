from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

CHATGPT_COLUMNS = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "raw_id",
    "chatgpt_prompt",
    "chatgpt_raw_text",
    "chatgpt_home_win_prob",
    "chatgpt_draw_prob",
    "chatgpt_away_win_prob",
    "chatgpt_handicap_win_prob",
    "chatgpt_handicap_draw_prob",
    "chatgpt_handicap_lose_prob",
    "chatgpt_score_1",
    "chatgpt_score_2",
    "chatgpt_score_3",
    "chatgpt_top_direction",
    "chatgpt_upset_probability_text",
    "chatgpt_summary",
    "chatgpt_model",
    "chatgpt_generated_at",
]


def chatgpt_prediction_file(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(__file__).resolve().parents[2]
    p = root / "data" / "predictions" / "chatgpt_predictions.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in CHATGPT_COLUMNS:
        if c not in out.columns:
            out[c] = None
    return out[CHATGPT_COLUMNS]


def load_chatgpt_predictions(base_dir: Path | None = None) -> pd.DataFrame:
    p = chatgpt_prediction_file(base_dir)
    if not p.exists():
        return pd.DataFrame(columns=CHATGPT_COLUMNS)
    try:
        return _ensure_cols(pd.read_csv(p))
    except Exception:
        return pd.DataFrame(columns=CHATGPT_COLUMNS)


def save_chatgpt_prediction(row: dict[str, Any], base_dir: Path | None = None) -> Path:
    p = chatgpt_prediction_file(base_dir)
    current = load_chatgpt_predictions(base_dir)

    new_row = {k: row.get(k) for k in CHATGPT_COLUMNS}
    for key in ["issue_date", "match_no", "raw_id", "home_team", "away_team"]:
        new_row[key] = str(new_row.get(key) or "").strip()

    key_raw_id = new_row.get("raw_id", "")
    key_issue_date = new_row.get("issue_date", "")
    if key_raw_id:
        mask = ~(
            (current["issue_date"].astype(str) == key_issue_date)
            & (current["raw_id"].astype(str) == key_raw_id)
        )
    else:
        mask = ~(
            (current["match_no"].astype(str) == new_row.get("match_no", ""))
            & (current["home_team"].astype(str) == new_row.get("home_team", ""))
            & (current["away_team"].astype(str) == new_row.get("away_team", ""))
        )

    kept = current[mask].copy()
    out = pd.concat([kept, pd.DataFrame([new_row])], ignore_index=True)
    out = _ensure_cols(out)
    out.to_csv(p, index=False, encoding="utf-8-sig")
    return p
