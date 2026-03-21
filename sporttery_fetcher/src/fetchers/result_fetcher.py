from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

import pandas as pd
from bs4 import BeautifulSoup

from config.settings import settings
from src.utils.http import HTTPClient


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
            if re.search(r"\d{1,2}\s*[-:：]\s*\d{1,2}", cell):
                score = re.search(r"\d{1,2}\s*[-:：]\s*\d{1,2}", cell).group(0).replace("：", "-").replace(":", "-")
                break
        if not score:
            return None

        match_no = next((c for c in cells if re.search(r"周[一二三四五六日天]\d{3}", c)), None)
        league = cells[2] if len(cells) > 2 else None

        teams = None
        for c in cells:
            if "vs" in c.lower() or "-" in c:
                teams = c
                if re.search(r"\d{1,2}\s*[-:：]\s*\d{1,2}", c):
                    continue
                break

        home_team, away_team = None, None
        if teams:
            parts = re.split(r"\s+vs\s+|\s+VS\s+|\s*[-—]\s*", teams)
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

    def fetch_results(self) -> list[dict[str, str | None]]:
        rows: list[dict[str, str | None]] = []

        for url in settings.result_urls:
            try:
                resp = self.client.request("GET", url)
            except Exception:
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            trs = soup.select("table tr")
            if not trs:
                trs = soup.select("tr")

            for tr in trs:
                tds = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                parsed = self._parse_row(tds)
                if parsed:
                    rows.append(parsed)

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

        return list(deduped.values())



def results_file(base_dir: Path | None = None) -> Path:
    root = base_dir or settings.base_dir
    path = root / "data" / "results" / "match_results.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path



def fetch_and_save_results(base_dir: Path | None = None) -> Path:
    fetcher = ResultFetcher(client=HTTPClient())
    rows = fetcher.fetch_results()

    path = results_file(base_dir)
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
    merged = merged.drop_duplicates(subset=["issue_date", "raw_id", "match_no", "home_team", "away_team"], keep="last")
    merged.to_csv(path, index=False, encoding="utf-8-sig")
    return path
