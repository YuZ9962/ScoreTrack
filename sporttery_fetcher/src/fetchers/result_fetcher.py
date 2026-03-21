from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

import pandas as pd
from bs4 import BeautifulSoup

from config.settings import settings
from src.utils.http import HTTPClient
from src.utils.logger import get_logger

logger = get_logger("result_fetcher")


@dataclass
class ResultFetcher:
    client: HTTPClient

    def _parse_outcome(self, score: str) -> str | None:
        m = re.match(r"\s*(\d{1,2})\s*[-:：]\s*(\d{1,2})\s*", str(score or ""))
        if not m:
            return None
        home, away = int(m.group(1)), int(m.group(2))
        if home > away:
            return "主胜"
        if home == away:
            return "平"
        return "客胜"

    def _parse_row(self, cells: list[str], issue_date_hint: str | None = None) -> dict[str, str | None] | None:
        if len(cells) < 6:
            return None

        score = None
        for cell in cells:
            m = re.search(r"\d{1,2}\s*[-:：]\s*\d{1,2}", cell)
            if m:
                score = m.group(0).replace("：", "-").replace(":", "-")
                break
        if not score:
            return None

        match_no = next((c for c in cells if re.search(r"周[一二三四五六日天]\d{3}", c)), None)
        league = cells[2] if len(cells) > 2 else None

        teams = None
        for c in cells:
            if "vs" in c.lower() or "-" in c or "对" in c:
                if re.search(r"\d{1,2}\s*[-:：]\s*\d{1,2}", c):
                    continue
                teams = c
                break

        home_team, away_team = None, None
        if teams:
            parts = re.split(r"\s+vs\s+|\s+VS\s+|\s*[-—]\s*|\s*对\s*", teams)
            if len(parts) >= 2:
                home_team, away_team = parts[0].strip(), parts[1].strip()

        issue_date = issue_date_hint
        for c in cells:
            if re.match(r"\d{4}-\d{2}-\d{2}", c):
                issue_date = c[:10]
                break

        outcome = self._parse_outcome(score)

        return {
            "issue_date": issue_date,
            "match_no": match_no,
            "league": league,
            "home_team": home_team,
            "away_team": away_team,
            "kickoff_time": None,
            "full_time_score": score,
            "result_match": outcome,
            "result_handicap": None,
            "raw_result_text": " | ".join(cells),
            "result_generated_at": datetime.now(timezone.utc).isoformat(),
            "raw_id": None,
        }

    def _parse_html(self, html_text: str) -> list[dict[str, str | None]]:
        rows: list[dict[str, str | None]] = []
        soup = BeautifulSoup(html_text, "lxml")
        trs = soup.select("table tr")
        if not trs:
            trs = soup.select("tr")

        for tr in trs:
            tds = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            parsed = self._parse_row(tds)
            if parsed:
                rows.append(parsed)

        return rows

    def _fetch_with_playwright(self, url: str) -> str | None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            logger.warning("Playwright 不可用，跳过动态渲染回退")
            return None

        logger.info("赛果抓取 Playwright 回退 URL=%s", url)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=settings.playwright_headless)
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=settings.request_timeout * 1000)
                html = page.content()
                browser.close()
                return html
        except Exception as exc:
            logger.warning("Playwright 回退抓取失败: %s", type(exc).__name__)
            return None

    def fetch_results(self) -> tuple[list[dict[str, str | None]], int]:
        rows: list[dict[str, str | None]] = []
        requested_count = 0

        logger.info("开始抓取赛果")
        for url in settings.result_urls:
            requested_count += 1
            logger.info("请求赛果 URL=%s", url)
            html_text = None
            try:
                resp = self.client.request("GET", url)
                html_text = resp.text
            except Exception as exc:
                logger.warning("赛果请求失败 URL=%s err=%s", url, type(exc).__name__)

            if html_text:
                parsed_rows = self._parse_html(html_text)
                logger.info("赛果解析条数 URL=%s rows=%s", url, len(parsed_rows))
                rows.extend(parsed_rows)

            if not rows:
                pw_html = self._fetch_with_playwright(url)
                if pw_html:
                    parsed_rows = self._parse_html(pw_html)
                    logger.info("Playwright 赛果解析条数 URL=%s rows=%s", url, len(parsed_rows))
                    rows.extend(parsed_rows)

            if rows:
                break

        deduped: dict[tuple[str, str, str, str], dict[str, str | None]] = {}
        for r in rows:
            key = (
                str(r.get("issue_date") or ""),
                str(r.get("match_no") or ""),
                str(r.get("home_team") or ""),
                str(r.get("away_team") or ""),
            )
            deduped[key] = r

        result_rows = list(deduped.values())
        logger.info("赛果去重后条数=%s", len(result_rows))
        return result_rows, requested_count



