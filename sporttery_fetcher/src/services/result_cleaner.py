from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

RESULT_COLUMNS = [
    "issue_date",
    "match_no",
    "sales_day_key",
    "home_team",
    "away_team",
    "raw_id",
    "full_time_score",
    "result_match",
    "result_handicap",
    "data_source",
    "updated_at",
]

RAW_COLUMNS = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "handicap",
    "kickoff_time",
    "half_time_score",
    "full_time_score",
    "half_score",
    "full_score",
    "result_match",
    "result_handicap",
    "raw_result_text",
    "result_generated_at",
    "raw_id",
    "data_source",
    "source_url",
    "scrape_time",
    "match_date",
    "updated_at",
]

BAD_COLUMNS = RAW_COLUMNS + ["bad_reason"]

VALID_SCORE_RE = re.compile(r"^\d{1,2}-\d{1,2}$")
SCORE_ANY_RE = re.compile(r"^(\d{1,2})\s*[-:：]\s*(\d{1,2})$")
VALID_MATCH = {"主胜", "平", "客胜", "未开奖"}
VALID_HANDICAP = {"让胜", "让平", "让负", "未开奖"}
VALID_SOURCE = {"auto_result_fetch", "manual_entry", "history_fetch", "repair_script"}
UNOPENED_KEYWORDS = (
    "未开奖",
    "待开奖",
    "待开",
    "开奖中",
    "未出",
    "未完",
    "待定",
    "进行中",
    "延期",
    "推迟",
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def result_paths(base_dir: Path | None = None) -> dict[str, Path]:
    root = base_dir or Path(__file__).resolve().parents[2]
    result_dir = root / "data" / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    return {
        "legacy": result_dir / "match_results.csv",
        "raw": result_dir / "raw_match_results.csv",
        "clean": result_dir / "clean_match_results.csv",
        "bad": result_dir / "bad_match_results.csv",
    }


def _read_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=columns)
    for c in columns:
        if c not in df.columns:
            df[c] = None
    return df[columns]


def _normalize_text(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v).strip()


def _normalize_score(score: str | None) -> str:
    text = _normalize_text(score)
    m = SCORE_ANY_RE.match(text)
    if not m:
        return ""
    return f"{int(m.group(1))}-{int(m.group(2))}"


