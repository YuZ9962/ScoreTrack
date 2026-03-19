# sporttery_fetcher

本项目是一个**本地可运行的中国体彩竞彩足球比赛信息抓取器（第一阶段 MVP）**。  
目标：稳定抓取每日比赛信息并落地到本地 JSON / CSV。

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
    self_check.py
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

## 3. 当前已确认可用的竞彩足球接口

已确认可用接口（API 主链路）：

```text
GET https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001
```

程序默认优先请求该接口。若接口异常，自动回退 HTML -> 移动端。

---

## 4. 快速开始

### 4.1 抓取当天

```bash
python -m src.main
```

### 4.2 抓取指定日期

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

## 5. 抓取策略（API 优先 + 回退）

1. **API 抓取器** `src/fetchers/api_fetcher.py`
   - 固定使用 `getMatchListV1.qry?clientCode=3001`。
   - 解析 `value.matchInfoList[*].subMatchList[*]`。
   - 按 `businessDate == --date` 过滤（无 businessDate 时回退 matchDate）。

2. **HTML 抓取器** `src/fetchers/html_fetcher.py`
   - requests + BeautifulSoup 解析官方页面：
     - `https://www.sporttery.cn/jc/zqszsc/`
   - 如页面动态渲染导致静态 HTML 无数据，自动回退 Playwright。

3. **移动端兜底** `src/fetchers/mobile_fetcher.py`
   - 再尝试移动端官方页面解析。

---

## 6. 官方页面接口检测（XHR/JSON）

运行自动检测脚本：

```bash
python -m src.fetchers.interface_detector
# 或指定 URL
python -m src.fetchers.interface_detector --url https://www.sporttery.cn/jc/zqszsc/
```

输出文件：
- `data/raw/detected_xhr.json`

---

## 7. 标准化字段

统一输出：
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
- 暂时抓不到的字段保留 `null`，不崩溃。
- API 映射规则：
  - `issue_date <- businessDate`（缺失时回退 matchDate）
  - `match_no <- lineNum`
  - `league <- leagueAllName > leagueAbbName`
  - `home_team <- homeTeamAllName > homeTeamAbbName`
  - `away_team <- awayTeamAllName > awayTeamAbbName`
  - `raw_id <- matchId`
  - `source_url <- https://www.sporttery.cn/jc/zqszsc/`

---

## 8. 修复后验证步骤（推荐）

### 8.1 一键自检（主页面 + API + HTML + detector）

```bash
python tests/self_check.py --date 2026-03-19
```

### 8.2 主程序验证

```bash
python -m src.main --date 2026-03-19
```

### 8.3 查看输出文件

```bash
ls -lh data/raw/2026-03-19_matches.json
ls -lh data/processed/2026-03-19_matches.csv
```

---

## 9. 日志与容错

- 控制台 + `logs/app.log` 双日志
- 请求超时重试（tenacity）
- 自定义 User-Agent
- 自动编码处理
- API 失败自动回退 HTML
- 可选 HTML 快照保存（用于页面结构漂移调试）

---

## 10. 下一阶段建议

1. 基于 `https://www.sporttery.cn/jc/zqsgkj/` 新增赛果抓取器。  
2. 增加赛事公告页结构化解析。  
3. 将赛程抓取结果写入数据库并做去重与增量。  
