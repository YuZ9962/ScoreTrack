from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import re
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

from config.settings import settings
from src.utils.http import HTTPClient
from src.utils.logger import get_logger

logger = get_logger("result_fetcher")

KEYWORDS = ["周四", "比分", "开奖", "主队", "客队"]
SCORE_PATTERN = re.compile(r"(?<!\d)([0-9])\s*[-:：]\s*([0-9])(?!\d)")
DATE_PATTERN = re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")


@dataclass
class ResultFetcher:
    client: HTTPClient
    _debug_sample_count: int = field(default=0, init=False, repr=False)

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

    def _normalize_score(self, score_text: str | None) -> str | None:
        if not score_text:
            return None
        m = SCORE_PATTERN.search(str(score_text))
        if not m:
            return None
        score = f"{m.group(1)}-{m.group(2)}"
        if score in {"26-03", "03-20"}:
            logger.warning("识别到疑似日期片段比分，已丢弃 score=%s source=%s", score, score_text)
            return None
        return score

    def _looks_like_date_fragment(self, score: str, source_text: str) -> bool:
        if DATE_PATTERN.search(source_text):
            parts = score.split("-")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                left, right = int(parts[0]), int(parts[1])
                if (left > 12 or right > 12) and (left >= 20 or right >= 20):
                    return True
        return False

    def _extract_score_from_cells(self, cells: list[str]) -> tuple[str | None, str | None]:
        clean_cells = [str(c or "").strip() for c in cells if str(c or "").strip()]
        if not clean_cells:
            return None, None

        explicit_candidates: list[str] = []
        compact_candidates: list[str] = []
        fallback_candidates: list[str] = []

        for cell in clean_cells:
            lower = cell.lower()
            if any(k in cell for k in ["比分", "赛果", "开奖"]) and SCORE_PATTERN.search(cell):
                explicit_candidates.append(cell)
                continue
            if SCORE_PATTERN.fullmatch(cell):
                compact_candidates.append(cell)
                continue
            if SCORE_PATTERN.search(cell) and not DATE_PATTERN.search(cell):
                fallback_candidates.append(cell)

        for candidate in [*explicit_candidates, *compact_candidates, *fallback_candidates]:
            score = self._normalize_score(candidate)
            if not score:
                continue
            if self._looks_like_date_fragment(score, candidate):
                logger.warning("识别到日期型比分候选，已忽略 candidate=%s score=%s", candidate, score)
                continue
            return score, candidate

        return None, None

    def _log_score_debug(self, cells: list[str], score_candidate: str | None, score: str | None) -> None:
        if self._debug_sample_count >= 3:
            return
        raw_row = " | ".join(cells)
        logger.info(
            "赛果调试样本[%s] raw_row=%s score_candidate=%s parsed_full_time_score=%s",
            self._debug_sample_count + 1,
            raw_row,
            score_candidate,
            score,
        )
        self._debug_sample_count += 1

    def _parse_row(self, cells: list[str], issue_date_hint: str | None = None) -> dict[str, str | None] | None:
        if len(cells) < 4:
            return None

        score, score_candidate = self._extract_score_from_cells(cells)
        self._log_score_debug(cells, score_candidate, score)
        if not score:
            return None

        match_no = next((c for c in cells if re.search(r"周[一二三四五六日天]\d{3}", c)), None)
        league = next((c for c in cells if len(c) <= 16 and any(x in c for x in ["联赛", "杯", "甲", "超"])) , None)

        teams = None
        for c in cells:
            if re.search(r"\bvs\b|\bVS\b|对|[-—]", c) and not re.search(r"\d{1,2}\s*[-:：]\s*\d{1,2}", c):
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

    def _keyword_hits(self, text: str) -> dict[str, bool]:
        return {k: (k in text) for k in KEYWORDS}

    def _save_snapshot(self, html_text: str, prefix: str = "result") -> Path:
        snap_dir = settings.snapshots_dir / "results"
        snap_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = snap_dir / f"{prefix}_{ts}.html"
        path.write_text(html_text, encoding="utf-8")
        logger.info("赛果页面快照已保存: %s", path)
        return path

    def _parse_html(self, html_text: str) -> tuple[list[dict[str, str | None]], int]:
        rows: list[dict[str, str | None]] = []
        soup = BeautifulSoup(html_text, "lxml")

        candidate_trs = soup.select("table tr")
        candidate_count = len(candidate_trs)
        logger.info("HTML 解析候选节点 table tr=%s", candidate_count)

        if not candidate_trs:
            candidate_trs = soup.select("tr")
            candidate_count = len(candidate_trs)
            logger.info("HTML 解析候选节点 tr=%s", candidate_count)

        for tr in candidate_trs:
            tds = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            parsed = self._parse_row(tds)
            if parsed:
                rows.append(parsed)

        # fallback: 非表格结构节点
        if not rows:
            candidates = soup.find_all(text=re.compile(r"周[一二三四五六日天]\d{3}"))
            logger.info("HTML 非表格候选文本节点=%s", len(candidates))
            for node in candidates:
                block = node.parent.get_text(" ", strip=True) if node.parent else str(node)
                cells = re.split(r"\s{2,}|\|", block)
                parsed = self._parse_row([c.strip() for c in cells if c.strip()])
                if parsed:
                    rows.append(parsed)

        return rows, candidate_count

    def _build_row_from_json_item(self, item: dict[str, Any]) -> dict[str, str | None] | None:
        text_dump = json.dumps(item, ensure_ascii=False)
        score = self._extract_score_from_json_item(item)
        if not score:
            return None
        match_no = None
        for key in ["matchNo", "match_no", "weekdayNo", "matchNumStr"]:
            v = item.get(key)
            if v:
                match_no = str(v)
                break
        if not match_no:
            m = re.search(r"周[一二三四五六日天]\d{3}", text_dump)
            match_no = m.group(0) if m else None

        home_team = next((str(item.get(k)) for k in ["homeTeamName", "homeName", "home_team"] if item.get(k)), None)
        away_team = next((str(item.get(k)) for k in ["awayTeamName", "awayName", "away_team"] if item.get(k)), None)
        league = next((str(item.get(k)) for k in ["leagueName", "league", "matchName"] if item.get(k)), None)
        issue_date = next((str(item.get(k))[:10] for k in ["issueDate", "matchDate", "saleDate"] if item.get(k)), None)

        return {
            "issue_date": issue_date,
            "match_no": match_no,
            "league": league,
            "home_team": home_team,
            "away_team": away_team,
            "kickoff_time": None,
            "full_time_score": score,
            "result_match": self._parse_outcome(score),
            "result_handicap": None,
            "raw_result_text": text_dump[:800],
            "result_generated_at": datetime.now(timezone.utc).isoformat(),
            "raw_id": str(item.get("id") or item.get("matchId") or "") or None,
        }

    def _extract_score_from_json_item(self, item: dict[str, Any]) -> str | None:
        score_keys = [
            "score",
            "fullScore",
            "full_time_score",
            "resultScore",
            "matchScore",
            "spfResult",
            "bfResult",
        ]
        for key in score_keys:
            value = item.get(key)
            if value is None:
                continue
            source_text = str(value)
            score = self._normalize_score(source_text)
            if not score:
                continue
            if self._looks_like_date_fragment(score, source_text):
                logger.warning("JSON 中识别到日期型比分候选，已忽略 key=%s value=%s", key, source_text)
                continue
            return score

        # 仅在“键名语义明确”的字段中做候选匹配，避免对整段 JSON 文本盲猜。
        for key, value in item.items():
            if not isinstance(value, str):
                continue
            key_lower = str(key).lower()
            if not any(flag in key_lower for flag in ["score", "result", "bf", "bifen"]):
                continue
            score = self._normalize_score(value)
            if not score:
                continue
            if self._looks_like_date_fragment(score, value):
                logger.warning("JSON 模糊字段识别到日期型比分候选，已忽略 key=%s value=%s", key, value)
                continue
            return score

        return None

    def _extract_rows_from_json(self, data: Any) -> list[dict[str, str | None]]:
        rows: list[dict[str, str | None]] = []

        def walk(obj: Any):
            if isinstance(obj, dict):
                row = self._build_row_from_json_item(obj)
                if row:
                    rows.append(row)
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for x in obj:
                    walk(x)

        walk(data)
        return rows

    def _detect_api_rows(self, page_url: str) -> tuple[list[dict[str, str | None]], int]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            logger.warning("Playwright 不可用，无法进行 XHR/JSON 探测")
            return [], 0

        candidates: list[dict[str, Any]] = []
        rows: list[dict[str, str | None]] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.playwright_headless)
            context = browser.new_context(user_agent=settings.user_agent)
            page = context.new_page()

            def on_response(resp):
                req = resp.request
                rtype = req.resource_type
                ctype = resp.headers.get("content-type", "").lower()
                if rtype not in {"xhr", "fetch"} and "json" not in ctype:
                    return
                url = resp.url
                if "sporttery" not in url:
                    return
                try:
                    body = resp.text()
                except Exception:
                    return

                item = {
                    "url": url,
                    "method": req.method,
                    "rtype": rtype,
                    "ctype": ctype,
                    "body_len": len(body),
                }
                candidates.append(item)

                try:
                    data = json.loads(body)
                except Exception:
                    return
                api_rows = self._extract_rows_from_json(data)
                if api_rows:
                    logger.info("接口命中赛果数据 URL=%s rows=%s", url, len(api_rows))
                    rows.extend(api_rows)

            page.on("response", on_response)
            page.goto(page_url, wait_until="networkidle", timeout=settings.request_timeout * 1000)
            html = page.content()
            logger.info("Playwright 页面源码长度=%s 关键字命中=%s", len(html), self._keyword_hits(html))
            self._save_snapshot(html, prefix="result_playwright")
            browser.close()

        logger.info("XHR/JSON 候选请求数=%s", len(candidates))
        return rows, len(candidates)

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
                logger.info("静态页面源码长度=%s 关键字命中=%s", len(html_text), self._keyword_hits(html_text))
            except Exception as exc:
                logger.warning("赛果请求失败 URL=%s err=%s", url, type(exc).__name__)

            if html_text:
                parsed_rows, candidate_count = self._parse_html(html_text)
                logger.info("静态 HTML 候选节点数=%s 解析条数=%s", candidate_count, len(parsed_rows))
                rows.extend(parsed_rows)

            # 优先接口探测
            if not rows:
                api_rows, api_candidate_count = self._detect_api_rows(url)
                logger.info("接口探测候选数=%s 解析条数=%s", api_candidate_count, len(api_rows))
                rows.extend(api_rows)

            if not rows and html_text:
                self._save_snapshot(html_text, prefix="result_static")

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
