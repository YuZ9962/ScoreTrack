from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

CHATGPT_COLUMNS = [
    "issue_date",
    "match_no",
    "sales_day_key",
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
    "chatgpt_match_main_pick",
    "chatgpt_match_secondary_pick",
    "chatgpt_handicap_main_pick",
    "chatgpt_handicap_secondary_pick",
    "chatgpt_score_1",
    "chatgpt_score_2",
    "chatgpt_score_3",
    "chatgpt_top_direction",
    "chatgpt_upset_probability_text",
    "chatgpt_summary",
    "chatgpt_model",
    "chatgpt_generated_at",
]


def _sales_day_key(issue_date: object, match_no: object) -> str:
    issue = str(issue_date or "").strip()
    no = str(match_no or "").strip()
    if issue and no:
        return f"{issue}_{no}"
    return ""


def chatgpt_prediction_file(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(__file__).resolve().parents[2]
    p = root / "data" / "predictions" / "chatgpt_predictions.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "sales_day_key" not in out.columns:
        out["sales_day_key"] = out.apply(lambda r: _sales_day_key(r.get("issue_date"), r.get("match_no")), axis=1)
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
    new_row["sales_day_key"] = _sales_day_key(new_row.get("issue_date"), new_row.get("match_no"))

    key_raw_id = new_row.get("raw_id", "")
    key_issue_date = new_row.get("issue_date", "")
    if key_raw_id:
        mask = ~(
            (current["issue_date"].astype(str) == key_issue_date)
            & (current["raw_id"].astype(str) == key_raw_id)
        )
    else:
        mask = ~(
            (current["issue_date"].astype(str) == key_issue_date)
            & (current["match_no"].astype(str) == new_row.get("match_no", ""))
            & (current["home_team"].astype(str) == new_row.get("home_team", ""))
            & (current["away_team"].astype(str) == new_row.get("away_team", ""))
        )

    kept = current[mask].copy()
    out = pd.concat([kept, pd.DataFrame([new_row])], ignore_index=True)
    out = _ensure_cols(out)
    out.to_csv(p, index=False, encoding="utf-8-sig")
    return p


def delete_chatgpt_predictions(matches: list[dict[str, str]], base_dir: Path | None = None) -> int:
    if not matches:
        return 0
    p = chatgpt_prediction_file(base_dir)
    if not p.exists():
        return 0
    df = load_chatgpt_predictions(base_dir)
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
    _ensure_cols(new_df).to_csv(p, index=False, encoding="utf-8-sig")
    return deleted
