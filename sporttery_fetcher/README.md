# sporttery_fetcher

本项目是一个**本地可运行的中国体彩竞彩足球比赛信息抓取器（第一阶段 MVP）**。  
目标：先稳定抓取每日比赛信息并落地到本地 JSON / CSV。

> 当前只做竞彩足球抓取，不含预测逻辑、不接大模型 API、不做前端可视化。

---

## 1. 项目结构

```text
sporttery_fetcher/
  README.md
  requirements.txt
  .env.example
  config/
    settings.py
  src/
    main.py
    fetchers/
      api_fetcher.py
      html_fetcher.py
      mobile_fetcher.py
      interface_detector.py
    parsers/
      normalize.py
    utils/
      logger.py
      http.py
      save.py
  data/
    raw/
    processed/
  logs/
    app.log
  tests/
```

---

## 2. 环境要求

- Python 3.11+
- macOS 本地运行（Linux 也可）

安装依赖：

```bash
cd sporttery_fetcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如需 Playwright 回退：

```bash
playwright install chromium
```

---

## 3. 快速开始

### 3.1 抓取当天

```bash
python -m src.main
```

### 3.2 抓取指定日期

```bash
python -m src.main --date 2026-03-19
```

运行成功后会输出：
- 抓取条数
- 使用策略（api/html/mobile）
- JSON / CSV 保存路径

默认输出路径：
- `data/raw/YYYY-MM-DD_matches.json`
- `data/processed/YYYY-MM-DD_matches.csv`

---

## 4. 抓取策略（两层 + 回退）

1. **API 抓取器** `src/fetchers/api_fetcher.py`
   - 优先尝试站内 JSON/XHR 接口。
   - 如果接口不可用或响应不是 JSON，自动进入下一层。

2. **HTML 抓取器** `src/fetchers/html_fetcher.py`
   - requests + BeautifulSoup 解析官方页面。
   - 如页面动态渲染导致静态 HTML 无数据，自动回退 Playwright。

3. **移动端兜底** `src/fetchers/mobile_fetcher.py`
   - 再尝试移动端官方页面解析。

---

## 5. 官方页面接口检测（XHR/JSON）

运行自动检测脚本：

```bash
python -m src.fetchers.interface_detector
# 或指定 URL
python -m src.fetchers.interface_detector --url https://www.sporttery.cn/jc/zqss/
```

脚本会：
- 监听页面加载时的 XHR/Fetch
- 提取 URL / Method / PostData / 响应片段
- 保存到 `data/raw/detected_xhr.json`

如果自动检测失败，会打印手动排查说明（F12 Network -> XHR/Fetch）。

---

## 6. 字段标准化

无论 API 还是 HTML，统一输出以下字段：

- issue_date
- match_no
- league
- home_team
- away_team
- kickoff_time
- handicap
- sell_status
- play_spf
- play_rqspf
- play_score
- play_goals
- play_half_full
- source_url
- scrape_time
- raw_id

说明：
- 暂时抓不到的字段会保留为 `null`，不会导致程序崩溃。
- 解析规则集中在 `src/parsers/normalize.py`，便于后续扩展。

---

## 7. 日志与容错

- 控制台 + `logs/app.log` 双日志
- 请求超时重试（tenacity）
- 自定义 User-Agent
- 自动编码处理
- API 失败自动回退 HTML
- 可选 HTML 快照保存（用于页面结构漂移调试）

HTML 快照默认开启，路径：
- `data/raw/snapshots/*.html`

可通过 `.env` 关闭：

```env
SAVE_HTML_SNAPSHOT=false
```

---

## 8. 后续扩展建议（下一阶段）

1. 复用同一框架新增“足球赛果开奖页”抓取器。  
2. 增加“赛事公告页”结构化解析（停售、延期、取消）。  
3. 将接口检测结果自动写回 API 配置，提高可维护性。  
4. 引入数据库持久化（如 SQLite / Postgres）并加去重策略。  
5. 增加字段质量检查（空值率、字段漂移告警）。

