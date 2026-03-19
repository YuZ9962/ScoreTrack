# sporttery_fetcher

本项目是一个本地可运行的中国体彩竞彩足球抓取器（MVP）。

> 当前主数据源：
> `https://www.sporttery.cn/jc/jsq/zqspf/index.html`

---

## 1. 抓取链路

1. API 优先（已确认接口）：

```text
https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?channel=c&poolCode=hhad,had
```

2. API 异常时自动回退 HTML / Playwright。
3. 再失败时回退移动端兜底。

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

```bash
python -m src.main --date 2026-03-19
```

输出：
- `data/raw/YYYY-MM-DD_matches.json`
- `data/processed/YYYY-MM-DD_matches.csv`

---

## 4. 已确认字段映射（getMatchCalculatorV1）

- `match_no = matchNumStr`
- `issue_date = businessDate`
- `league = leagueAllName > leagueAbbName`
- `home_team = homeTeamAllName > homeTeamAbbName`
- `away_team = awayTeamAllName > awayTeamAbbName`
- `kickoff_time = matchDate + " " + matchTime[:5]`（缺时间时保留 matchDate）
- `raw_id = matchId`
- `source_url = https://www.sporttery.cn/jc/jsq/zqspf/index.html`

让球：
- `handicap = hhad.goalLine`
- 若为空，回退 `hhad.goalLineValue`
- 再回退 `oddsList(poolCode=HHAD).goalLine`

胜平负奖金：
- `spf_win = had.h`
- `spf_draw = had.d`
- `spf_lose = had.a`
- had 缺失时回退 `oddsList(poolCode=HAD)`

让球胜平负奖金：
- `rqspf_win = hhad.h`
- `rqspf_draw = hhad.d`
- `rqspf_lose = hhad.a`
- hhad 缺失时回退 `oddsList(poolCode=HHAD)`

开售状态：
- `matchStatus == "Selling"` 或 `sellStatus == 2` -> `sell_status = "开售"`
- 否则保留原始 `matchStatus/sellStatus`

---

## 5. 接口检测（排查优先）

```bash
python -m src.fetchers.interface_detector
# 或指定 URL
python -m src.fetchers.interface_detector --url https://www.sporttery.cn/jc/jsq/zqspf/index.html
```

输出文件：
- `data/raw/detected_xhr.json`

---

## 6. 自检

```bash
python tests/self_check.py --date 2026-03-19
```

自检检查：
1. 主页面可访问
2. 至少抓到 1 场
3. 至少 1 场 `handicap` 非空
4. 至少 1 场 `spf_win` 非空
5. 至少 1 场 `rqspf_win` 非空
6. detector 输出文件存在

---

## 7. 常见排查

1. 查看 `logs/app.log`
2. 先跑 `python -m src.fetchers.interface_detector`
3. 若 Playwright 报错，执行 `playwright install chromium`
4. 检查 `data/raw/snapshots/` 中 HTML 快照
