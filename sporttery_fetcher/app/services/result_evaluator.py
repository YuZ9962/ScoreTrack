from __future__ import annotations

import pandas as pd


def _normalize_pick(value: object) -> str:
    return str(value or "").strip()


def _has_secondary_pick(value: object) -> bool:
    v = _normalize_pick(value)
    return bool(v and v != "无" and v.lower() != "null")


def _is_not_started_result(value: object) -> bool:
    v = _normalize_pick(value)
    return (not v) or (v == "未开奖")


def _judge_hit(real_result: object, main_pick: object, secondary_pick: object) -> str:
    real = _normalize_pick(real_result)
    if _is_not_started_result(real):
        return "未开奖"

    main = _normalize_pick(main_pick)
    if main and real == main:
        return "命中"

    if _has_secondary_pick(secondary_pick):
        secondary = _normalize_pick(secondary_pick)
        if real == secondary:
            return "命中"

    return "未命中"



def _match_row(pred_row: pd.Series, result_df: pd.DataFrame) -> pd.Series | None:
    raw_id = str(pred_row.get("raw_id", "") or "").strip()
    issue_date = str(pred_row.get("issue_date", "") or "").strip()

    if raw_id and "raw_id" in result_df.columns:
        matched = result_df[result_df["raw_id"].astype(str) == raw_id]
        if not matched.empty:
            return matched.iloc[-1]

    if "match_no" in result_df.columns:
        matched = result_df[
            (result_df["issue_date"].astype(str) == issue_date)
            & (result_df["match_no"].astype(str) == str(pred_row.get("match_no", "")))
        ]
        if not matched.empty:
            return matched.iloc[-1]

    matched = result_df[
        (result_df["issue_date"].astype(str) == issue_date)
        & (result_df["home_team"].astype(str) == str(pred_row.get("home_team", "")))
        & (result_df["away_team"].astype(str) == str(pred_row.get("away_team", "")))
    ]
    if not matched.empty:
        return matched.iloc[-1]

    return None



def evaluate_predictions(pred_df: pd.DataFrame, result_df: pd.DataFrame) -> pd.DataFrame:
    out = pred_df.copy()
    out["final_score"] = None
    out["match_hit_result"] = "未开奖"
    out["handicap_hit_result"] = "未开奖"

    if result_df.empty:
        return out

    for i, row in out.iterrows():
        matched = _match_row(row, result_df)
        if matched is None:
            continue

        final_score = matched.get("full_time_score")
        result_match = matched.get("result_match")
        result_handicap = matched.get("result_handicap")
        out.at[i, "final_score"] = final_score

        out.at[i, "match_hit_result"] = _judge_hit(
            result_match,
            row.get("gemini_match_main_pick"),
            row.get("gemini_match_secondary_pick"),
        )

        out.at[i, "handicap_hit_result"] = _judge_hit(
            result_handicap,
            row.get("gemini_handicap_main_pick"),
            row.get("gemini_handicap_secondary_pick"),
        )

    return out



def build_hit_summary(eval_df: pd.DataFrame) -> dict[str, str | int]:
    total = len(eval_df)
    match_ended = int((eval_df["match_hit_result"] != "未开奖").sum()) if "match_hit_result" in eval_df.columns else 0
    handicap_ended = (
        int((eval_df["handicap_hit_result"] != "未开奖").sum()) if "handicap_hit_result" in eval_df.columns else 0
    )

    match_hit = int((eval_df.get("match_hit_result", pd.Series([], dtype="string")) == "命中").sum())
    handicap_hit = int((eval_df.get("handicap_hit_result", pd.Series([], dtype="string")) == "命中").sum())

    if match_ended > 0:
        match_rate = f"{match_hit} / {match_ended}（{(match_hit / match_ended) * 100:.1f}%）"
    else:
        match_rate = "0 / 0（0.0%）"

    if handicap_ended > 0:
        handicap_rate = f"{handicap_hit} / {handicap_ended}（{(handicap_hit / handicap_ended) * 100:.1f}%）"
    else:
        handicap_rate = "0 / 0（0.0%）"

    return {
        "total": total,
        "ended": match_ended,
        "match_rate": match_rate,
        "handicap_rate": handicap_rate,
    }
