# 台股回測研究 — 跨 session 交接筆記

兩個 Claude session 同時在這個 repo 做台股回測,但跨 session 直接通訊在此環境不可用,
所以用這份文件當交接媒介。

| | session A | session B |
|---|---|---|
| 標題 | 台灣股市估值策略回測 | 股票檢測與分析環境 |
| 分支 | `claude/taiwan-stock-valuation-backtest-assutt` | `main` / `claude/stock-detection-analysis-env-1jnhgu` |
| 產出 | `tw_stock_backtest/`(框架) | `research/`、`docs/`、`tools/`(資料 + 網頁) |

以下由 session B 撰寫,內容都是**實測結果,不是推測**。

---

## 一、最重要的一件事:這個環境可以抓真實資料

`tw_stock_backtest/README.md` 目前寫著「必須換一個網路出口政策較寬鬆的執行環境」。
沙盒本身確實封鎖對外連線,但 **GitHub Actions 的 runner 有完整對外網路**,
而且這個 repo 已經有現成可用的 workflow。

`.github/workflows/research.yml` — 用 `workflow_dispatch` 觸發,
`inputs.script` 指定 `research/` 底下的檔名即可執行,產出會自動 commit 回 repo。

session B 已用它抓到大量真實資料並跑出回測結果。**不需要換環境。**

---

## 二、已實測可用的端點與實際回應格式

### 證交所(無硬性配額,間隔 2~2.5 秒即可)

```
https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=YYYYMMDD&type=ALLBUT0999&response=json
```
回傳 `tables` 陣列。要找 fields 含「證券代號 / 收盤價 / 成交金額」的那一張。

> ⚠ 2015 年只有 4 張表有資料、2024 年有 10 張。**必須用欄名尋找,不能用固定索引。**

```
https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=YYYYMMDD&response=json
```
個股本益比 / 殖利率 / 股價淨值比。

> ⚠ **欄位結構這十年變過:2015 是 5 欄、2024 是 8 欄。**
> 一律用欄名對應,用位置取值會在某個年份靜默錯位 —— 這種錯誤不會拋例外,只會讓數字變成別的東西。

- 非交易日回傳 `{"stat": "很抱歉,沒有符合條件的資料!"}`,可據此判斷。
- 民國年 7 碼(`1150904`)轉西元:`int(raw[:3]) + 1911`。
- `STOCK_DAY_ALL`(當日全市場)回傳的是 **CSV 而非 JSON**,即使帶 `response=json`。

### FinMind(匿名可用,配額很緊)

建議 1.5~2 秒間隔並做指數退避。session B 曾用 360 次請求跑了 110 分鐘才被迫取消。

| dataset | 實際欄位 |
|---|---|
| `TaiwanStockPrice` | date, stock_id, open, max, min, close, Trading_Volume, Trading_money |
| `TaiwanStockPER` | date, stock_id, dividend_yield, PER, PBR |
| `TaiwanStockMonthRevenue` | date, stock_id, revenue, revenue_year, revenue_month |
| `TaiwanStockFinancialStatements` | 長格式:date, stock_id, type, value, origin_name |
| `TaiwanStockInstitutionalInvestorsBuySell` | date, stock_id, buy, sell, name |

**已驗證 FinMind 保有已下市公司的歷史資料**(抽測 10 檔全部有,含綠悅-KY、永冠-KY)。

> `tw_stock_backtest/finmind_source.py` 的 README 自述是在無法連線查證 API 的情況下寫的,
> 請以上表實測欄名為準核對。

### 一個省事的推導

`ROE = PBR ÷ PER`,因為 `(P/B)/(P/E) = E/B`。
所以只要有 `TaiwanStockPER` 就能算出 ROE,不必解析財報的長格式,
而且兩者都是當日值,不會引入前視偏誤。

---

## 三、可直接取用的既有資料(已在 `main`)

| 檔案 | 內容 |
|---|---|
| `research/data/price.csv.gz` | 120 檔 × 2014-01~2026-09 日線,350,860 筆 |
| `research/data/valuation.csv.gz` | 同期每日 PER/PBR/殖利率,346,450 筆 |
| `research/data/revenue.csv.gz` | 月營收,17,283 筆,120 檔完整 |
| `research/data/pit/universe_by_date.csv` | 逐季 point-in-time 股票池(抓取中) |
| `research/output/backtest_results.json` | 已完成的回測結果與權益曲線 |
| `docs/data/stocks.json` | 120 檔近 500 根日 K,供網頁使用 |

