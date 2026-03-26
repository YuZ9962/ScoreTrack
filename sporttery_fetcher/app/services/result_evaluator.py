from __future__ import annotations

import logging
import pandas as pd

logger = logging.getLogger("result_evaluator")


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


def _date_from_text(value: object) -> str:
    text = _normalize_pick(value)
    if not text:
        return ""
    return text[:10]


def _pick_best_candidate(pred_row: pd.Series, matched: pd.DataFrame) -> pd.Series | None:
    if matched.empty:
        return None
    pred_issue_date = _normalize_pick(pred_row.get("issue_date"))
    if pred_issue_date and "issue_date" in matched.columns:
        same_date = matched[matched["issue_date"].astype(str) == pred_issue_date]
        if not same_date.empty:
            return same_date.iloc[-1]
    kickoff_date = _date_from_text(pred_row.get("kickoff_time"))
    if kickoff_date and "issue_date" in matched.columns:
        by_kickoff_date = matched[matched["issue_date"].astype(str) == kickoff_date]
        if not by_kickoff_date.empty:
            return by_kickoff_date.iloc[-1]
    return matched.iloc[-1]



def _match_row(pred_row: pd.Series, result_df: pd.DataFrame) -> pd.Series | None:
    raw_id = str(pred_row.get("raw_id", "") or "").strip()
    match_no = _normalize_pick(pred_row.get("match_no"))
    home_team = _normalize_pick(pred_row.get("home_team"))
    away_team = _normalize_pick(pred_row.get("away_team"))
    issue_date = _normalize_pick(pred_row.get("issue_date"))
    kickoff_date = _date_from_text(pred_row.get("kickoff_time"))

    if raw_id and "raw_id" in result_df.columns:
        matched = result_df[result_df["raw_id"].astype(str) == raw_id]
        if not matched.empty:
            return _pick_best_candidate(pred_row, matched)

    if match_no and home_team and away_team and "issue_date" in result_df.columns:
        matched = result_df[
            (result_df["issue_date"].astype(str) == issue_date)
            & (result_df["match_no"].astype(str) == match_no)
            & (result_df["home_team"].astype(str) == home_team)
            & (result_df["away_team"].astype(str) == away_team)
        ]
        if not matched.empty:
            return _pick_best_candidate(pred_row, matched)

    if match_no and home_team and away_team:
        matched = result_df[
            (result_df["match_no"].astype(str) == match_no)
            & (result_df["home_team"].astype(str) == home_team)
            & (result_df["away_team"].astype(str) == away_team)
        ]
        if not matched.empty:
            return _pick_best_candidate(pred_row, matched)

    if match_no and "match_no" in result_df.columns:
        matched = result_df[result_df["match_no"].astype(str) == match_no]
        if not matched.empty:
            return _pick_best_candidate(pred_row, matched)

    if home_team and away_team:
        matched = result_df[
            (result_df["home_team"].astype(str) == home_team)
            & (result_df["away_team"].astype(str) == away_team)
        ]
        if kickoff_date and "issue_date" in matched.columns:
            matched = matched[matched["issue_date"].astype(str) == kickoff_date]
        if not matched.empty:
            return _pick_best_candidate(pred_row, matched)

    return None



def evaluate_predictions(pred_df: pd.DataFrame, result_df: pd.DataFrame) -> pd.DataFrame:
    out = pred_df.copy()
    out["final_score"] = None
    out["match_hit_result"] = "未开奖"
    out["handicap_hit_result"] = "未开奖"

    if result_df.empty:
        return out

    matched_result_indices: set[int] = set()
    for i, row in out.iterrows():
        matched = _match_row(row, result_df)
        if matched is None:
            continue
        if hasattr(matched, "name"):
            try:
                matched_result_indices.add(int(matched.name))
            except Exception:
                pass

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

        pred_issue = _normalize_pick(row.get("issue_date"))
        res_issue = _normalize_pick(matched.get("issue_date"))
        if (
            _normalize_pick(row.get("match_no"))
            and _normalize_pick(row.get("match_no")) == _normalize_pick(matched.get("match_no"))
            and pred_issue
            and res_issue
            and pred_issue != res_issue
        ):
            logger.info(
                "按 match_no 跨天匹配成功 match_no=%s home=%s away=%s result_issue_date=%s prediction_issue_date=%s",
                row.get("match_no"),
                row.get("home_team"),
                row.get("away_team"),
                res_issue,
                pred_issue,
            )
        else:
            logger.info(
                "赛果匹配成功 match_no=%s home=%s away=%s result_issue_date=%s prediction_issue_date=%s",
                row.get("match_no"),
                row.get("home_team"),
                row.get("away_team"),
                res_issue,
                pred_issue,
            )

    if not result_df.empty:
        unmatched_results = result_df.loc[~result_df.index.isin(matched_result_indices)].head(10)
        for _, r in unmatched_results.iterrows():
            logger.info(
                "未匹配赛果 match_no=%s home=%s away=%s result_issue_date=%s full_time_score=%s",
                r.get("match_no"),
                r.get("home_team"),
                r.get("away_team"),
                r.get("issue_date"),
                r.get("full_time_score"),
            )

    return out


def evaluate_chatgpt_predictions(pred_df: pd.DataFrame, result_df: pd.DataFrame) -> pd.DataFrame:
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
        out.at[i, "final_score"] = matched.get("full_time_score")
        out.at[i, "match_hit_result"] = _judge_hit(
            matched.get("result_match"),
            row.get("chatgpt_match_main_pick"),
            row.get("chatgpt_match_secondary_pick"),
        )
        out.at[i, "handicap_hit_result"] = _judge_hit(
            matched.get("result_handicap"),
            row.get("chatgpt_handicap_main_pick"),
            row.get("chatgpt_handicap_secondary_pick"),
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
