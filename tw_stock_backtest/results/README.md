# 回測結果（由 GitHub Actions 自動產生，請勿手動編輯）

這個目錄由 `.github/workflows/tw_stock_backtest.yml` 自動寫入，每次執行後會覆蓋對應
子目錄：

```
results/
├── default/      # config.BacktestConfig() 預設參數
├── long_term/     # config.long_term_config()（長期投資策略）
└── short_term/    # config.short_term_config()（半年內短期投資策略）
```

每個子目錄底下有：
- `report.json`　— 結構化績效指標（CAGR、Sharpe、MDD、勝率、對比基準…）
- `equity_curve.csv`　— 每日權益曲線
- `trades.csv`　— 完整交易紀錄（含停損 / 換股出場原因）

## 怎麼觸發

1. Repo 頁面 → **Actions** → 選「台股多因子回測」→ **Run workflow**，可自訂資料源
   （finmind / yfinance / twse）與回測區間，留空則用各策略預設區間。
2. 也會在每週一台灣時間早上 9 點自動跑一次，不需要手動觸發。
3.（建議）到 repo 的 **Settings → Secrets and variables → Actions** 新增
   `FINMIND_TOKEN`（到 https://finmindtrade.com/ 免費註冊取得），可以提高 API 呼叫額度；
   不設定也能跑，只是額度較低。

## 提醒

這些數字是 GitHub Actions runner 在**有網路權限的環境**上，用真實資料跑出來的結果
（不是合成資料），但仍然是「回測」而非「保證未來報酬」，使用前請務必讀過
`../RESEARCH.md` 與 `../README.md`「已知限制」一節。
