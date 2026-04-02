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
from src.fetchers.zqsgkj_fetcher import fetch_zqsgkj_matches
from src.services.result_cleaner import append_raw_results
from src.domain.match_identity import build_match_key
from src.domain.match_time import derive_match_date, infer_issue_date_from_kickoff, kickoff_belongs_to_issue_date

logger = get_logger("result_fetcher")

KEYWORDS = ["周四", "比分", "开奖", "主队", "客队"]
SCORE_PATTERN = re.compile(r"(?<!\d)([0-9])\s*[-:：]\s*([0-9])(?!\d)")
DATE_PATTERN = re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")
MATCH_NO_PATTERN = re.compile(r"周[一二三四五六日天]\d{3}")


@dataclass
class ResultFetcher:
    client: HTTPClient
    _debug_sample_count: int = field(default=0, init=False, repr=False)

    def _normalize_issue_date(self, issue_date: str | None) -> str:
        text = str(issue_date or "").strip()
        if not text:
            return ""
        text = text.replace("/", "-").replace(".", "-")
        m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        return m.group(1) if m else text[:10]

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
            "draw_result": find_index(["开奖结果"]),
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
        return sum(1 for e in expected if any(self._normalize_header_text(e) in h for h in normalized)) >= 4

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

    def _filter_rows_by_issue_date(self, rows: list[dict[str, str | None]], issue_date: str | None) -> list[dict[str, str | None]]:
        target = self._normalize_issue_date(issue_date)
        if not target:
            return rows
        out: list[dict[str, str | None]] = []
        for r in rows:
            kickoff = r.get("kickoff_time")
            if kickoff and kickoff_belongs_to_issue_date(kickoff, target):
                out.append(r)
                continue

            row_issue = self._normalize_issue_date(r.get("issue_date"))
            inferred_issue = infer_issue_date_from_kickoff(kickoff) if kickoff else None
            if row_issue == target or inferred_issue == target:
                out.append(r)
                continue

            # 历史赛果常缺少 kickoff，避免误删：无明确归属证据时保留
            if not kickoff and not row_issue:
                out.append(r)
        return out

    def _parse_table_rows(
        self,
        table: Any,
        score_col_idx: int,
        col_map: dict[str, int | None],
        issue_date_hint: str | None = None,
    ) -> list[dict[str, str | None]]:
        rows: list[dict[str, str | None]] = []
        trs = table.select("tr")
        for tr in trs:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if not cells or score_col_idx >= len(cells):
                continue

            issue_date = self._row_value_by_index(cells, col_map.get("issue_date")) or issue_date_hint
            issue_date = self._normalize_issue_date(issue_date)

            match_no = self._row_value_by_index(cells, col_map.get("match_no"))
            league = self._row_value_by_index(cells, col_map.get("league"))
            team_vs = self._row_value_by_index(cells, col_map.get("team_vs"))
            status_text = self._row_value_by_index(cells, col_map.get("status")) or ""
            draw_text = self._row_value_by_index(cells, col_map.get("draw_result")) or ""
            if not issue_date and not match_no and not league and not team_vs:
                continue

            score_candidate = self._row_value_by_index(cells, score_col_idx)
            score = self._normalize_score(score_candidate)
            if score and score_candidate and self._looks_like_date_fragment(score, score_candidate):
                score = None

            home_team, away_team, handicap = self._parse_team_vs(team_vs)
            pending = (not score) or ("待开奖" in status_text) or (not draw_text)
            result_match = "未开奖" if pending else self._parse_outcome(score or "")
            result_handicap = "未开奖" if pending else (self._parse_handicap_result(score, handicap) or None)

            row_match_date = self._normalize_issue_date(self._row_value_by_index(cells, col_map.get("issue_date")))
            row_data = {
                "issue_date": issue_date,
                "match_date": row_match_date or None,
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
            row_data["match_key"] = build_match_key(row_data)
            rows.append(row_data)

        return rows

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

    def _parse_html(
        self,
        html_text: str,
        source_label: str = "static",
        issue_date_hint: str | None = None,
    ) -> tuple[list[dict[str, str | None]], int]:
        rows: list[dict[str, str | None]] = []
        soup = BeautifulSoup(html_text, "lxml")
        tables = soup.select("table")
        candidate_count = len(tables)

        header_table_idx: int | None = None
        header_map: dict[str, int | None] | None = None

        for idx, table in enumerate(tables, start=1):
            header_cells = table.select("tr th")
            headers = [h.get_text(" ", strip=True) for h in header_cells]
            if not headers:
                first_tr = table.select_one("tr")
                if first_tr:
                    headers = [c.get_text(" ", strip=True) for c in first_tr.find_all(["th", "td"])]
            if headers and self._is_header_table(headers):
                header_table_idx = idx
                header_map = self._resolve_column_indices(headers)
                break

        if header_table_idx is None or header_map is None or header_map.get("score") is None:
            return rows, candidate_count

        for idx, table in enumerate(tables, start=1):
            if idx <= header_table_idx:
                continue
            if not self._is_data_table(table):
                continue
            table_rows = self._parse_table_rows(table, score_col_idx=header_map["score"], col_map=header_map, issue_date_hint=issue_date_hint)
            if table_rows:
                rows.extend(table_rows)

        rows = self._filter_rows_by_issue_date(rows, issue_date_hint)
        logger.info("HTML 解析完成 source=%s issue_date=%s rows=%s", source_label, issue_date_hint, len(rows))
        return rows, candidate_count

    def _extract_score_from_json_item(self, item: dict[str, Any]) -> str | None:
        score_keys = ["score", "fullScore", "full_time_score", "resultScore", "matchScore", "bfResult"]
        for key in score_keys:
            value = item.get(key)
            if value is None:
                continue
            score = self._normalize_score(str(value))
            if score:
                return score
        return None

    def _build_row_from_json_item(self, item: dict[str, Any]) -> dict[str, str | None] | None:
        score = self._extract_score_from_json_item(item)
        if not score:
            return None
        text_dump = json.dumps(item, ensure_ascii=False)

        kickoff_time = next((str(item.get(k)) for k in ["kickoffTime", "matchTime", "matchDateTime", "matchDate"] if item.get(k)), None)
        source_issue_date = next((str(item.get(k))[:10] for k in ["issueDate", "saleDate", "date"] if item.get(k)), None)
        issue_date = self._normalize_issue_date(source_issue_date or infer_issue_date_from_kickoff(kickoff_time))
        match_no = next((str(item.get(k)) for k in ["matchNo", "match_no", "weekdayNo", "matchNumStr"] if item.get(k)), None)
        home_team = next((str(item.get(k)) for k in ["homeTeamName", "homeName", "home_team"] if item.get(k)), None)
        away_team = next((str(item.get(k)) for k in ["awayTeamName", "awayName", "away_team"] if item.get(k)), None)
        league = next((str(item.get(k)) for k in ["leagueName", "league", "matchName"] if item.get(k)), None)
        handicap = next((str(item.get(k)) for k in ["handicap", "rangqiu", "rq"] if item.get(k) is not None), None)
        result_handicap = next((str(item.get(k)) for k in ["rqResult", "resultHandicap", "result_handicap"] if item.get(k)), None)

        row_data = {
            "issue_date": issue_date,
            "match_no": match_no,
            "league": league,
            "home_team": home_team,
            "away_team": away_team,
            "handicap": handicap,
            "kickoff_time": kickoff_time,
            "match_date": derive_match_date(kickoff_time),
            "full_time_score": score,
            "result_match": self._parse_outcome(score),
            "result_handicap": result_handicap,
            "raw_result_text": text_dump[:1200],
            "result_generated_at": datetime.now(timezone.utc).isoformat(),
            "raw_id": str(item.get("id") or item.get("matchId") or "") or None,
        }
        row_data["match_key"] = build_match_key(row_data)
        return row_data

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

    def _select_issue_date(self, page: Any, issue_date: str) -> bool:
        target = self._normalize_issue_date(issue_date)
        if not target:
            return False
        changed = False
        try:
            changed = bool(
                page.evaluate(
                    """
                    (target) => {
                      const compact = target.replace(/-/g, '');
                      const dot = target.replace(/-/g, '.');
                      const slash = target.replace(/-/g, '/');
                      let hit = false;

                      const selects = Array.from(document.querySelectorAll('select'));
                      for (const sel of selects) {
                        const opts = Array.from(sel.options || []);
                        const found = opts.find(o => {
                          const v = String(o.value || '');
                          const t = String(o.textContent || '').trim();
                          return v.includes(target) || v.includes(compact) || t.includes(target) || t.includes(dot) || t.includes(slash) || t.includes(compact);
                        });
                        if (found) {
                          sel.value = found.value;
                          sel.dispatchEvent(new Event('input', { bubbles: true }));
                          sel.dispatchEvent(new Event('change', { bubbles: true }));
                          hit = true;
                        }
                      }

                      if (!hit) {
                        const candidates = Array.from(document.querySelectorAll('a,button,li,span,td,option'));
                        for (const el of candidates) {
                          const t = String(el.textContent || '').replace(/\\s+/g, '');
                          if (!t) continue;
                          if (t.includes(target) || t.includes(dot) || t.includes(slash) || t.includes(compact)) {
                            el.click();
                            hit = true;
                            break;
                          }
                        }
                      }

                      return hit;
                    }
                    """,
                    target,
                )
            )
        except Exception:
            changed = False

        try:
            page.wait_for_timeout(1200)
            page.wait_for_load_state("networkidle", timeout=max(8000, settings.request_timeout * 1000))
        except Exception:
            pass
        return changed

    def _fetch_with_playwright_html_for_date(self, page_url: str, issue_date: str) -> tuple[str | None, bool]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            logger.warning("Playwright 不可用，无法进行按日期渲染")
            return None, False

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.playwright_headless)
            context = browser.new_context(user_agent=settings.user_agent)
            page = context.new_page()
            changed = False
            try:
                page.goto(page_url, wait_until="networkidle", timeout=settings.request_timeout * 1000)
                changed = self._select_issue_date(page, issue_date)
                html = page.content()
                return html, changed
            except Exception as exc:
                logger.warning("Playwright 按日期渲染失败 URL=%s issue_date=%s err=%s", page_url, issue_date, type(exc).__name__)
                return None, False
            finally:
                browser.close()

    def _detect_api_rows_for_date(self, page_url: str, issue_date: str) -> tuple[list[dict[str, str | None]], int]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            logger.warning("Playwright 不可用，无法进行 XHR/JSON 探测")
            return [], 0

        candidates = 0
        rows: list[dict[str, str | None]] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.playwright_headless)
            context = browser.new_context(user_agent=settings.user_agent)
            page = context.new_page()

            def on_response(resp):
                nonlocal candidates
                req = resp.request
                rtype = req.resource_type
                ctype = resp.headers.get("content-type", "").lower()
                if rtype not in {"xhr", "fetch"} and "json" not in ctype:
                    return
                if "sporttery" not in resp.url:
                    return
                candidates += 1
                try:
                    body = resp.text()
                    data = json.loads(body)
                except Exception:
                    return
                rows.extend(self._extract_rows_from_json(data))

            page.on("response", on_response)
            try:
                page.goto(page_url, wait_until="networkidle", timeout=settings.request_timeout * 1000)
                self._select_issue_date(page, issue_date)
                page.wait_for_timeout(1500)
            except Exception:
                pass
            browser.close()

        rows = self._filter_rows_by_issue_date(rows, issue_date)
        logger.info("接口探测完成 issue_date=%s candidates=%s rows=%s", issue_date, candidates, len(rows))
        return rows, candidates

    def _convert_zqsgkj_row(self, row: dict[str, str]) -> dict[str, str | None]:
        score = str(row.get("full_score") or "").strip()
        handicap = str(row.get("handicap") or "").strip() or None
        result_row: dict[str, str | None] = {
            "issue_date": str(row.get("issue_date") or ""),
            "match_no": str(row.get("match_no") or ""),
            "league": str(row.get("league") or ""),
            "home_team": str(row.get("home_team") or ""),
            "away_team": str(row.get("away_team") or ""),
            "handicap": handicap,
            "kickoff_time": row.get("kickoff_time"),
            "match_date": str(row.get("match_date") or "") or None,
            "full_time_score": score or None,
            "result_match": self._parse_outcome(score) if score else "未开奖",
            "result_handicap": self._parse_handicap_result(score, handicap) if score and handicap else "未开奖",
            "raw_result_text": json.dumps(row, ensure_ascii=False),
            "result_generated_at": datetime.now(timezone.utc).isoformat(),
            "raw_id": None,
        }
        result_row["match_key"] = build_match_key(result_row)
        return result_row

    def fetch_results_by_date(self, issue_date: str) -> tuple[list[dict[str, str | None]], int, str]:
        target_date = self._normalize_issue_date(issue_date)
        logger.info("开始抓取赛果 issue_date=%s", target_date)

        requested_count = 0
        rows: list[dict[str, str | None]] = []
        mode = "none"

        try:
            zqsgkj_rows = fetch_zqsgkj_matches(target_date)
            if zqsgkj_rows:
                rows = [self._convert_zqsgkj_row(r) for r in zqsgkj_rows]
                mode = "zqsgkj_playwright"
                logger.info("赛果抓取方式=%s issue_date=%s parsed=%s", mode, target_date, len(rows))
                deduped = {
                    (
                        str(r.get("issue_date") or ""),
                        str(r.get("match_no") or ""),
                        str(r.get("home_team") or ""),
                        str(r.get("away_team") or ""),
                    ): r
                    for r in rows
                }
                out = list(deduped.values())
                logger.info("按日期赛果抓取完成 issue_date=%s mode=%s parsed_rows=%s dedup_rows=%s", target_date, mode, len(rows), len(out))
                return out, 1, mode
        except Exception as exc:
            logger.warning("zqsgkj 按日期抓取失败 issue_date=%s err=%s，回退旧逻辑", target_date, type(exc).__name__)

        for url in settings.result_urls:
            requested_count += 1

            api_rows, api_candidates = self._detect_api_rows_for_date(url, target_date)
            logger.info("赛果抓取方式=api issue_date=%s url=%s candidates=%s parsed=%s", target_date, url, api_candidates, len(api_rows))
            if api_rows:
                rows = api_rows
                mode = "api"
                break

            html, changed = self._fetch_with_playwright_html_for_date(url, target_date)
            if html:
                parsed_rows, candidate_count = self._parse_html(html, source_label="playwright_date", issue_date_hint=target_date)
                logger.info(
                    "赛果抓取方式=playwright issue_date=%s url=%s date_changed=%s tables=%s parsed=%s",
                    target_date,
                    url,
                    changed,
                    candidate_count,
                    len(parsed_rows),
                )
                if parsed_rows:
                    rows = parsed_rows
                    mode = "playwright"
                    break

            # 最后兜底：静态页 + date 参数尝试
            try:
                resp = self.client.request("GET", url, params={"date": target_date})
                static_rows, candidate_count = self._parse_html(resp.text, source_label="static_date", issue_date_hint=target_date)
                logger.info("赛果抓取方式=static issue_date=%s url=%s tables=%s parsed=%s", target_date, url, candidate_count, len(static_rows))
                if static_rows:
                    rows = static_rows
                    mode = "static"
                    break
            except Exception as exc:
                logger.warning("静态按日期抓取失败 issue_date=%s url=%s err=%s", target_date, url, type(exc).__name__)

        deduped: dict[tuple[str, str, str, str], dict[str, str | None]] = {}
        for r in rows:
            key = (
                str(r.get("issue_date") or ""),
                str(r.get("match_no") or ""),
                str(r.get("home_team") or ""),
                str(r.get("away_team") or ""),
            )
            deduped[key] = r

        out = list(deduped.values())
        logger.info("按日期赛果抓取完成 issue_date=%s mode=%s parsed_rows=%s dedup_rows=%s", target_date, mode, len(rows), len(out))
        return out, requested_count, mode


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
        issue_date = str(row.get("issue_date", "") or "").strip()
        raw_id = str(row.get("raw_id", "") or "").strip()
        match_no = str(row.get("match_no", "") or "").strip()
        home_team = str(row.get("home_team", "") or "").strip()
        away_team = str(row.get("away_team", "") or "").strip()
        pred_mk = str(row.get("match_key", "") or "").strip()

        # 优先通过 match_key 匹配
        if pred_mk and "match_key" in result_df.columns:
            m = result_df[result_df["match_key"].astype(str) == pred_mk]
            if not m.empty:
                matched += 1
                continue

        # 降级：issue_date + raw_id
        if raw_id and "raw_id" in result_df.columns:
            m = result_df[
                (result_df["issue_date"].astype(str) == issue_date)
                & (result_df["raw_id"].astype(str) == raw_id)
            ]
            if not m.empty:
                matched += 1
                continue

        # 降级：issue_date + match_no + home + away
        m = result_df[
            (result_df["issue_date"].astype(str) == issue_date)
            & (result_df["match_no"].astype(str) == match_no)
            & (result_df["home_team"].astype(str) == home_team)
            & (result_df["away_team"].astype(str) == away_team)
        ]
        if not m.empty:
            matched += 1

    return matched


