from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from services.prediction_store import save_prediction
from src.services.result_cleaner import append_raw_results, load_clean_results

MATCH_COLUMNS = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "raw_id",
    "spf_win",
    "spf_draw",
    "spf_lose",
    "rqspf_win",
    "rqspf_draw",
    "rqspf_lose",
    "data_source",
    "created_at",
    "updated_at",
]

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


@dataclass
class SaveResult:
    ok: bool
    message: str
    match_updated: bool
    prediction_updated: bool
    result_updated: bool


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root(base_dir: Path | None = None) -> Path:
    return base_dir or Path(__file__).resolve().parents[2]


def manual_matches_file(base_dir: Path | None = None) -> Path:
    path = _root(base_dir) / "data" / "manual" / "history_matches.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _results_file(base_dir: Path | None = None) -> Path:
    path = _root(base_dir) / "data" / "results" / "match_results.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = None
    return out[cols]


def _load_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        return _ensure_columns(pd.read_csv(path), columns)
    except Exception:
        return pd.DataFrame(columns=columns)


def _match_key_mask(df: pd.DataFrame, row: dict[str, Any]) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    mask = (
        (df["issue_date"].astype(str) == str(row.get("issue_date", "")))
        & (df["match_no"].astype(str) == str(row.get("match_no", "")))
        & (df["home_team"].astype(str) == str(row.get("home_team", "")))
        & (df["away_team"].astype(str) == str(row.get("away_team", "")))
    )
    raw_id = str(row.get("raw_id", "") or "").strip()
    if raw_id and "raw_id" in df.columns:
        mask = mask | (
            (df["issue_date"].astype(str) == str(row.get("issue_date", "")))
            & (df["raw_id"].astype(str) == raw_id)
        )
    return mask


def _parse_outcome(score: str | None) -> str:
    text = str(score or "").strip()
    m = pd.Series([text]).str.extract(r"^(\d+)\s*[-:：]\s*(\d+)$")
    if m.isna().any(axis=None):
        return "未开奖"
    home = int(m.iloc[0, 0])
    away = int(m.iloc[0, 1])
    if home > away:
        return "主胜"
    if home == away:
        return "平"
    return "客胜"


def _parse_handicap_result(score: str | None, handicap: str | None) -> str:
    text = str(score or "").strip()
    m = pd.Series([text]).str.extract(r"^(\d+)\s*[-:：]\s*(\d+)$")
    if m.isna().any(axis=None):
        return "未开奖"
    try:
        home = int(m.iloc[0, 0])
        away = int(m.iloc[0, 1])
        hcap = int(str(handicap or "0").strip() or "0")
    except Exception:
        return "未开奖"
    adj = home + hcap
    if adj > away:
        return "让胜"
    if adj == away:
        return "让平"
    return "让负"


def upsert_manual_match(row: dict[str, Any], base_dir: Path | None = None) -> bool:
    path = manual_matches_file(base_dir)
    df = _load_csv(path, MATCH_COLUMNS)

    now = _now_iso()
    normalized = {k: row.get(k) for k in MATCH_COLUMNS}
    normalized["data_source"] = "manual"
    normalized["updated_at"] = now
    normalized["created_at"] = normalized.get("created_at") or now

    mask = _match_key_mask(df, normalized)
    existed = bool(mask.any())
    if existed:
        original_created = str(df.loc[mask, "created_at"].iloc[-1] or "").strip()
        if original_created:
            normalized["created_at"] = original_created

    kept = df[~mask].copy() if not df.empty else df
    out = pd.concat([kept, pd.DataFrame([normalized])], ignore_index=True)
    _ensure_columns(out, MATCH_COLUMNS).to_csv(path, index=False, encoding="utf-8-sig")
    return existed


def upsert_result(row: dict[str, Any], base_dir: Path | None = None, data_source: str = "manual_entry") -> bool:
    clean_df = load_clean_results(base_dir)
    existed = False
    if not clean_df.empty:
        existed = bool(_match_key_mask(clean_df, row).any())

    raw_row = {
        "issue_date": row.get("issue_date"),
        "match_no": row.get("match_no"),
        "league": row.get("league"),
        "home_team": row.get("home_team"),
        "away_team": row.get("away_team"),
        "handicap": row.get("handicap"),
        "kickoff_time": row.get("kickoff_time"),
        "full_time_score": row.get("full_time_score"),
        "result_match": row.get("result_match"),
        "result_handicap": row.get("result_handicap"),
        "raw_result_text": row.get("raw_result_text"),
        "result_generated_at": row.get("result_generated_at"),
        "raw_id": row.get("raw_id"),
        "updated_at": _now_iso(),
    }
    append_raw_results([raw_row], data_source=data_source, base_dir=base_dir)
    return existed


def upsert_manual_prediction(row: dict[str, Any], base_dir: Path | None = None) -> bool:
    existing = load_existing_prediction(row, base_dir)
    save_prediction({**row, "data_source": "manual", "prediction_source": "manual_user", "is_manual": True}, base_dir)
    return existing


def upsert_history_fetch_results(records: list[dict[str, Any]], base_dir: Path | None = None) -> dict[str, int]:
    updated = 0
    inserted = 0
    for r in records:
        issue_date = str(r.get("issue_date", "") or "").strip()
        match_no = str(r.get("match_no", "") or "").strip()
        home = str(r.get("home_team", "") or "").strip()
        away = str(r.get("away_team", "") or "").strip()
        handicap = str(r.get("handicap", "") or "").strip()
        full_score = str(r.get("full_score", "") or "").strip()

        row = {
            "issue_date": issue_date,
            "match_no": match_no,
            "home_team": home,
            "away_team": away,
            "raw_id": None,
            "full_time_score": full_score,
            "result_match": _parse_outcome(full_score),
            "result_handicap": _parse_handicap_result(full_score, handicap),
        }
        existed = upsert_result(row, base_dir=base_dir, data_source="history_fetch")
        if existed:
            updated += 1
        else:
            inserted += 1

    return {"inserted": inserted, "updated": updated, "total": len(records)}


def load_existing_match(row: dict[str, Any], base_dir: Path | None = None) -> bool:
    df = _load_csv(manual_matches_file(base_dir), MATCH_COLUMNS)
    if df.empty:
        return False
    return bool(_match_key_mask(df, row).any())


def load_existing_prediction(row: dict[str, Any], base_dir: Path | None = None) -> bool:
    from services.prediction_store import load_predictions

    df = load_predictions(base_dir)
    if df.empty:
        return False
    return bool(_match_key_mask(df, row).any())


def load_existing_result(row: dict[str, Any], base_dir: Path | None = None) -> bool:
    df = load_clean_results(base_dir)
    if df.empty:
        return False
    return bool(_match_key_mask(df, row).any())


def save_history_entry(
    *,
    match_data: dict[str, Any],
    prediction_data: dict[str, Any],
    result_data: dict[str, Any],
    save_result: bool,
    base_dir: Path | None = None,
) -> SaveResult:
    try:
        match_updated = upsert_manual_match(match_data, base_dir)
        prediction_updated = upsert_manual_prediction(prediction_data, base_dir)
        result_updated = False
        if save_result:
            result_updated = upsert_result(result_data, base_dir, data_source="manual_entry")
    except Exception as exc:
        return SaveResult(False, f"保存失败：{type(exc).__name__}", False, False, False)

    if match_updated or prediction_updated or result_updated:
        message = "保存成功：检测到同场次已存在，已执行覆盖更新"
    else:
        message = "保存成功：已新增历史场次"
    return SaveResult(True, message, match_updated, prediction_updated, result_updated)
