from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


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
    return df
