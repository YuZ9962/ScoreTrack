from __future__ import annotations

"""
Data Layer Contract
===================
All read access from the app layer goes through this module (loader.py).
Write access goes through the designated store module for each domain.

File                                    Owner                   Schema ref
----                                    -----                   ----------
data/processed/{date}_matches.csv       src/utils/save.py       PROCESSED_MATCH_COLUMNS
data/manual/history_matches.csv         manual_entry_store.py   MATCH_COLUMNS
data/predictions/gemini_predictions.csv prediction_store.py     PREDICTION_COLUMNS
data/predictions/chatgpt_*.csv          chatgpt_store.py        CHATGPT_COLUMNS
data/results/raw_match_results.csv      result_cleaner.py       RAW_COLUMNS
data/results/clean_match_results.csv    result_cleaner.py       RESULT_COLUMNS
data/results/bad_match_results.csv      result_cleaner.py       BAD_COLUMNS
data/facts/match_facts.csv              match_fact_builder.py   FACT_COLUMNS
data/articles/wechat_articles.csv       article_store.py        ARTICLE_COLUMNS

Trigger chain (write → rebuild):
  Any store save  →  rebuild_match_facts()  →  data/facts/match_facts.csv
  result_cleaner.append_raw_results()  →  rebuild_clean_results()  →  clean_match_results.csv
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from services.chatgpt_store import load_chatgpt_predictions as _load_chatgpt_predictions
from utils.data_paths import legacy_results_file, manual_matches_file, processed_dir
from services.prediction_store import load_predictions as _load_predictions
from src.services.result_cleaner import load_clean_results
from services.transforms import ensure_issue_date_columns
from src.services.match_fact_builder import (
    load_match_facts as _load_facts,
    rebuild_match_facts as _rebuild_facts,
    FACT_COLUMNS,
)


@dataclass
class DataContext:
    data_dir: Path
    files: list[Path]


def get_data_context(base_dir: Path | None = None) -> DataContext:
    data_dir = processed_dir(base_dir)
    files = sorted(data_dir.glob("*_matches.csv"))
    return DataContext(data_dir=data_dir, files=files)


def available_date_options(ctx: DataContext) -> list[str]:
    options: list[str] = []
    for f in ctx.files:
        date_part = f.name.split("_matches.csv")[0]
        options.append(date_part)
    return options


def get_latest_date(ctx: DataContext) -> str | None:
    options = available_date_options(ctx)
    if not options:
        return None
    return sorted(options)[-1]


def load_matches_by_date(date_str: str, ctx: DataContext) -> pd.DataFrame:
    target = ctx.data_dir / f"{date_str}_matches.csv"
    if not target.exists():
        raise FileNotFoundError(f"未找到数据文件: {target}")

    df = pd.read_csv(target)
    if "issue_date" not in df.columns:
        df["issue_date"] = date_str
    return df


def _manual_match_file(base_dir: Path | None = None) -> Path:
    return manual_matches_file(base_dir)


def _concat_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    valid = [f for f in frames if isinstance(f, pd.DataFrame) and not f.empty]
    if not valid:
        return pd.DataFrame()
    all_cols: list[str] = []
    for frame in valid:
        for col in frame.columns:
            if col not in all_cols:
                all_cols.append(col)
    aligned = [frame.reindex(columns=all_cols) for frame in valid]
    if len(aligned) == 1:
        return aligned[0].reset_index(drop=True)
    return pd.concat(aligned, ignore_index=True)


def load_all_matches(ctx: DataContext, base_dir: Path | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for file_path in ctx.files:
        date_part = file_path.name.split("_matches.csv")[0]
        try:
            df = pd.read_csv(file_path)
        except Exception:
            continue
        if "issue_date" not in df.columns:
            df["issue_date"] = date_part
        frames.append(df)

    manual_file = _manual_match_file(base_dir)
    if manual_file.exists():
        try:
            manual_df = pd.read_csv(manual_file)
            if not manual_df.empty:
                if "issue_date" not in manual_df.columns:
                    manual_df["issue_date"] = ""
                if "data_source" not in manual_df.columns:
                    manual_df["data_source"] = "manual"
                frames.append(manual_df)
        except Exception:
            pass

    return _concat_frames(frames)


def results_file(base_dir: Path | None = None) -> Path:
    return legacy_results_file(base_dir)


def load_results(base_dir: Path | None = None) -> pd.DataFrame:
    clean_df = load_clean_results(base_dir)
    if not clean_df.empty:
        return clean_df

    path = results_file(base_dir)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_chatgpt_predictions(base_dir: Path | None = None) -> pd.DataFrame:
    return _load_chatgpt_predictions(base_dir)


def load_recommendation_inputs(
    date_str: str, ctx: DataContext, base_dir: Path | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    matches_df = load_matches_by_date(date_str, ctx)

    gemini_df = _load_predictions(base_dir)
    if not gemini_df.empty and "issue_date" in gemini_df.columns:
        gemini_df = gemini_df[gemini_df["issue_date"].astype(str) == str(date_str)].copy()

    chatgpt_df = _load_chatgpt_predictions(base_dir)
    if not chatgpt_df.empty and "issue_date" in chatgpt_df.columns:
        chatgpt_df = chatgpt_df[chatgpt_df["issue_date"].astype(str) == str(date_str)].copy()

    return matches_df, gemini_df, chatgpt_df


def load_gemini_predictions_by_date(date_str: str, base_dir: Path | None = None) -> pd.DataFrame:
    gemini_df = _load_predictions(base_dir)
    if gemini_df.empty:
        return gemini_df
    if "issue_date" not in gemini_df.columns:
        return pd.DataFrame()
    return gemini_df[gemini_df["issue_date"].astype(str) == str(date_str)].copy()


# ──────────────────────────────────────────────────────────────────────────────
# 事实表接口（统一消费层）
# ──────────────────────────────────────────────────────────────────────────────

def load_match_facts(base_dir: Path | None = None) -> pd.DataFrame:
    """读取已建好的事实表。不存在时返回空 DataFrame（不触发重建）。"""
    return _load_facts(base_dir)


def load_match_facts_by_date(date_str: str, base_dir: Path | None = None) -> pd.DataFrame:
    """按销售日 issue_date 筛选事实表（支持从 kickoff_time 推断缺失 issue_date）。"""
    df = _load_facts(base_dir)
    if df.empty:
        return pd.DataFrame(columns=FACT_COLUMNS)
    enriched = ensure_issue_date_columns(df, source_col="issue_date")
    return enriched[enriched["_date"].astype(str) == str(date_str)].copy()


def get_or_rebuild_match_facts(base_dir: Path | None = None) -> pd.DataFrame:
    """
    读取事实表；若不存在则触发一次全量重建后返回。
    适合页面启动时调用。重建失败则返回空表（不中断流程）。
    """
    df = _load_facts(base_dir)
    if not df.empty:
        return df
    _rebuild_facts(base_dir)
    return _load_facts(base_dir)
