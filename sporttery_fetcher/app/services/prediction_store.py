from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

from utils.common import csv_lock, sales_day_key


def _try_rebuild_facts(base_dir: Path | None) -> None:
    """保存预测后触发 facts 重建（失败不影响主流程）。"""
    try:
        from src.services.match_fact_builder import rebuild_match_facts
        rebuild_match_facts(base_dir)
    except Exception:
        import logging
        logging.getLogger("prediction_store").debug("facts rebuild skipped after prediction save")


# match_identity 在 src/ 下，app/ 运行时需要把 ROOT 加入 sys.path
# 这里用延迟导入保持向后兼容
def _build_match_key(record: dict) -> str:
    try:
        from src.domain.match_identity import build_match_key
        return build_match_key(record)
    except Exception:
        raw_id = str(record.get("raw_id") or "").strip()
        if raw_id:
            return f"raw:{raw_id}"
        d = str(record.get("issue_date") or "").strip()
        n = str(record.get("match_no") or "").strip()
        h = str(record.get("home_team") or "").strip()
        a = str(record.get("away_team") or "").strip()
        return f"biz:{d}|{n}|{h}|{a}"


PREDICTION_COLUMNS = [
    "issue_date",
    "match_no",
    "sales_day_key",
    "match_key",    # 全局唯一比赛标识（新增，旧 CSV 无此列时向后兼容）
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
        out["sales_day_key"] = out.apply(
            lambda r: sales_day_key(r.get("issue_date"), r.get("match_no")), axis=1
        )
    # 向后兼容旧 CSV：match_key 列不存在时按行计算
    if "match_key" not in out.columns:
        out["match_key"] = out.apply(lambda r: _build_match_key(r.to_dict()), axis=1)

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
    normalized["sales_day_key"] = sales_day_key(normalized.get("issue_date"), normalized.get("match_no"))
    if normalized.get("raw_text") in (None, ""):
        normalized["raw_text"] = normalized.get("gemini_raw_text")
    if not str(normalized.get("data_source") or "").strip():
        normalized["data_source"] = "auto"
    # 确保 match_key 已设置（优先使用传入的，否则计算）
    if not str(normalized.get("match_key") or "").strip():
        normalized["match_key"] = _build_match_key(normalized)
    return normalized


def save_prediction(row: dict[str, Any], base_dir: Path | None = None) -> Path:
    file_path = prediction_file(base_dir)
    new_row = _normalize_row(row)

    key_match_key = str(new_row.get("match_key") or "").strip()
    key_raw_id = new_row.get("raw_id", "")
    key_issue_date = new_row.get("issue_date", "")

    with csv_lock(file_path):
        current_df = load_predictions(base_dir)

        # 匹配优先级：1) match_key  2) issue_date+raw_id  3) issue_date+match_no+home+away
        if key_match_key and "match_key" in current_df.columns:
            dedup_mask = ~(current_df["match_key"].astype(str) == key_match_key)
        elif key_raw_id:
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
        _ensure_columns(out_df).to_csv(file_path, index=False, encoding="utf-8-sig")

    _try_rebuild_facts(base_dir)
    return file_path


def delete_predictions(matches: list[dict[str, str]], base_dir: Path | None = None) -> int:
    if not matches:
        return 0
    file_path = prediction_file(base_dir)
    if not file_path.exists():
        return 0

    with csv_lock(file_path):
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
            # 优先通过 match_key 删除（最精确）
            mk = str(m.get("match_key") or _build_match_key(m)).strip()
            if mk and "match_key" in df.columns:
                keep_mask &= ~(df["match_key"].astype(str) == mk)
            elif raw_id:
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
