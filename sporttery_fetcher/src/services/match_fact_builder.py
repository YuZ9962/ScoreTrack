from __future__ import annotations

"""
match_fact_builder.py
=====================
统一比赛事实表构建器（Single Source of Truth 消费层）。

架构原则：
- 原始层保留不动（processed/*.csv / predictions/*.csv / results/*.csv）
- 事实层是只读消费层，由此处负责合并构建
- 所有 merge 优先通过 match_key；旧数据缺列时现场补算

数据流：
  processed/*_matches.csv   ─┐
  manual/history_matches.csv ─┤
                              ├─► merge_match_facts ─► data/facts/match_facts.csv
  gemini_predictions.csv    ─┤
  chatgpt_predictions.csv   ─┤
  clean_match_results.csv   ─┘
"""

import logging
from pathlib import Path
from typing import Any

import pandas as pd
from filelock import FileLock

try:
    from src.utils.logger import get_logger
    logger = get_logger("match_fact_builder")
except Exception:
    logger = logging.getLogger("match_fact_builder")

# ──────────────────────────────────────────────────────────────────────────────
# 事实表字段定义
# ──────────────────────────────────────────────────────────────────────────────

FACT_COLUMNS: list[str] = [
    # ── 核心 identity ──
    "match_key",
    "raw_id",
    "issue_date",
    "match_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "sell_status",
    "source_url",
    "scrape_time",
    "data_source",
    "updated_at",
    # ── 赔率 ──
    "spf_win",
    "spf_draw",
    "spf_lose",
    "rqspf_win",
    "rqspf_draw",
    "rqspf_lose",
    # ── 赛果 ──
    "full_time_score",
    "half_time_score",
    "result_match",
    "result_handicap",
    "result_status",   # "已开奖" / "未开奖" / ""
    # ── Gemini 预测 ──
    "gemini_prediction_status",   # success / manual_filled / failed / ""
    "gemini_match_main_pick",
    "gemini_match_secondary_pick",
    "gemini_handicap_main_pick",
    "gemini_handicap_secondary_pick",
    "gemini_score_1",
    "gemini_score_2",
    "gemini_summary",
    "gemini_raw_text",
    "gemini_generated_at",
    # ── ChatGPT 预测 ──
    "chatgpt_prediction_status",  # present / absent
    "chatgpt_match_main_pick",
    "chatgpt_match_secondary_pick",
    "chatgpt_handicap_main_pick",
    "chatgpt_handicap_secondary_pick",
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
    "chatgpt_raw_text",
    "chatgpt_generated_at",
    # ── 命中评估 ──
    "gemini_match_hit",      # 命中 / 未命中 / 未开奖
    "gemini_handicap_hit",
    "chatgpt_match_hit",
    "chatgpt_handicap_hit",
    # ── 元信息 ──
    "fact_built_at",
]

FACTS_DIR = "facts"
FACTS_FILE = "match_facts.csv"


# ──────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────────────

def _root(base_dir: Path | None) -> Path:
    return base_dir or Path(__file__).resolve().parents[2]


def _facts_path(base_dir: Path | None = None) -> Path:
    p = _root(base_dir) / "data" / FACTS_DIR / FACTS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


from src.utils.shared_utils import now_iso as _now_iso


def _ensure_mk(df: pd.DataFrame) -> pd.DataFrame:
    """为缺少 match_key 的行现场补算。"""
    if df.empty:
        return df
    if "match_key" not in df.columns:
        df = df.copy()
        df["match_key"] = None

    missing = df["match_key"].isna() | (df["match_key"].astype(str).str.strip() == "")
    if missing.any():
        try:
            from src.domain.match_identity import build_match_key
            df.loc[missing, "match_key"] = df[missing].apply(
                lambda r: build_match_key(r.to_dict()), axis=1
            )
        except Exception:
            # 兜底：构造 biz:key
            def _fallback(r: pd.Series) -> str:
                d = str(r.get("issue_date") or "").strip()
                n = str(r.get("match_no") or "").strip()
                h = str(r.get("home_team") or "").strip()
                a = str(r.get("away_team") or "").strip()
                rid = str(r.get("raw_id") or "").strip()
                if rid:
                    return f"raw:{rid}"
                return f"biz:{d}|{n}|{h}|{a}"

            df.loc[missing, "match_key"] = df[missing].apply(_fallback, axis=1)
    return df


