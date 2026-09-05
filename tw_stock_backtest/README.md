# 台股多因子估值 / 投資策略回測框架

這個模組是為了回答「台股最有效的估值/投資策略是什麼、能不能回測、能不能結合總經與多因子」
而建立的一套**完整、可執行**的研究 + 回測程式碼。策略研究內容見 [`RESEARCH.md`](./RESEARCH.md)。

## ⚠️ 目前這個沙盒環境跑不出「真實」回測結果

開發這套程式的執行環境，網路出口政策封鎖了所有外部資料 API，不只金融資料（Yahoo Finance、
FinMind、證交所 OpenAPI 皆回傳 `EGRESS_BLOCKED`），連政府開放資料平台（data.gov.tw）與
央行開放資料 API（cpx.cbc.gov.tw）也一併被封鎖（已實測 `curl` 直接被 proxy 拒絕，回應
`403`）。這不是「手動 vs 自動」的差異能解決的問題，而是這個沙盒環境的網路出口政策本身
擋掉了所有非白名單網域（只放行 pypi/npm/github/anthropic 等開發用途網域），所以**無論
是股價/財報還是總經指標，這裡都無法自動抓到任何真實資料**。

如果你希望在 Claude Code 的環境裡直接讓我抓真實資料，需要的是**換一個網路出口政策較寬鬆
的執行環境**（建立 Claude Code on the web 的環境時可以選擇網路政策），而不是改程式碼；
目前這個環境是在建立當下就選定了限制較嚴的政策。詳見
[Claude Code on the web 文件](https://code.claude.com/docs/en/claude-code-on-the-web)。
在你自己的電腦或 GitHub Actions 執行則完全沒有這個限制。

已經在本環境完成、且驗證過可正常運作的部分：
- 完整的多因子選股 + 月頻再平衡 + -20% 停損 + 交易成本的回測引擎（`backtest.py`）。
- 用「合成隨機資料」跑過 `tests/test_pipeline_synthetic.py` 全流程兩次（一般情境 + 刻意
  製造崩跌以確保停損機制真的會觸發），**兩個測試都通過**，證明程式邏輯正確、不會中途出錯、
  數字不會出現不合理的爆量（例如因為資料洩漏 look-ahead bias 而報酬率虛高）。
- CLI 也已經跑過一次 `python -m tw_stock_backtest.run_backtest --source synthetic`，
  能完整輸出 `equity_curve.csv`、`trades.csv`、`report.json` 三個檔案。

## ✅ 已幫你架好：GitHub Actions 自動回測（推薦，不需要手動做任何事）

`.github/workflows/tw_stock_backtest.yml` 會在 GitHub 自己的 runner 上執行（不受這個
沙盒環境的網路限制），完全自動：
1. 手動觸發：Repo 頁面 → **Actions** → 「台股多因子回測」→ **Run workflow**（可選資料源
   / 回測區間，留空用預設）。
2. 或什麼都不用做：**每週一台灣時間早上 9 點自動跑一次**，同時跑 `default` / `long_term`
   / `short_term` 三組預設。
3. 結果自動 commit 回 [`results/`](./results/) 目錄（`report.json` / `equity_curve.csv` /
   `trades.csv`），也會寫進該次 workflow run 的 Job Summary，不需要下載、不需要自己執行
   任何指令。
4.（可選）到 repo 的 Settings → Secrets and variables → Actions 加一個 `FINMIND_TOKEN`
   （https://finmindtrade.com/ 免費註冊），可以提高資料源的 API 呼叫額度；不加也能跑。

這是目前**唯一不需要你自己動手**的路徑——下面「如何取得真實回測結果」是給想在本機/自己
的 CI 環境手動控制參數時參考的步驟，兩者用的是同一套程式碼。

## 目錄結構

```
tw_stock_backtest/
├── RESEARCH.md              # 量化/質化策略研究彙整、總經指標建議
├── config.py                # 所有可調參數（母體、因子權重、停損%、再平衡頻率、交易成本…）
├── factors.py                # 因子計算 + 橫斷面 z-score + 複合分數 + 選股
├── macro.py                  # 總經濾網（SOX動能、M1B年增率、政策利率、景氣燈號 → 多空分數）
├── backtest.py                # 回測引擎：買進/賣出/停損/再平衡
├── metrics.py                 # 績效指標：CAGR/Sharpe/Sortino/MDD/勝率/對比基準
├── run_backtest.py            # CLI 進入點
├── data_sources/
│   ├── base.py                    # 抽象介面 + 固定 schema
│   ├── synthetic_source.py        # 合成資料（本環境可用，僅供驗證程式邏輯）
│   ├── finmind_source.py          # FinMind API（推薦的真實資料源，需網路）
│   ├── yfinance_source.py         # yfinance（備援，台股基本面覆蓋率較差）
│   └── twse_source.py             # 證交所公開資料（備援，僅價格，無基本面）
│   └── opendata_macro_source.py   # 全自動抓景氣對策信號/M1B/出口訂單/央行利率，不需手動維護
├── data/macro_manual_template.csv # 備援用：自動抓取失敗時才需要的手動範本（預設流程用不到）
└── tests/
```

## 如何取得真實回測結果

1. 到一個有網路權限的環境（本機終端機、GitHub Actions、Colab 皆可）。
2. `pip install -r tw_stock_backtest/requirements.txt`
3.（建議）到 https://finmindtrade.com/ 註冊免費帳號取得 API token，設定環境變數：
   `export FINMIND_TOKEN=你的token`（不設定也能跑，只是額度較低、且每小時 600 次呼叫上限）。
4. **先核對 API 文件**：`finmind_source.py` 檔頭有清楚註記，這份程式碼是在無法連線查證
   最新 FinMind 文件的情況下寫的，dataset 名稱/欄位若已改版，對照
   https://finmind.github.io/ 調整檔案開頭的常數即可，其他模組完全不用動。
5. 執行：
   ```bash
   python -m tw_stock_backtest.run_backtest \
       --source finmind \
       --start 2015-01-01 --end 2024-12-31 \
       --output-dir out
   ```
   景氣對策信號、央行重貼現率、M1B年增率、出口訂單年增率**預設會自動**從政府開放資料平台
   （data.gov.tw dataset 6099）與央行開放資料 API（cpx.cbc.gov.tw dataset 6022）抓取並合併，
   不需要準備、也不需要手動更新任何 CSV，見 `data_sources/opendata_macro_source.py`。
   只有在這條自動路徑因為平台改版而失敗時，程式會印出警告並自動略過該部分（其餘因子照常
   運作，總經濾網那幾項會變中性值），此時才需要考慮用 `--manual-macro-csv` 提供備援資料。
6. 看 `out/report.json`（結構化）或終端機印出的 `format_report_text`（人類可讀）。

也可以改用 `--source yfinance`（不需要 token，但基本面資料品質較差，只適合先看價格面
的動能/低波動因子效果）或 `--source twse`（只有價格，速度較慢，適合交叉驗證）。

## 想先驗證程式邏輯（不需要網路）

```bash
pip install -r tw_stock_backtest/requirements.txt
python -m pytest tw_stock_backtest/tests/ -v
python -m tw_stock_backtest.run_backtest --source synthetic --output-dir out_synthetic_demo
```
這條路徑產生的數字**沒有任何真實市場意義**，純粹是拿隨機亂數資料證明整條 pipeline（資料
→ 因子 → 選股 → 買賣 → 停損 → 績效報告）跑得通、不會中途拋錯、也不會因為程式漏洞讓報酬率
不合理地爆量或憑空出現負值資產。

## 調整策略

所有策略行為都集中在 `config.py`：
- `factor_weights`：調整價值/品質/成長/動能/低波動/籌碼因子的權重（設 0 代表停用）。
- `top_n` / `defensive_top_n` / `macro_defensive_threshold`：總經轉差時自動縮減持股檔數。
- `stop_loss_pct`：預設 0.20（-20%），改這一個數字就能測試不同停損%的影響。
- `rebalance_freq`："W"（週頻）、"M"（月頻）或 "Q"（季頻）。
- `factor_windows`：動能/波動度因子的回看天數，長期策略用長窗口（如 252/21/60 日）濾雜訊，
  短期策略要縮短（如 60/5/20 日）才能捕捉半年內的訊號。
- 已內建兩組預設：`config.long_term_config()`（長期投資）與 `config.short_term_config()`
  （半年內短期投資），差異與使用方式見 RESEARCH.md「長期 vs 短期投資策略設計」一節，或直接
  用 CLI：`--preset long_term` / `--preset short_term`。
- `buy_commission_rate` / `sell_commission_rate` / `sell_tax_rate`：交易成本假設。

## 已知限制（誠實列出，正式使用前務必知道）

- 再平衡目前只處理「因子排名被淘汰 / 新入選」的股票，既有且仍在名單內的持股**不會**被強制
  調整回等權重，這是簡化實作，不是完整的目標權重再平衡。
- `finmind_source.py` / `twse_source.py` / `opendata_macro_source.py` 的欄位映射是依訓練
  資料當中的既有知識撰寫，**沒有在真實 API 上驗證過**（沙盒環境連不上這些網域），第一次
  使用請務必對照官方文件核對；`opendata_macro_source.py` 已經寫成「找關鍵字」而非寫死欄位
  順序，失敗時會印出清楚的錯誤訊息（列出實際欄位/檔名），方便你快速修正關鍵字。
- 回測結果的品質高度依賴：(1) 財報「公告可用日」是否正確（避免 look-ahead bias）、
  (2) 存活者偏差（universe 若只放現在還在市場上的股票，會高估歷史績效，應該用「當時的
  完整上市櫃清單」而非事後回推的清單）、(3) 交易成本與流動性篩選是否貼近實務。
- 回測區間建議 ≥ 8～10 年並涵蓋至少一次完整多空循環，否則績效數字沒有代表性。
