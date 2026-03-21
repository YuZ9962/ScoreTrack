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
MATCH_NO_PATTERN = re.compile(r"周[一二三四五六日天]\d{3}")


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

    def _normalize_header_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", "", str(text or ""))
        normalized = normalized.replace("（", "(").replace("）", ")")
        return normalized

    def _resolve_column_indices(self, headers: list[str]) -> dict[str, int | None]:
        normalized_headers = [self._normalize_header_text(h) for h in headers]

        def find_index(candidates: list[str], contains: bool = True) -> int | None:
            for i, h in enumerate(normalized_headers):
                for c in candidates:
                    nc = self._normalize_header_text(c)
                    if contains and nc in h:
                        return i
                    if not contains and nc == h:
                        return i
            return None

        return {
            "score": find_index(["全场比分(90分钟)", "全场比分"]),
            "match_no": find_index(["赛事编号", "场次编号", "场次", "编号"]),
            "league": find_index(["联赛"]),
            "team_vs": find_index(["主队(让球)vs客队", "主队vs客队", "主队（让球）vs客队"]),
            "away_team": find_index(["客队"]),
            "result_match": find_index(["胜平负"]),
            "result_handicap": find_index(["让胜平负"]),
            "issue_date": find_index(["赛事日期", "日期", "比赛日期", "开奖日期"]),
            "status": find_index(["状态"]),
            "draw_result": find_index(["开奖结果", "开奖结果"]),
        }

    def _is_header_table(self, headers: list[str]) -> bool:
        normalized = [self._normalize_header_text(h) for h in headers]
        expected = [
            "赛事日期",
            "赛事编号",
            "联赛",
            "主队(让球)vs客队",
            "半场比分",
            "全场比分(90分钟)",
            "开奖结果",
        ]
        hits = 0
        for e in expected:
            ne = self._normalize_header_text(e)
            if any(ne in h for h in normalized):
                hits += 1
        return hits >= 4

    def _is_data_table(self, table: Any) -> bool:
        first_tr = table.select_one("tr")
        if not first_tr:
            return False
        first_cells = [c.get_text(" ", strip=True) for c in first_tr.find_all(["td", "th"])]
        if len(first_cells) < 3:
            return False
        first_col = str(first_cells[0] or "").strip()
        second_col = str(first_cells[1] or "").strip()
        third_col = str(first_cells[2] or "").strip()
        return bool(re.match(r"\d{4}-\d{2}-\d{2}", first_col) and MATCH_NO_PATTERN.search(second_col) and third_col)

    def _row_value_by_index(self, cells: list[str], idx: int | None) -> str | None:
        if idx is None or idx < 0 or idx >= len(cells):
            return None
        value = str(cells[idx] or "").strip()
        return value or None

    def _parse_team_vs(self, team_vs_text: str | None) -> tuple[str | None, str | None, str | None]:
        if not team_vs_text:
            return None, None, None
        text = str(team_vs_text).strip()
        m = re.match(r"^\s*(.+?)\s*(?:\(([+-]?\d+)\))?\s*(?:VS|vs|Vs|vS)\s*(.+?)\s*$", text)
        if m:
            return m.group(1).strip(), m.group(3).strip(), m.group(2)
        parts = re.split(r"\s*(?:VS|vs|Vs|vS)\s*", text)
        if len(parts) >= 2:
            home_raw = parts[0].strip()
            away = parts[1].strip()
            hm = re.match(r"^(.*?)\s*\(([+-]?\d+)\)\s*$", home_raw)
            if hm:
                return hm.group(1).strip(), away, hm.group(2)
            return home_raw, away, None
        return None, None, None

    def _parse_handicap_result(self, score: str | None, handicap: str | None) -> str | None:
        if not score or not handicap:
            return None
        m = re.match(r"^\s*([0-9]+)-([0-9]+)\s*$", score)
        if not m:
            return None
        try:
            home = int(m.group(1))
            away = int(m.group(2))
            hcap = int(str(handicap))
        except Exception:
            return None
        adjusted_home = home + hcap
        if adjusted_home > away:
            return "让胜"
        if adjusted_home == away:
            return "让平"
        return "让负"

    def _parse_table_rows(
        self, table: Any, score_col_idx: int, col_map: dict[str, int | None], issue_date_hint: str | None = None
    ) -> list[dict[str, str | None]]:
        rows: list[dict[str, str | None]] = []
        debug_count = 0
        trs = table.select("tr")
        for tr in trs:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if not cells:
                continue
            if score_col_idx >= len(cells):
                continue

            issue_date = self._row_value_by_index(cells, col_map.get("issue_date")) or issue_date_hint
            match_no = self._row_value_by_index(cells, col_map.get("match_no"))
            league = self._row_value_by_index(cells, col_map.get("league"))
            team_vs = self._row_value_by_index(cells, col_map.get("team_vs"))
            status_text = self._row_value_by_index(cells, col_map.get("status")) or ""
            draw_text = self._row_value_by_index(cells, col_map.get("draw_result")) or ""
            if not issue_date and not match_no and tr.find_all("th"):
                continue
            if not issue_date and not match_no and not league and not team_vs:
                continue

            score_candidate = self._row_value_by_index(cells, score_col_idx)
            score = self._normalize_score(score_candidate)
            if score and score_candidate and self._looks_like_date_fragment(score, score_candidate):
                logger.warning("识别到日期型比分候选，已忽略 candidate=%s score=%s", score_candidate, score)
                score = None
            home_team, away_team, handicap = self._parse_team_vs(team_vs)
            if issue_date and re.match(r"\d{4}-\d{2}-\d{2}", issue_date):
                issue_date = issue_date[:10]

            pending = (not score) or ("待开奖" in status_text) or (not draw_text)
            result_match = "未开奖" if pending else self._parse_outcome(score or "")
            result_handicap = "未开奖" if pending else (self._parse_handicap_result(score, handicap) or None)

            row = {
                "issue_date": issue_date,
                "match_no": match_no,
                "league": league,
                "home_team": home_team,
                "away_team": away_team,
                "handicap": handicap,
                "kickoff_time": None,
                "full_time_score": score,
                "result_match": result_match,
                "result_handicap": result_handicap,
                "raw_result_text": " | ".join(cells),
                "result_generated_at": datetime.now(timezone.utc).isoformat(),
                "raw_id": None,
            }
            rows.append(row)
            if debug_count < 3:
                logger.info("赛果解析样本[%s]=%s", debug_count + 1, row)
                debug_count += 1

        return rows

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

    def _parse_html(self, html_text: str, source_label: str = "static") -> tuple[list[dict[str, str | None]], int]:
        rows: list[dict[str, str | None]] = []
        soup = BeautifulSoup(html_text, "lxml")
        tables = soup.select("table")
        candidate_count = len(tables)
        logger.info("HTML 解析候选 table=%s source=%s", candidate_count, source_label)

        header_table_idx: int | None = None
        header_map: dict[str, int | None] | None = None

        for idx, table in enumerate(tables, start=1):
            header_cells = table.select("tr th")
            headers = [h.get_text(" ", strip=True) for h in header_cells]
            if not headers:
                first_tr = table.select_one("tr")
                if first_tr:
                    headers = [c.get_text(" ", strip=True) for c in first_tr.find_all(["th", "td"])]

            if not headers:
                continue

            logger.info("赛果表格[%s]表头=%s", idx, headers)
            if self._is_header_table(headers):
                header_table_idx = idx
                header_map = self._resolve_column_indices(headers)
                logger.info("识别到赛果表头表 index=%s", idx)
                logger.info("赛果表头列映射=%s", header_map)
                logger.info("赛果表格[%s] “全场比分（90分钟）”列索引=%s", idx, header_map.get("score"))
                break

        if header_table_idx is None or header_map is None or header_map.get("score") is None:
            if tables:
                logger.warning("未找到列：全场比分（90分钟）")
                self._save_snapshot(html_text, prefix=f"result_missing_score_col_{source_label}")
            return rows, candidate_count

        for idx, table in enumerate(tables, start=1):
            if idx <= header_table_idx:
                continue
            if not self._is_data_table(table):
                continue
            logger.info("识别到赛果数据表 index=%s", idx)
            table_rows = self._parse_table_rows(table, score_col_idx=header_map["score"], col_map=header_map)
            if table_rows:
                rows.extend(table_rows)
                break

        if not rows:
            logger.warning("未解析到赛果数据行 source=%s", source_label)

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

    def _fetch_with_playwright_html(self, page_url: str) -> str | None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            logger.warning("Playwright 不可用，无法进行动态渲染")
            return None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.playwright_headless)
            context = browser.new_context(user_agent=settings.user_agent)
            page = context.new_page()
            try:
                page.goto(page_url, wait_until="networkidle", timeout=settings.request_timeout * 1000)
                html = page.content()
                logger.info("Playwright 页面源码长度=%s 关键字命中=%s", len(html), self._keyword_hits(html))
                self._save_snapshot(html, prefix="result_playwright")
                return html
            except Exception as exc:
                logger.warning("Playwright 渲染失败 URL=%s err=%s", page_url, type(exc).__name__)
                return None
            finally:
                browser.close()

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
                parsed_rows, candidate_count = self._parse_html(html_text, source_label="static")
                logger.info("静态 HTML 候选节点数=%s 解析条数=%s", candidate_count, len(parsed_rows))
                rows.extend(parsed_rows)

            # Playwright 回退：渲染后依旧按表头列定位解析，不做整行正则猜测
            if not rows:
                pw_html = self._fetch_with_playwright_html(url)
                if pw_html:
                    pw_rows, pw_candidate_count = self._parse_html(pw_html, source_label="playwright")
                    logger.info("Playwright HTML 候选节点数=%s 解析条数=%s", pw_candidate_count, len(pw_rows))
                    rows.extend(pw_rows)

            # 接口探测兜底
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
