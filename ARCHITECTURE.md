# 南山業績 LINE Bot — 整體串接流程

## 系統組成

| 角色 | 工具 | 說明 |
|---|---|---|
| 資料來源 | Gmail（IMAP） | 業務部寄送 Excel 報表到 Gmail 信箱 |
| 資料抓取 | `fetch_gmail.py` | 用 IMAP 登入 Gmail，依信件主旨判斷報表類型，解析 Excel，更新 `data/performance.json` |
| 排程觸發 | GitHub Actions（主要）+ cron-job.org（備援） | 平日台灣時間 07:30～17:30，每小時觸發一次 |
| CI/CD | `.github/workflows/update_performance.yml` | 安裝套件 → 跑 `fetch_gmail.py` → commit/push `performance.json` → 寄通知信 |
| 通知信 | `send_notify.py` | 執行完成後寄信給 c5268326@gmail.com，回報執行時間、資料時間、廣播狀態 |
| LINE Bot | `app.py`（Flask, 部署在 Render） | 接收 LINE webhook 訊息，依關鍵字回覆業績資料；早上第一次更新會主動廣播 |
| 資料儲存 | `data/performance.json` | 存放本日/本月業績數字，commit 進 repo 當資料庫用 |

## 整體流程圖

```
Gmail 信箱（業務部寄送 Excel 報表）
        │
        │  IMAP 登入抓信
        ▼
┌─────────────────────────┐
│   fetch_gmail.py          │
│  1. 依信件主旨判斷報表類型 │
│     ・「速報」      → 日報表 │
│     ・「每日業績追蹤報表」→ 月報表 │
│  2. 解析 Excel（openpyxl/xlrd）│
│  3. 月報表 + 日報表 合併計算 │
│     （金額相加、達成率重算）  │
│  4. 寫入 data/performance.json │
│  5. 判斷今天是否已廣播過      │
│     （只有早上 07:30 第一次廣播）│
└─────────────────────────┘
        │
        ▼
   git commit & push（performance.json 進 repo）
        │
        ▼
┌─────────────────────────┐
│   send_notify.py          │
│  寄信給 c5268326@gmail.com │
│  （執行時間／資料時間／廣播狀態）│
└─────────────────────────┘


【觸發端，兩條保險】
GitHub Actions schedule（主要）──┐
   cron: 07:30, 08:30...17:30   │
                                  ├──→ workflow_dispatch API
cron-job.org（備援，外部排程）──┘     （POST .../actions/.../dispatches）
   因 GitHub schedule 偶爾不準時觸發


【使用者互動端】
LINE 使用者 傳訊息（例如「本日業績」）
        │
        ▼
┌─────────────────────────┐
│   app.py（Flask, Render）  │
│  讀取 data/performance.json │
│  依關鍵字組成 Flex/文字訊息  │
│  回覆給使用者 / 群組         │
└─────────────────────────┘
```

## 各檔案職責

- **`fetch_gmail.py`**
  - `_decode_subject()`：解析郵件主旨（含中文編碼）
  - `_get_excel_attachment()`：取得信件中的 Excel 附件
  - `get_latest_excels()`：依主旨關鍵字分類「日報表／月報表」
  - `_combine_vals()`：月報表金額 + 日報表金額相加，並用「月報表金額 ÷ 月報表達成率」反推目標值，重新計算合併後達成率
  - `update_performance()`：寫入 `performance.json`
  - `broadcast_performance()`：呼叫 LINE Broadcast API 推播，並寫入 `last_broadcast_date` 避免重複推播
  - `main()`：整支腳本進入點，GitHub Actions 會執行 `python fetch_gmail.py`

- **`app.py`**
  - Flask webhook，接收 LINE 訊息事件
  - 依關鍵字（本日業績、本月業績、排行榜等）組成回覆
  - 部署在 Render，是 24 小時常駐服務（跟 GitHub Actions 排程是分開的兩個系統）

- **`send_notify.py`**
  - 獨立腳本，讀 `performance.json` 組信件內容，用 Gmail SMTP 寄出
  - 取代原本寫在 workflow 裡的 heredoc inline Python（heredoc 曾經造成 YAML 解析失敗，導致排程完全失效）

- **`.github/workflows/update_performance.yml`**
  - `on.workflow_dispatch`：允許手動觸發
  - `on.schedule`：兩條 cron，涵蓋台灣時間 07:30～17:30 平日每小時
  - 三個 steps：抓資料更新 → commit push → 寄通知信

- **`data/performance.json`**
  - 欄位：`updated_at`（資料時間）、`last_broadcast_date`（上次廣播日期）、`today`/`regions`（業績數字）
  - 既是資料庫也是「執行成功與否」的證據（updated_at 沒更新就代表沒抓到新資料）

## 已知問題與因應

GitHub Actions 的 `schedule` 觸發**不保證準時**，遇到平台忙碌時可能被跳過、且沒有任何紀錄可查。因此額外用 **cron-job.org** 外部服務，定時呼叫 GitHub 的 `workflow_dispatch` API（`POST /repos/c5268326/line-bot-test/actions/workflows/update_performance.yml/dispatches`）當備援，確保排程不靠 GitHub 單一系統。
