from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from utils.common import sales_day_key as _sales_day_key

logger = logging.getLogger("result_evaluator")


@dataclass
class MatchStats:
    matched: int = 0
    skipped_cross_week: int = 0
    skip_samples: list[dict[str, str]] | None = None

    def __post_init__(self) -> None:
        if self.skip_samples is None:
            self.skip_samples = []


_PICK_ALIASES: dict[str, str] = {
    "平局": "平",
}


def _normalize_pick(value: object) -> str:
    s = str(value or "").strip()
    return _PICK_ALIASES.get(s, s)


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


def _pick_latest(matched: pd.DataFrame) -> pd.Series | None:
    if matched.empty:
        return None
    if "updated_at" in matched.columns:
        tdf = matched.copy()
        tdf["_updated_ts"] = pd.to_datetime(tdf["updated_at"], errors="coerce")
        tdf = tdf.sort_values("_updated_ts", ascending=True)
        return tdf.iloc[-1]
    return matched.iloc[-1]


def _match_row(pred_row: pd.Series, result_df: pd.DataFrame, stats: MatchStats) -> pd.Series | None:
    raw_id = _normalize_pick(pred_row.get("raw_id"))
    match_no = _normalize_pick(pred_row.get("match_no"))
    home_team = _normalize_pick(pred_row.get("home_team"))
    away_team = _normalize_pick(pred_row.get("away_team"))
    issue_date = _normalize_pick(pred_row.get("issue_date"))

    # 1) raw_id
    if raw_id and "raw_id" in result_df.columns:
        matched = result_df[result_df["raw_id"].astype(str) == raw_id]
        candidate = _pick_latest(matched)
        if candidate is not None:
            return candidate

    # 2) issue_date + match_no (core key)
    if issue_date and match_no and "issue_date" in result_df.columns and "match_no" in result_df.columns:
        matched = result_df[
            (result_df["issue_date"].astype(str) == issue_date) & (result_df["match_no"].astype(str) == match_no)
        ]
        candidate = _pick_latest(matched)
        if candidate is not None:
            return candidate

        # cross-week same-number diagnostics
        same_match_no_other_issue = result_df[result_df["match_no"].astype(str) == match_no]
        if not same_match_no_other_issue.empty:
            for _, r in same_match_no_other_issue.head(3).iterrows():
                res_issue = _normalize_pick(r.get("issue_date"))
                if res_issue and res_issue != issue_date:
                    stats.skipped_cross_week += 1
                    if len(stats.skip_samples or []) < 3:
                        (stats.skip_samples or []).append(
                            {
                                "result_issue_date": res_issue,
                                "result_match_no": _normalize_pick(r.get("match_no")),
                                "prediction_issue_date": issue_date,
                                "prediction_match_no": match_no,
                            }
                        )

    # 3) issue_date + home_team + away_team
    if issue_date and home_team and away_team and "issue_date" in result_df.columns:
        matched = result_df[
            (result_df["issue_date"].astype(str) == issue_date)
            & (result_df["home_team"].astype(str) == home_team)
            & (result_df["away_team"].astype(str) == away_team)
        ]
        candidate = _pick_latest(matched)
        if candidate is not None:
            return candidate

    # 4) match_no + home_team + away_team (issue_date missing fallback only)
    if (not issue_date) and match_no and home_team and away_team:
        matched = result_df[
            (result_df["match_no"].astype(str) == match_no)
            & (result_df["home_team"].astype(str) == home_team)
            & (result_df["away_team"].astype(str) == away_team)
        ]
        candidate = _pick_latest(matched)
        if candidate is not None:
            return candidate

    return None


def _prepare_result_df(result_df: pd.DataFrame) -> pd.DataFrame:
    out = result_df.copy()
    if "sales_day_key" not in out.columns:
        out["sales_day_key"] = out.apply(lambda r: _sales_day_key(r.get("issue_date"), r.get("match_no")), axis=1)
    return out


def _evaluate(pred_df: pd.DataFrame, result_df: pd.DataFrame, kind: str) -> pd.DataFrame:
    out = pred_df.copy()
    out["final_score"] = None
    out["match_hit_result"] = "未开奖"
    out["handicap_hit_result"] = "未开奖"
    out["sales_day_key"] = out.apply(lambda r: _sales_day_key(r.get("issue_date"), r.get("match_no")), axis=1)

    if result_df.empty:
        return out

    result_df = _prepare_result_df(result_df)
    stats = MatchStats()
    matched_result_indices: set[int] = set()

    for i, row in out.iterrows():
        matched = _match_row(row, result_df, stats)
        if matched is None:
            continue
        stats.matched += 1
        if hasattr(matched, "name"):
            try:
                matched_result_indices.add(int(matched.name))
            except Exception:
                pass

        out.at[i, "final_score"] = matched.get("full_time_score")

        if kind == "gemini":
            out.at[i, "match_hit_result"] = _judge_hit(
                matched.get("result_match"),
                row.get("gemini_match_main_pick"),
                row.get("gemini_match_secondary_pick"),
            )
            out.at[i, "handicap_hit_result"] = _judge_hit(
                matched.get("result_handicap"),
                row.get("gemini_handicap_main_pick"),
                row.get("gemini_handicap_secondary_pick"),
            )
        else:
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

    logger.info(
        "result match summary | kind=%s key_priority=raw_id>issue_date+match_no>issue_date+teams>match_no+teams(issue_date_missing) matched=%s skipped_cross_week=%s",
        kind,
        stats.matched,
        stats.skipped_cross_week,
    )
    if stats.skip_samples:
        logger.info("跨周同编号比赛已跳过，避免串场 samples=%s", stats.skip_samples)

    if not result_df.empty:
        unmatched_results = result_df.loc[~result_df.index.isin(matched_result_indices)].head(10)
        for _, r in unmatched_results.iterrows():
            logger.info(
                "未匹配赛果 sales_day_key=%s match_no=%s home=%s away=%s result_issue_date=%s full_time_score=%s",
                _sales_day_key(r.get("issue_date"), r.get("match_no")),
                r.get("match_no"),
                r.get("home_team"),
                r.get("away_team"),
                r.get("issue_date"),
                r.get("full_time_score"),
            )

    return out


def evaluate_predictions(pred_df: pd.DataFrame, result_df: pd.DataFrame) -> pd.DataFrame:
    return _evaluate(pred_df, result_df, kind="gemini")


def evaluate_chatgpt_predictions(pred_df: pd.DataFrame, result_df: pd.DataFrame) -> pd.DataFrame:
    return _evaluate(pred_df, result_df, kind="chatgpt")


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