---

## 四、三個實作陷阱(session B 已踩過)

### 1. 權益曲線只在換股日取樣,會讓最大回撤低估到剩三分之一

原本只在每季換股日記錄淨值,季中的回檔完全看不見。
價值策略 MDD 顯示 -8.7%,改成逐日計算後是 -10.2%;動能從 -10.7% 變 -11.6%。

**對停損策略研究來說,回撤算錯等於整份報告白做。** 請確認 equity curve 是逐日的。

### 2. 因子公式可能靜默退化

session B 寫過 `score = roe / PBR`,而 `roe = PBR / PER`,代入後恰好等於 `1/PER` ——
品質因子完全沒有參與排序,但函式名稱還叫「品質×價值」。

用 z-score 或百分位排名合成比較不容易發生,但仍值得逐一檢查各因子是否真的獨立貢獻。

### 3. 倖存者偏誤比想像嚴重,而且主因不是下市

實測全市場檔數:

| | 檔數 |
|---|---|
| 2015-01-05 全市場(四碼普通股) | 873 |
| 2026-09-04 全市場 | 1093 |
| 2015 有、今天沒有(已下市/改代號) | **71** |
| 今天有、2015 沒有(期間才上市) | **291** |

**新上市那半是下市那半的四倍。**

`tw_stock_backtest/config.py` 目前用 20 檔寫死的固定名單(2330/2317/2454/…),
其中多檔在 2015 年還沒上市或市值遠小於今天,回測會假裝當時就能買。

session B 的證據:用「今天成交金額前 120 名」回頭套十年,
**等權全持對照組跑出年化 25.38%**,而台股同期實際約 10~13%。
那 12 個百分點全部是偏誤。

修法是每個換股日各取當天的名單(`research/fetch_pit.py`),
`research/backtest.py` 的 universe 參數已支援 `dict` 形式的逐期清單。

---

## 五、一個容易被忽略的對照組設計

只看策略的絕對報酬沒有意義,因為它同時包含了股票池的效應。
session B 加了一條對照線:**同一個股票池、等權重、同樣每季再平衡、全部持有**。

策略減去它,才是選股邏輯真正的貢獻。結果很有啟發性:

| 策略 | 年化 | 對照組超額 |
|---|---:|---:|
| 對照:等權全持 | +25.38% | — |
| 價值:低股價淨值比 | +19.41% | **−5.97pp** |
| 品質×價值 | +17.85% | **−7.53pp** |
| 高現金殖利率 | +16.43% | **−8.95pp** |
| 動能 12-1 | +35.25% | +9.87pp |
| 月營收年增動能 | +34.22% | +8.84pp |

三個「便宜股」策略**輸給無腦全買**。單看「年化 19%」會覺得不錯,
但那全部來自股票池,選股邏輯是扣分的。

20% 停損使五個策略年化全數下降 2.40~7.58 個百分點,其中動能受傷最重
(觸發率 30.3%,付出 6.68pp 只換到 1.0pp 的回撤改善)。

---

## 六、兩邊的分工建議

`tw_stock_backtest/` 的架構比 `research/` 好:設定集中在 `config.py`、因子可加權、
有總經濾網、有測試、月頻再平衡可調。`research/` 的優勢是已驗證的真實資料管線。

- **session A**:保留並強化框架 —— 修 README 的環境結論、依實測欄名核對資料源、
  把 `universe` 改成可接受「逐期名單」而非固定 list、確認 equity curve 逐日、
  加一個讀 `research/data/` 的資料源。
- **session B**:完成 point-in-time 股票池與新舊對照回測,產出放在 `research/data/pit/`。

### 避免衝突

- session B 動:`research/`、`docs/`、`tools/`、`app.py`、`twse_quotes.py`
- session A 動:`tw_stock_backtest/`
- 這份文件由 session B 維護

---

## 七、安全提醒

**這個 repo 是公開的。** 不要再往裡面加任何真實個資或憑證。

- `app.py` 目前仍有硬編碼的 LINE CHANNEL_ACCESS_TOKEN 與 SECRET(自 2026-06-17 起),
  已知需要在 LINE Developers 後台重新產生,只有 repo 擁有者能做。
- `data/performance.json` 是公司內部業績數字,且排程每小時 commit 一次。
- 業展處主管姓名已改為代稱,真名改由環境變數 `DEPARTMENT_MANAGERS_JSON` 提供。
