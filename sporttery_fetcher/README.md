# sporttery_fetcher

本项目是一个本地可运行的中国体彩竞彩足球抓取器（MVP）。

> 当前主数据源已切换为官方竞彩足球计算器页面：
> `https://www.sporttery.cn/jc/jsq/zqspf/index.html`

---

## 1. 核心能力

- API / XHR 优先（从 detector 结果或配置候选接口中抓取）
- HTML 解析回退（BeautifulSoup）
- Playwright 动态渲染回退
- 移动端页面兜底
- 标准化输出 JSON/CSV，支持后续扩展

---

## 2. 安装

```bash
cd sporttery_fetcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

---

## 3. 运行

抓取指定日期（推荐）：

```bash
python -m src.main --date 2026-03-19
```

抓取当天：

```bash
python -m src.main
```

输出文件：
- `data/raw/YYYY-MM-DD_matches.json`
- `data/processed/YYYY-MM-DD_matches.csv`

---

## 4. 接口检测（建议先执行）

```bash
python -m src.fetchers.interface_detector
# 或指定 URL
python -m src.fetchers.interface_detector --url https://www.sporttery.cn/jc/jsq/zqspf/index.html
```

输出：
- `data/raw/detected_xhr.json`

说明：主流程会先尝试 API 抓取；若接口不可用会自动回退 HTML/Playwright。

---

## 5. 字段说明

输出字段（含新增赔率字段）：

- issue_date
- match_no
- league
- home_team
- away_team
- kickoff_time
- handicap
- sell_status
- spf_win
- spf_draw
- spf_lose
- rqspf_win
- rqspf_draw
- rqspf_lose
- play_spf
- play_rqspf
- play_score
- play_goals
- play_half_full
- source_url
- scrape_time
- raw_id

说明：
- `handicap` 优先从明确让球字段解析，避免把赔率数字误识别为让球。
- 无法确认字段保留 `null`。

---

## 6. 自检

```bash
python tests/self_check.py --date 2026-03-19
```

自检包含：
1. 主页面可访问（zqspf 计算器页）
2. 至少抓到 1 场比赛
3. handicap 至少在部分比赛非空
4. detector 输出文件存在

---

## 7. 配置

可通过 `.env` 覆盖：

- `PRIMARY_PAGE_URL`：默认主页面 URL
- `API_CANDIDATE_URLS`：逗号分隔 API 候选接口
- `REQUEST_TIMEOUT` / `REQUEST_RETRIES` / `RETRY_WAIT_SECONDS`
- `SAVE_HTML_SNAPSHOT`
- `PLAYWRIGHT_HEADLESS`

---

## 8. 故障排查

1. 先看 `logs/app.log`
2. 先跑 `python -m src.fetchers.interface_detector`
3. 若 Playwright 报错，执行 `playwright install chromium`
4. 检查 `data/raw/snapshots/` HTML 快照是否有目标表格