def fetch_and_save_results(base_dir: Path | None = None, issue_date: str | None = None) -> dict[str, object]:
    root = base_dir or settings.base_dir
    target_date = issue_date or datetime.now().date().isoformat()

    fetcher = ResultFetcher(client=HTTPClient())
    rows, requested_count, mode = fetcher.fetch_results_by_date(target_date)

    path = results_file(root)
    columns = [
        "issue_date",
        "match_no",
        "league",
        "home_team",
        "away_team",
        "handicap",
        "kickoff_time",
        "full_time_score",
        "result_match",
        "result_handicap",
        "raw_result_text",
        "result_generated_at",
        "raw_id",
        "data_source",
        "updated_at",
    ]

    if not rows:
        logger.warning("赛果抓取结果为空 issue_date=%s mode=%s", target_date, mode)
        return {
            "ok": False,
            "path": str(path),
            "issue_date": target_date,
            "mode": mode,
            "requested_urls": requested_count,
            "parsed_rows": 0,
            "written_rows": 0,
            "matched_predictions": 0,
        }

    raw_records = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for r in rows:
        row = {k: r.get(k) for k in columns}
        row["data_source"] = "auto_result_fetch"
        row["updated_at"] = now_iso
        raw_records.append(row)

    clean_stats = append_raw_results(raw_records, data_source="auto_result_fetch", base_dir=root)

    # 保持 legacy match_results.csv 兼容统计
    merged = pd.read_csv(path) if path.exists() else pd.DataFrame()
    matched_predictions = _count_matched_predictions(root, merged)
    logger.info(
        "赛果写入完成 issue_date=%s mode=%s parsed=%s raw_appended=%s clean_rows=%s bad_rows=%s matched_predictions=%s path=%s",
        target_date,
        mode,
        len(rows),
        clean_stats.get("appended_raw", 0),
        clean_stats.get("clean_rows", 0),
        clean_stats.get("bad_rows", 0),
        matched_predictions,
        path,
    )

    # 赛果保存成功后重建事实表
    facts_rebuilt = False
    try:
        from src.services.match_fact_builder import rebuild_match_facts
        rebuild_match_facts(root)
        facts_rebuilt = True
    except Exception as exc:
        logger.warning("result save后重建facts失败 err=%s", type(exc).__name__)

    return {
        "ok": True,
        "path": str(path),
        "issue_date": target_date,
        "mode": mode,
        "requested_urls": requested_count,
        "parsed_rows": len(rows),
        "written_rows": int(clean_stats.get("clean_rows", 0)),
        "matched_predictions": matched_predictions,
        "bad_rows": int(clean_stats.get("bad_rows", 0)),
        "facts_rebuilt": facts_rebuilt,
    }


def fetch_results_by_date(issue_date: str) -> list[dict[str, str | None]]:
    fetcher = ResultFetcher(client=HTTPClient())
    rows, _, _ = fetcher.fetch_results_by_date(issue_date)
    return rows
