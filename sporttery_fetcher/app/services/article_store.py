from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ARTICLE_COLUMNS = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "article_title",
    "article_body",
    "generated_at",
    "source_model",
    "source_analysis_type",
    "wechat_upload_status",
    "wechat_draft_id",
    "wechat_uploaded_at",
    "wechat_error_message",
]


def article_csv_file(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(__file__).resolve().parents[2]
    p = root / "data" / "articles" / "wechat_articles.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in ARTICLE_COLUMNS:
        if c not in out.columns:
            out[c] = None
    return out[ARTICLE_COLUMNS]


def load_articles(base_dir: Path | None = None) -> pd.DataFrame:
    p = article_csv_file(base_dir)
    if not p.exists():
        return pd.DataFrame(columns=ARTICLE_COLUMNS)
    try:
        return _ensure_cols(pd.read_csv(p))
    except Exception:
        return pd.DataFrame(columns=ARTICLE_COLUMNS)


def _match_mask(df: pd.DataFrame, row: dict[str, Any]) -> pd.Series:
    return (
        (df["issue_date"].astype(str) == str(row.get("issue_date", "")))
        & (df["match_no"].astype(str) == str(row.get("match_no", "")))
        & (df["home_team"].astype(str) == str(row.get("home_team", "")))
        & (df["away_team"].astype(str) == str(row.get("away_team", "")))
    )


def save_article(record: dict[str, Any], base_dir: Path | None = None) -> tuple[Path, Path]:
    csv_path = article_csv_file(base_dir)
    existing = load_articles(base_dir)
    row = {k: record.get(k) for k in ARTICLE_COLUMNS}
    row.setdefault("wechat_upload_status", "未上传")
    row.setdefault("wechat_draft_id", None)
    row.setdefault("wechat_uploaded_at", None)
    row.setdefault("wechat_error_message", None)

    mask = ~_match_mask(existing, row)
    merged = pd.concat([existing[mask], pd.DataFrame([row])], ignore_index=True)
    _ensure_cols(merged).to_csv(csv_path, index=False, encoding="utf-8-sig")

    root = base_dir or Path(__file__).resolve().parents[2]
    safe_home = str(row.get("home_team", "home")).replace("/", "-")
    safe_away = str(row.get("away_team", "away")).replace("/", "-")
    issue_date = str(row.get("issue_date", datetime.now().date()))
    md_path = root / "data" / "articles" / f"{issue_date}_{safe_home}_vs_{safe_away}.md"
    md_path.write_text(f"# {row.get('article_title', '')}\n\n{row.get('article_body', '')}\n", encoding="utf-8")
    return csv_path, md_path


def update_wechat_upload_status(
    *,
    issue_date: str,
    match_no: str,
    home_team: str,
    away_team: str,
    status: str,
    draft_id: str | None,
    uploaded_at: str | None,
    error_message: str | None,
    base_dir: Path | None = None,
) -> Path:
    csv_path = article_csv_file(base_dir)
    df = load_articles(base_dir)
    if df.empty:
        return csv_path

    mask = _match_mask(
        df,
        {
            "issue_date": issue_date,
            "match_no": match_no,
            "home_team": home_team,
            "away_team": away_team,
        },
    )
    if mask.any():
        df.loc[mask, "wechat_upload_status"] = status
        df.loc[mask, "wechat_draft_id"] = draft_id
        df.loc[mask, "wechat_uploaded_at"] = uploaded_at
        df.loc[mask, "wechat_error_message"] = error_message

    _ensure_cols(df).to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path