def _parse_score(score: str | None) -> tuple[int, int] | None:
    text = _normalize_score(score)
    m = SCORE_ANY_RE.match(text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_handicap_int(handicap: str | None) -> int | None:
    text = _normalize_text(handicap)
    if not text:
        return None
    m = re.search(r"([+-]?\d+)", text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _is_invalid_date_like_score(score: str) -> bool:
    if not VALID_SCORE_RE.match(score):
        return True
    a, b = [int(x) for x in score.split("-")]
    if a >= 20 and 1 <= b <= 12:
        return True
    if b >= 20 and 1 <= a <= 12:
        return True
    return False


def _derive_match(score: str | None) -> str:
    parsed = _parse_score(score)
    if parsed is None:
        return "未开奖"
    home, away = parsed
    if home > away:
        return "主胜"
    if home == away:
        return "平"
    return "客胜"


def _derive_handicap_result(score: str | None, handicap: str | None) -> str:
    parsed = _parse_score(score)
    hcap = _parse_handicap_int(handicap)
    if parsed is None or hcap is None:
        return "未开奖"
    home, away = parsed
    adj = home + hcap
    if adj > away:
        return "让胜"
    if adj == away:
        return "让平"
    return "让负"


def _raw_text_indicates_unopened(raw_result_text: str) -> bool:
    text = _normalize_text(raw_result_text)
    if not text:
        return False
    return any(keyword in text for keyword in UNOPENED_KEYWORDS)


def _is_unopened_record(score: str, result_match: str, result_handicap: str, raw_result_text: str) -> bool:
    if result_match == "未开奖" or result_handicap == "未开奖":
        return True
    if not score and _raw_text_indicates_unopened(raw_result_text):
        return True
    return False


def _sales_day_key(issue_date: object, match_no: object) -> str:
    issue = _normalize_text(issue_date)
    no = _normalize_text(match_no)
    if issue and no:
        return f"{issue}_{no}"
    return ""


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    raw_id = _normalize_text(row.get("raw_id"))
    match_no = _normalize_text(row.get("match_no"))
    issue_date = _normalize_text(row.get("issue_date"))
    home = _normalize_text(row.get("home_team"))
    away = _normalize_text(row.get("away_team"))

    if raw_id:
        return ("raw_id", raw_id)
    if match_no and issue_date:
        return ("match_no_issue_date", f"{match_no}|{issue_date}")
    if match_no and home and away:
        return ("match_no_teams", f"{match_no}|{home}|{away}")
    return ("invalid", "")


def _normalize_row(row: dict[str, Any], default_source: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    out = {k: row.get(k) for k in RAW_COLUMNS}
    out["issue_date"] = _normalize_text(out.get("issue_date"))
    out["match_no"] = _normalize_text(out.get("match_no"))
    out["home_team"] = _normalize_text(out.get("home_team"))
    out["away_team"] = _normalize_text(out.get("away_team"))
    out["raw_id"] = _normalize_text(out.get("raw_id")) or None
    out["raw_result_text"] = _normalize_text(out.get("raw_result_text"))
    out["handicap"] = _normalize_text(out.get("handicap"))

    # 字段别名兼容：history 抓取常见 full_score / half_score
    full_time_score = _normalize_text(out.get("full_time_score"))
    if not full_time_score:
        full_time_score = _normalize_text(out.get("full_score"))
    full_time_score = _normalize_score(full_time_score)

    half_time_score = _normalize_text(out.get("half_time_score"))
    if not half_time_score:
        half_time_score = _normalize_text(out.get("half_score"))
    out["half_time_score"] = half_time_score
    out["full_time_score"] = full_time_score

    src = _normalize_text(out.get("data_source")) or default_source
    out["data_source"] = src if src in VALID_SOURCE else default_source
    out["updated_at"] = _normalize_text(out.get("updated_at")) or _now_iso()

    if not out["issue_date"]:
        bad = {**out, "bad_reason": "issue_date 为空"}
        return None, bad, False
    if not out["match_no"]:
        bad = {**out, "bad_reason": "match_no 为空"}
        return None, bad, False
    if not out["home_team"] or not out["away_team"]:
        bad = {**out, "bad_reason": "home_team 或 away_team 为空"}
        return None, bad, False

    key_type, _ = _row_key(out)
    if key_type == "invalid":
        bad = {**out, "bad_reason": "唯一键缺失(raw_id/match_no+issue_date/match_no+teams)"}
        return None, bad, False

    result_match = _normalize_text(out.get("result_match"))
    result_handicap = _normalize_text(out.get("result_handicap"))
    score = out["full_time_score"]

    is_unopened = _is_unopened_record(
        score=score,
        result_match=result_match,
        result_handicap=result_handicap,
        raw_result_text=out["raw_result_text"],
    )

    if is_unopened:
        clean = {
            "issue_date": out["issue_date"],
            "match_no": out["match_no"],
            "sales_day_key": _sales_day_key(out["issue_date"], out["match_no"]),
            "home_team": out["home_team"],
            "away_team": out["away_team"],
            "raw_id": out["raw_id"],
            "full_time_score": score,
            "result_match": "未开奖",
            "result_handicap": "未开奖",
            "data_source": out["data_source"],
            "updated_at": out["updated_at"],
        }
        return clean, None, True

    if not score:
        bad = {**out, "bad_reason": "无法解析 full_time_score"}
        return None, bad, False
    if _is_invalid_date_like_score(score):
        bad = {**out, "bad_reason": f"比分字段格式非法: {score}"}
        return None, bad, False

    if result_match not in VALID_MATCH or result_match == "未开奖":
        result_match = _derive_match(score)
    if result_match == "未开奖":
        bad = {**out, "bad_reason": "无法计算 result_match"}
        return None, bad, False

    if result_handicap not in VALID_HANDICAP or result_handicap == "未开奖":
        result_handicap = _derive_handicap_result(score, out.get("handicap"))
    if result_handicap == "未开奖":
        bad = {**out, "bad_reason": "无法计算 result_handicap"}
        return None, bad, False

    clean = {
        "issue_date": out["issue_date"],
        "match_no": out["match_no"],
        "sales_day_key": _sales_day_key(out["issue_date"], out["match_no"]),
        "home_team": out["home_team"],
        "away_team": out["away_team"],
        "raw_id": out["raw_id"],
        "full_time_score": score,
        "result_match": result_match,
        "result_handicap": result_handicap,
        "data_source": out["data_source"],
        "updated_at": out["updated_at"],
    }

    return clean, None, False


def _dedup_clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    df = pd.DataFrame(rows)
    if "updated_at" not in df.columns:
        df["updated_at"] = _now_iso()
    df["updated_at"] = df["updated_at"].fillna("").astype(str)
    df["_updated_ts"] = pd.to_datetime(df["updated_at"], errors="coerce")
    df = df.sort_values("_updated_ts", ascending=True)

    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for _, r in df.iterrows():
        row = r.to_dict()
        key = _row_key(row)
        if key[0] == "invalid":
            continue
        buckets[key] = {k: row.get(k) for k in RESULT_COLUMNS}

    return list(buckets.values())


def _count_unopened_rows(raw_df: pd.DataFrame) -> int:
    if raw_df.empty:
        return 0
    count = 0
    for _, row in raw_df.iterrows():
        score = _normalize_score(row.get("full_time_score") or row.get("full_score"))
        result_match = _normalize_text(row.get("result_match"))
        result_handicap = _normalize_text(row.get("result_handicap"))
        raw_result_text = _normalize_text(row.get("raw_result_text"))
        if _is_unopened_record(score, result_match, result_handicap, raw_result_text):
            count += 1
    return count


def rebuild_clean_results(base_dir: Path | None = None, source_mode: str = "repair_script") -> dict[str, int]:
    paths = result_paths(base_dir)
    raw_df = _read_csv(paths["raw"], RAW_COLUMNS)
    if raw_df.empty and paths["legacy"].exists():
        legacy_df = pd.read_csv(paths["legacy"])
        for c in RAW_COLUMNS:
            if c not in legacy_df.columns:
                legacy_df[c] = None
        raw_df = legacy_df[RAW_COLUMNS]

    clean_rows: list[dict[str, Any]] = []
    bad_rows: list[dict[str, Any]] = []
    unopened_rows = 0

    for _, row in raw_df.iterrows():
        clean, bad, is_unopened = _normalize_row(row.to_dict(), source_mode)
        if clean:
            clean_rows.append(clean)
        if bad:
            bad_rows.append(bad)
        if is_unopened:
            unopened_rows += 1

    dedup_clean = _dedup_clean_rows(clean_rows)

    clean_df = pd.DataFrame(dedup_clean, columns=RESULT_COLUMNS)
    bad_df = pd.DataFrame(bad_rows, columns=BAD_COLUMNS)

    clean_df.to_csv(paths["clean"], index=False, encoding="utf-8-sig")
    bad_df.to_csv(paths["bad"], index=False, encoding="utf-8-sig")
    clean_df.to_csv(paths["legacy"], index=False, encoding="utf-8-sig")

    bad_samples = bad_df.head(3)[["match_no", "bad_reason"]].to_dict("records") if not bad_df.empty else []
    logger.info(
        "result_cleaner rebuild finished | raw=%s clean=%s bad=%s unopened=%s | bad_samples=%s | raw_path=%s clean_path=%s bad_path=%s",
        len(raw_df),
        len(clean_df),
        len(bad_df),
        unopened_rows,
        bad_samples,
        paths["raw"],
        paths["clean"],
        paths["bad"],
    )

    return {
        "raw_rows": len(raw_df),
        "clean_rows": len(clean_df),
        "bad_rows": len(bad_df),
        "unopened_rows": unopened_rows,
    }


def append_raw_results(records: list[dict[str, Any]], data_source: str, base_dir: Path | None = None) -> dict[str, int]:
    paths = result_paths(base_dir)
    src = data_source if data_source in VALID_SOURCE else "repair_script"

    normalized_raw: list[dict[str, Any]] = []
    for r in records:
        out = {k: r.get(k) for k in RAW_COLUMNS}
        out["data_source"] = src
        out["updated_at"] = _normalize_text(out.get("updated_at")) or _now_iso()
        normalized_raw.append(out)

    new_df = pd.DataFrame(normalized_raw, columns=RAW_COLUMNS)
    old_df = _read_csv(paths["raw"], RAW_COLUMNS)

    if old_df.empty:
        merged = new_df.copy()
    elif new_df.empty:
        merged = old_df.copy()
    else:
        old_aligned = old_df.reindex(columns=RAW_COLUMNS)
        new_aligned = new_df.reindex(columns=RAW_COLUMNS)
        merged = pd.concat([old_aligned, new_aligned], ignore_index=True)

    merged.to_csv(paths["raw"], index=False, encoding="utf-8-sig")

    stats = rebuild_clean_results(base_dir, source_mode=src)
    stats["appended_raw"] = len(new_df)
    return stats


def load_clean_results(base_dir: Path | None = None) -> pd.DataFrame:
    paths = result_paths(base_dir)
    clean_df = _read_csv(paths["clean"], RESULT_COLUMNS)
    if not clean_df.empty:
        return clean_df

    raw_df = _read_csv(paths["raw"], RAW_COLUMNS)
    unopened_count = _count_unopened_rows(raw_df)
    if not raw_df.empty and unopened_count > 0:
        logger.info(
            "clean results empty but raw has unopened rows, rebuilding | raw=%s unopened=%s | raw_path=%s clean_path=%s",
            len(raw_df),
            unopened_count,
            paths["raw"],
            paths["clean"],
        )
        rebuild_clean_results(base_dir=base_dir, source_mode="repair_script")
        clean_df = _read_csv(paths["clean"], RESULT_COLUMNS)

    return clean_df