def _ensure_col(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """确保 DataFrame 含有指定列（缺列补 None）。"""
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df


def _normalize_text(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v).strip()


def _judge_hit(real_result: Any, main_pick: Any, secondary_pick: Any) -> str:
    """复用 result_evaluator 的命中判断逻辑（独立实现，避免循环导入）。"""
    real = _normalize_text(real_result)
    if not real or real == "未开奖":
        return "未开奖"
    main = _normalize_text(main_pick)
    if main and real == main:
        return "命中"
    sec = _normalize_text(secondary_pick)
    if sec and sec != "无" and real == sec:
        return "命中"
    return "未命中"


# ──────────────────────────────────────────────────────────────────────────────
# 数据加载层
# ──────────────────────────────────────────────────────────────────────────────

def load_match_base_records(base_dir: Path | None = None) -> pd.DataFrame:
    """加载所有基础比赛记录（processed/*.csv + manual/history_matches.csv）。"""
    root = _root(base_dir)
    frames: list[pd.DataFrame] = []

    processed_dir = root / "data" / "processed"
    if processed_dir.exists():
        for f in sorted(processed_dir.glob("*_matches.csv")):
            try:
                df = pd.read_csv(f)
                date_part = f.name.replace("_matches.csv", "")
                if "issue_date" not in df.columns:
                    df["issue_date"] = date_part
                frames.append(df)
            except Exception:
                logger.warning("无法读取 %s", f)

    manual_file = root / "data" / "manual" / "history_matches.csv"
    if manual_file.exists():
        try:
            df = pd.read_csv(manual_file)
            if "data_source" not in df.columns:
                df["data_source"] = "manual"
            frames.append(df)
        except Exception:
            logger.warning("无法读取手动补录文件 %s", manual_file)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    result = _ensure_mk(result)
    return result


def load_gemini_prediction_records(base_dir: Path | None = None) -> pd.DataFrame:
    """加载 Gemini 预测表。"""
    root = _root(base_dir)
    path = root / "data" / "predictions" / "gemini_predictions.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    df = _ensure_mk(df)
    return df


def load_chatgpt_prediction_records(base_dir: Path | None = None) -> pd.DataFrame:
    """加载 ChatGPT 预测表。"""
    root = _root(base_dir)
    path = root / "data" / "predictions" / "chatgpt_predictions.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    df = _ensure_mk(df)
    return df


def load_clean_result_records(base_dir: Path | None = None) -> pd.DataFrame:
    """加载 clean 赛果表（优先 clean，降级 raw）。"""
    try:
        from src.services.result_cleaner import load_clean_results
        df = load_clean_results(base_dir)
        if not df.empty:
            return _ensure_mk(df)
    except Exception:
        pass
    # 降级：直接读文件
    root = _root(base_dir)
    for fname in ("clean_match_results.csv", "match_results.csv"):
        p = root / "data" / "results" / fname
        if p.exists():
            try:
                df = pd.read_csv(p)
                return _ensure_mk(df)
            except Exception:
                pass
    return pd.DataFrame()


# ──────────────────────────────────────────────────────────────────────────────
# 命中评估
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_fact_hits(df: pd.DataFrame) -> pd.DataFrame:
    """在事实表上原地计算命中评估字段（依赖已合并的预测+赛果字段）。"""
    out = df.copy()

    out["gemini_match_hit"] = out.apply(
        lambda r: _judge_hit(
            r.get("result_match"),
            r.get("gemini_match_main_pick"),
            r.get("gemini_match_secondary_pick"),
        ),
        axis=1,
    )
    out["gemini_handicap_hit"] = out.apply(
        lambda r: _judge_hit(
            r.get("result_handicap"),
            r.get("gemini_handicap_main_pick"),
            r.get("gemini_handicap_secondary_pick"),
        ),
        axis=1,
    )
    out["chatgpt_match_hit"] = out.apply(
        lambda r: _judge_hit(
            r.get("result_match"),
            r.get("chatgpt_match_main_pick"),
            r.get("chatgpt_match_secondary_pick"),
        ),
        axis=1,
    )
    out["chatgpt_handicap_hit"] = out.apply(
        lambda r: _judge_hit(
            r.get("result_handicap"),
            r.get("chatgpt_handicap_main_pick"),
            r.get("chatgpt_handicap_secondary_pick"),
        ),
        axis=1,
    )
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 合并逻辑
# ──────────────────────────────────────────────────────────────────────────────

def _merge_left_by_match_key(
    base: pd.DataFrame,
    right: pd.DataFrame,
    right_cols: list[str],
    rename_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    把 right 的 right_cols 列合并到 base，按 match_key left-join。
    right 里相同 match_key 保留最新一条（按 generated_at 或最后一条）。
    rename_map 允许重命名 right 列（例如 prediction_status → gemini_prediction_status）。
    """
    if right.empty or "match_key" not in right.columns:
        return base

    cols_to_take = ["match_key"] + [c for c in right_cols if c in right.columns]
    sub = right[cols_to_take].copy()

    if rename_map:
        sub = sub.rename(columns=rename_map)
        right_cols = [rename_map.get(c, c) for c in right_cols]

    # 去重：同 match_key 保最后一条
    sub = sub.drop_duplicates(subset=["match_key"], keep="last")

    # 去掉 base 里已有的目标列，避免 merge 后出现 _x/_y 后缀
    merged_cols = [c for c in right_cols if c in sub.columns]
    base = base.drop(columns=[c for c in merged_cols if c in base.columns], errors="ignore")

    result = base.merge(sub[["match_key"] + merged_cols], on="match_key", how="left")
    return result


def merge_match_facts(
    base_df: pd.DataFrame,
    gemini_df: pd.DataFrame,
    chatgpt_df: pd.DataFrame,
    result_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    将四张表合并为统一事实表。
    优先通过 match_key join；所有 join 均为 left join（以 base 为准）。
    """
    if base_df.empty:
        logger.warning("base_df 为空，无法构建事实表")
        return pd.DataFrame(columns=FACT_COLUMNS)

    df = base_df.copy()
    df = _ensure_mk(df)

    # 去重：同一 match_key 只保留最新（按 scrape_time 降序）
    if "scrape_time" in df.columns:
        df["_st"] = pd.to_datetime(df["scrape_time"], errors="coerce")
        df = df.sort_values("_st", ascending=False).drop_duplicates(subset=["match_key"], keep="first")
        df = df.drop(columns=["_st"])
    else:
        df = df.drop_duplicates(subset=["match_key"], keep="last")

    # ── Gemini 预测 ──
    gemini_cols = [
        "prediction_status",
        "gemini_match_main_pick",
        "gemini_match_secondary_pick",
        "gemini_handicap_main_pick",
        "gemini_handicap_secondary_pick",
        "gemini_score_1",
        "gemini_score_2",
        "gemini_summary",
        "gemini_raw_text",
        "raw_text",
        "gemini_generated_at",
    ]
    df = _merge_left_by_match_key(
        df,
        gemini_df,
        gemini_cols,
        rename_map={"prediction_status": "gemini_prediction_status", "raw_text": "gemini_raw_text"},
    )
    # gemini_raw_text 可能被 rename 覆盖，确保列存在
    if "gemini_raw_text" not in df.columns:
        df["gemini_raw_text"] = None

    # ── ChatGPT 预测 ──
    chatgpt_cols = [
        "chatgpt_match_main_pick",
        "chatgpt_match_secondary_pick",
        "chatgpt_handicap_main_pick",
        "chatgpt_handicap_secondary_pick",
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
        "chatgpt_raw_text",
        "chatgpt_generated_at",
    ]
    df = _merge_left_by_match_key(df, chatgpt_df, chatgpt_cols)
    # 补充 chatgpt_prediction_status
    if "chatgpt_generated_at" in df.columns:
        df["chatgpt_prediction_status"] = df["chatgpt_generated_at"].apply(
            lambda v: "present" if _normalize_text(v) else "absent"
        )
    else:
        df["chatgpt_prediction_status"] = "absent"

    # ── 赛果 ──
    result_cols = [
        "full_time_score",
        "result_match",
        "result_handicap",
    ]
    if not result_df.empty:
        result_sub = _ensure_mk(result_df)
        df = _merge_left_by_match_key(df, result_sub, result_cols)

        # 回退：match_key 不一致时（base=raw:xxx, result=biz:...），
        # 对仍无 full_time_score 的行尝试用业务复合键二次 join
        unmatched_mask = df["full_time_score"].isna() | (df["full_time_score"].astype(str).str.strip() == "")
        if unmatched_mask.any():
            # issue_date + match_no 在同一销售日内唯一，无需加队名
            # （API base 用全称，zqsgkj result 用简称，两者不匹配）
            BIZ_KEYS = ["issue_date", "match_no"]
            result_biz = result_sub.copy()
            for k in BIZ_KEYS:
                if k in result_biz.columns:
                    result_biz[k] = result_biz[k].astype(str).str.strip()
                else:
                    result_biz[k] = ""
            result_biz = result_biz.drop_duplicates(subset=BIZ_KEYS, keep="last")

            # 取 base 中未匹配的行，保留原始 index
            unmatched_idx = df.index[unmatched_mask]
            unmatched_df = df.loc[unmatched_idx].copy()
            for k in BIZ_KEYS:
                if k in unmatched_df.columns:
                    unmatched_df[k] = unmatched_df[k].astype(str).str.strip()
                else:
                    unmatched_df[k] = ""

            cols_needed = BIZ_KEYS + [c for c in result_cols if c in result_biz.columns]
            fill = (
                unmatched_df
                .drop(columns=[c for c in result_cols if c in unmatched_df.columns], errors="ignore")
                .reset_index(drop=False)
                .merge(result_biz[cols_needed], on=BIZ_KEYS, how="left")
                .set_index("index")
            )

            # 将查到结果的行写回 df（仅覆盖有值的格子，index 对齐）
            filled_count = 0
            for c in result_cols:
                if c in fill.columns:
                    has_value = fill[c].notna() & (fill[c].astype(str).str.strip() != "")
                    if has_value.any():
                        df.loc[fill.index[has_value], c] = fill.loc[has_value, c]
                        filled_count += int(has_value.sum())

            logger.info(
                "result fallback biz-key join: unmatched_rows=%s filled_cells=%s",
                int(unmatched_mask.sum()),
                filled_count,
            )

    # result_status 衍生字段
    df["result_status"] = df.apply(
        lambda r: "已开奖" if _normalize_text(r.get("result_match")) not in ("", "未开奖") else "未开奖",
        axis=1,
    )

    # half_time_score：result_df 里可能有（raw 层有 half_time_score）
    if "half_time_score" not in df.columns:
        df["half_time_score"] = None

    # ── 命中评估 ──
    df = evaluate_fact_hits(df)

    # ── 时间戳 ──
    df["fact_built_at"] = _now_iso()

    # ── 对齐最终字段 ──
    for c in FACT_COLUMNS:
        if c not in df.columns:
            df[c] = None

    return df[FACT_COLUMNS].reset_index(drop=True)


# ──────────────────────────────────────────────────────────────────────────────
# 存储
# ──────────────────────────────────────────────────────────────────────────────

def save_match_facts(df: pd.DataFrame, base_dir: Path | None = None) -> Path:
    """将事实表写入 data/facts/match_facts.csv（文件锁保护）。"""
    path = _facts_path(base_dir)
    lock = FileLock(str(path) + ".lock", timeout=15)
    with lock:
        df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("事实表已写入 path=%s rows=%s", path, len(df))
    return path


def load_match_facts(base_dir: Path | None = None) -> pd.DataFrame:
    """读取已有事实表；不存在则返回空 DataFrame。"""
    path = _facts_path(base_dir)
    if not path.exists():
        return pd.DataFrame(columns=FACT_COLUMNS)
    try:
        df = pd.read_csv(path)
        for c in FACT_COLUMNS:
            if c not in df.columns:
                df[c] = None
        return df[FACT_COLUMNS]
    except Exception:
        return pd.DataFrame(columns=FACT_COLUMNS)


# ──────────────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────────────

def rebuild_match_facts(base_dir: Path | None = None) -> dict[str, Any]:
    """
    全量重建事实表。
    失败时不抛出异常，只记录日志并返回 ok=False，确保调用方主流程不中断。
    """
    try:
        base_df = load_match_base_records(base_dir)
        gemini_df = load_gemini_prediction_records(base_dir)
        chatgpt_df = load_chatgpt_prediction_records(base_dir)
        result_df = load_clean_result_records(base_dir)

        facts_df = merge_match_facts(base_df, gemini_df, chatgpt_df, result_df)
        path = save_match_facts(facts_df, base_dir)

        logger.info(
            "事实表重建完成 rows=%s gemini_rows=%s chatgpt_rows=%s result_rows=%s path=%s",
            len(facts_df),
            len(gemini_df),
            len(chatgpt_df),
            len(result_df),
            path,
        )
        return {
            "ok": True,
            "rows": len(facts_df),
            "path": str(path),
        }
    except Exception as exc:
        logger.exception("事实表重建失败 err=%s", type(exc).__name__)
        return {"ok": False, "error": str(exc)}
