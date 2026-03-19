# sporttery_fetcher

本项目包含两部分：
1. **抓取端**：本地抓取中国体彩竞彩足球数据并保存 CSV/JSON。
2. **前端仪表盘（Streamlit）**：本地查看、筛选、统计每日比赛数据。

---

## 1. 数据抓取（已有）

主页面：
- `https://www.sporttery.cn/jc/jsq/zqspf/index.html`

API（优先）：
- `https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?channel=c&poolCode=hhad,had`

运行抓取：

```bash
python -m src.main --date 2026-03-19
```

输出：
- `data/raw/YYYY-MM-DD_matches.json`
- `data/processed/YYYY-MM-DD_matches.csv`

---

## 2. 前端仪表盘（新增）

### 2.1 页面说明

- **Dashboard（首页）**
  - 总比赛数
  - handicap 非空场次
  - 开售场次
  - 联赛分布
  - 最早/最晚开赛时间
  - 最近抓取时间

- **Matches（比赛列表）**
  - 表格展示比赛
  - 支持筛选：日期、联赛、关键词、handicap 非空、开售
  - 支持排序：开赛时间/联赛/场次编号
  - 可选中单场并展示详情卡片

- **Match Detail（比赛详情）**
  - 基础信息卡片
  - 胜平负奖金卡片
  - 让球胜平负奖金卡片
  - 原始抓取信息（source_url/raw_id/scrape_time）

- **Analytics（统计分析）**
  - 每日比赛数趋势
  - 联赛比赛数柱状图
  - handicap 分布柱状图
  - 胜平负与让球胜平负赔率统计摘要

### 2.2 运行方式

```bash
streamlit run app/app.py
```

启动后浏览器会打开本地地址（默认 `http://localhost:8501`）。

---

## 3. 安装

```bash
cd sporttery_fetcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

---

## 4. 前端数据来源规则

- 直接读取：`data/processed/*_matches.csv`
- 默认选择最新日期文件
- 支持用户切换日期文件
- 无文件或空数据时给出友好提示

---

## 5. 字段（CSV）

前端默认使用这些字段：

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
- source_url
- scrape_time
- raw_id

---

## 6. 常见问题

1. **没有数据文件**
   - 先执行抓取命令：`python -m src.main --date 2026-03-19`
2. **Streamlit 启动失败**
   - 确认依赖已安装：`pip install -r requirements.txt`
3. **接口变化导致数据异常**
   - 先跑：`python -m src.fetchers.interface_detector`
   - 查看：`logs/app.log` 与 `data/raw/snapshots/`
