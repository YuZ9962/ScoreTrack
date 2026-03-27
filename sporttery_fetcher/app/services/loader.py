from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from services.chatgpt_store import load_chatgpt_predictions as _load_chatgpt_predictions
from services.prediction_store import load_predictions as _load_predictions
from services.result_cleaner import load_clean_results


@dataclass
class DataContext:
    data_dir: Path
    files: list[Path]


def get_data_context(base_dir: Path | None = None) -> DataContext:
    base = base_dir or Path(__file__).resolve().parents[2]
    data_dir = base / "data" / "processed"
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
    root = base_dir or Path(__file__).resolve().parents[2]
    return root / "data" / "manual" / "history_matches.csv"


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

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def results_file(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(__file__).resolve().parents[2]
    path = root / "data" / "results" / "match_results.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


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