def results_file(base_dir: Path | None = None) -> Path:
    root = base_dir or settings.base_dir
    path = root / "data" / "results" / "match_results.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path



def _count_matched_predictions(base_dir: Path, result_df: pd.DataFrame) -> int:
    pred_path = base_dir / "data" / "predictions" / "gemini_predictions.csv"
    if not pred_path.exists() or result_df.empty:
        return 0
    try:
        pred_df = pd.read_csv(pred_path)
    except Exception:
        return 0

    matched = 0
    for _, row in pred_df.iterrows():
        raw_id = str(row.get("raw_id", "") or "").strip()
        issue_date = str(row.get("issue_date", "") or "").strip()

        if raw_id and "raw_id" in result_df.columns:
            m = result_df[result_df["raw_id"].astype(str) == raw_id]
            if not m.empty:
                matched += 1
                continue

        m = result_df[
            (result_df["issue_date"].astype(str) == issue_date)
            & (result_df["match_no"].astype(str) == str(row.get("match_no", "")))
        ]
        if not m.empty:
            matched += 1
            continue

        m = result_df[
            (result_df["issue_date"].astype(str) == issue_date)
            & (result_df["home_team"].astype(str) == str(row.get("home_team", "")))
            & (result_df["away_team"].astype(str) == str(row.get("away_team", "")))
        ]
        if not m.empty:
            matched += 1

    return matched



def fetch_and_save_results(base_dir: Path | None = None) -> dict[str, object]:
    root = base_dir or settings.base_dir
    fetcher = ResultFetcher(client=HTTPClient())
    rows, requested_count = fetcher.fetch_results()

    path = results_file(root)
    columns = [
        "issue_date",
        "match_no",
        "league",
        "home_team",
        "away_team",
        "kickoff_time",
        "full_time_score",
        "result_match",
        "result_handicap",
        "raw_result_text",
        "result_generated_at",
        "raw_id",
    ]

    if not rows:
        logger.warning("赛果抓取结果为空，未写入数据")
        return {
            "ok": False,
            "path": str(path),
            "requested_urls": requested_count,
            "parsed_rows": 0,
            "written_rows": 0,
            "matched_predictions": 0,
        }

    new_df = pd.DataFrame(rows, columns=columns)
    if path.exists():
        old_df = pd.read_csv(path)
        merged = pd.concat([old_df, new_df], ignore_index=True)
    else:
        merged = new_df

    for col in columns:
        if col not in merged.columns:
            merged[col] = None

    merged = merged[columns]
    before = len(merged)
    merged = merged.drop_duplicates(subset=["issue_date", "raw_id", "match_no", "home_team", "away_team"], keep="last")
    written_rows = len(merged)
    merged.to_csv(path, index=False, encoding="utf-8-sig")

    matched_predictions = _count_matched_predictions(root, merged)

    logger.info(
        "赛果写入完成 path=%s parsed_rows=%s merged_before=%s written_rows=%s matched_predictions=%s",
        path,
        len(rows),
        before,
        written_rows,
        matched_predictions,
    )

    return {
        "ok": True,
        "path": str(path),
        "requested_urls": requested_count,
        "parsed_rows": len(rows),
        "written_rows": written_rows,
        "matched_predictions": matched_predictions,
    }
