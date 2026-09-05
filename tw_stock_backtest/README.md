# 台股多因子估值 / 投資策略回測框架

這個模組是為了回答「台股最有效的估值/投資策略是什麼、能不能回測、能不能結合總經與多因子」
而建立的一套**完整、可執行**的研究 + 回測程式碼。策略研究內容見 [`RESEARCH.md`](./RESEARCH.md)。

## ⚠️ 目前這個沙盒環境跑不出「真實」回測結果

開發這套程式的執行環境，網路出口政策封鎖了所有金融資料 API（Yahoo Finance、FinMind、
證交所 OpenAPI 皆回傳 `EGRESS_BLOCKED`），因此**這裡無法抓取真實股價/財報並產生真實的
投資報酬率數字**。

已經在本環境完成、且驗證過可正常運作的部分：
- 完整的多因子選股 + 月頻再平衡 + -20% 停損 + 交易成本的回測引擎（`backtest.py`）。
- 用「合成隨機資料」跑過 `tests/test_pipeline_synthetic.py` 全流程兩次（一般情境 + 刻意
  製造崩跌以確保停損機制真的會觸發），**兩個測試都通過**，證明程式邏輯正確、不會中途出錯、
  數字不會出現不合理的爆量（例如因為資料洩漏 look-ahead bias 而報酬率虛高）。
- CLI 也已經跑過一次 `python -m tw_stock_backtest.run_backtest --source synthetic`，
  能完整輸出 `equity_curve.csv`、`trades.csv`、`report.json` 三個檔案。

**你需要做的事**：在一個有一般網路權限的環境（自己的電腦、GitHub Actions、Google Colab 等）
安裝套件並執行下面「如何取得真實回測結果」的步驟，就能得到真實資料算出來的報酬率。

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
├── data/macro_manual_template.csv # 沒有穩定公開 API 的總經指標，手動維護的範本
└── tests/test_pipeline_synthetic.py
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
       --manual-macro-csv tw_stock_backtest/data/macro_manual_template.csv \
       --output-dir out
   ```
   `--manual-macro-csv` 請先照著 `data/macro_manual_template.csv` 的格式，把景氣對策信號、
   央行政策利率、出口訂單年增率、M1B年增率填成真實歷史數字（來源見 RESEARCH.md 第三節的
   資料源表格），這幾項沒有穩定的免費 API，需要手動維護。
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
- `finmind_source.py` / `twse_source.py` 的欄位映射是依訓練資料當中的既有知識撰寫，**沒有
  在真實 API 上驗證過**，第一次使用請務必對照官方文件核對。
- 回測結果的品質高度依賴：(1) 財報「公告可用日」是否正確（避免 look-ahead bias）、
  (2) 存活者偏差（universe 若只放現在還在市場上的股票，會高估歷史績效，應該用「當時的
  完整上市櫃清單」而非事後回推的清單）、(3) 交易成本與流動性篩選是否貼近實務。
- 回測區間建議 ≥ 8～10 年並涵蓋至少一次完整多空循環，否則績效數字沒有代表性。
