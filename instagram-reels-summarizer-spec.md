# Instagram Reels 影片自動摘要系統 開發規格

## 1. 概述

- **功能描述**: 透過 Telegram Bot 接收 Instagram Reels / 圖文貼文 / Threads 連結，自動下載影片與圖片、轉錄語音、生成摘要，並同步至 Roam Research 與 NotebookLM
- **開發背景**: 簡化社群媒體內容的擷取與知識管理流程，實現自動化筆記整理
- **目標使用者**: 個人使用
- **特點**: 完全免費，使用本地 AI 模型，無需任何 API Key

## 2. 功能需求

### 2.1 核心功能

| 功能項目 | 說明 | 優先級 |
|---------|------|--------|
| Telegram Bot 接收連結 | 接收 Instagram Reels / 圖文貼文 / Threads 連結 | 高 |
| Instagram Reels 下載 | 解析連結並下載 Reels 短影片 (yt-dlp) | 高 |
| Instagram 圖文貼文下載 | 下載多圖 Carousel 貼文 (Instaloader) | 高 |
| Threads 貼文下載 | 下載 Threads 貼文與串文（Googlebot SSR 自動偵測作者連續貼文） | 高 |
| 語音轉逐字稿 | 使用 faster-whisper 本地模型將影片音訊轉為文字 | 高 |
| AI 摘要生成 | 多後端支援：Ollama（本地）/ Claude Code CLI / GitHub Copilot CLI | 高 |
| 視覺分析 | 使用 Gemma3 / MiniCPM-V 分析影片畫面內容（動態 8-10 幀、並行處理） | 中 |
| 工具與技能提取 | 從摘要中提取工具、技能、步驟等清單（必填欄位） | 中 |
| Telegram 回覆 | 回傳摘要、重點、畫面觀察、Roam 與 NotebookLM 連結 | 高 |
| Roam Research 同步 | 儲存本地 Markdown + Claude Code MCP 自動同步 | 高 |
| NotebookLM 同步 | 透過 Chrome CDP + Playwright 自動上傳摘要與媒體到 NotebookLM | 中 |
| 失敗重試機制 | 記錄失敗連結並自動定時重試 | 中 |

### 2.2 使用流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                          使用者操作流程                              │
└─────────────────────────────────────────────────────────────────────┘

1. 使用者在手機 Instagram / Threads App 看到感興趣的內容
2. 點擊分享 → 選擇 Telegram → 發送給 Bot
3. Bot 回覆「處理中...」
4. 等待處理完成
5. Bot 回覆：
   - 摘要段落
   - 條列式重點
   - Roam Research 頁面連結
   - NotebookLM 連結（如啟用）
6. 內容同步出現在 Roam Research 與 NotebookLM

┌─────────────────────────────────────────────────────────────────────┐
│                          系統處理流程                                │
└─────────────────────────────────────────────────────────────────────┘

┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Telegram │───▶│ 下載器       │───▶│ faster-whisper │───▶│ Gemma3       │
│   Bot    │    │ yt-dlp /      │    │ 本地轉錄       │    │ 視覺分析     │
└──────────┘    │ Instaloader  │    └──────────────┘    └──────────────┘
                └──────────────┘                                  │
                                                                      ▼
                                                               ┌──────────────┐
                                                               │ Ollama/Qwen  │
                                                               │ 整合摘要     │
                                                               └──────────────┘
                                                                      │
                     ┌──────────────┬───────────────────┤
                     ▼              ▼                   ▼
              ┌──────────┐  ┌──────────┐  ┌────────────────┐
              │ Telegram │  │ Roam     │  │ NotebookLM     │
              │ 回覆     │  │ Research │  │ (Chrome CDP)   │
              └──────────┘  └──────────┘  └────────────────┘
```

### 2.2.1 Threads 下載流程（三層降級）

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Threads 下載降級策略                               │
└──────────────────────────────────────────────────────────────────────┘

                    ┌──────────────┐
                    │ Threads URL  │
                    └──────┬───────┘
                           ▼
                  ┌─────────────────┐
              ┌───│ MetaThreads API │───┐
              │   └─────────────────┘   │
           成功│                        │失敗 (login_required)
              ▼                         ▼
     ┌──────────────┐        ┌──────────────────┐
     │ 單則貼文結果  │        │ Googlebot SSR    │
     └───────┬──────┘        │ (User-Agent 偽裝) │
             │               └────────┬─────────┘
             │                        │
             │              ┌─────────┴──────────┐
             │           成功│                    │失敗
             │              ▼                     ▼
             │    ┌──────────────────┐  ┌───────────────┐
             │    │ 解析 thread_items│  │ Web Scraping  │
             │    │ 過濾作者貼文     │  │ (傳統備用方案) │
             │    └────────┬────────┘  └───────────────┘
             │             │
             │    ┌────────┴────────┐
             │    │ 1則=single_post │
             │    │ N則=thread      │
             │    └─────────────────┘
             │
             ▼
   ┌───────────────────┐
   │ 也嘗試 SSR 檢查   │  ← API 成功時仍用 SSR 確認是否為串文
   │ 是否有更多串文貼文 │
   └───────────────────┘
```

**Googlebot SSR 原理**：使用 `Googlebot/2.1` User-Agent 請求 Threads 頁面，Meta 會回傳 server-side rendered HTML，其中包含完整的 JSON 資料（含 `thread_items` 陣列）。系統從中解析所有貼文，並過濾只保留原作者的貼文（排除他人回覆），實現串文自動偵測。

### 2.3 例外處理

| 情境 | 處理方式 |
|------|---------|
| URL 已處理過 | 查詢資料庫，回傳「📝 此連結已於 YYYY-MM-DD HH:MM 處理過」 |
| Instagram 連結無效 | 回傳錯誤訊息：「無法解析此連結，請確認是否為有效的 Instagram Reels 連結」 |
| 影片下載失敗 | 記錄連結至失敗清單，回傳「下載失敗，已排入重試佇列」 |
| 語音轉錄失敗 | 記錄連結至失敗清單，回傳「轉錄失敗，已排入重試佇列」 |
| 影片無語音/靜音 | 自動改用視覺分析結果作為主要內容來源 |
| Ollama 摘要失敗 | 記錄連結至失敗清單，回傳「摘要生成失敗，已排入重試佇列」 |
| Roam Research 同步失敗 | 先回傳 Telegram 摘要，記錄同步失敗待重試 |
| 重試 3 次仍失敗 | 回傳「處理失敗已達重試上限，請手動重新分享」 |
| 網路超時 | 使用安全訊息編輯（_safe_edit_message），超時不中斷處理流程 |

## 3. 技術規格

### 3.1 技術堆疊

| 項目 | 技術選擇 |
|------|---------|
| 程式語言 | Python 3.10+ |
| Web 框架 | FastAPI |
| Telegram Bot | python-telegram-bot 套件 |
| Instagram Reels 下載 | yt-dlp + cookies.txt 認證 |
| Instagram 貼文下載 | Instaloader |
| Threads 下載 | Threads API + Googlebot SSR + Web Scraping（三層降級） |
| 語音轉錄 | faster-whisper 本地模型 |
| 摘要生成 | Ollama（本地）/ Claude Code CLI / GitHub Copilot CLI |
| 視覺分析 | Ollama + Gemma3 / MiniCPM-V 本地模型 |
| Roam 整合 | 本地 Markdown 檔案儲存 + Claude Code MCP 同步 |
| NotebookLM 整合 | Playwright + Chrome CDP 自動化上傳 |
| 任務排程 | APScheduler |
| 部署方式 | 本地端 + Cloudflare Tunnel |

### 3.2 系統架構

```
┌─────────────────────────────────────────────────────────────────┐
│                         本地端伺服器                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │  Telegram   │    │   下載器    │    │faster-whisper│        │
│  │  Bot API    │───▶│ yt-dlp /   │───▶│ 本地轉錄      │        │
│  └─────────────┘    │ Instaloader│    └─────────────┘        │
│         │          └─────────────┘           │               │
│         │                              ┌───────┴───────┐       │
│         │                              ▼               ▼       │
│         │                      ┌─────────────┐ ┌─────────────┐│
│         │                      │ Gemma3      │ │ Ollama +    ││
│         │                      │ 視覺分析    │─▶│ Qwen3       ││
│         │                      └─────────────┘ └─────────────┘│
│         │                                      │               │
│         ▼                                      ▼               │
│  ┌─────────────┐                       ┌─────────────┐        │
│  │  回覆訊息   │◀──────────────────────│ Markdown  │        │
│  └─────────────┘                       │ 本地儲存    │        │
│                                       └──────┬──────┘        │
│                                              │                  │
│         ┌────────────────┼───────────────┐             │
│         ▼                ▼               ▼             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐        │
│  │ NotebookLM  │ │ Roam        │ │   排程器    │        │
│  │ (Chrome CDP)│ │ Research    │ │  (每小時)   │        │
│  └─────────────┘ └─────────────┘ └─────────────┘        │
│                                                                 │
│  ┌─────────────┐                                              │
│  │  失敗記錄   │                                              │
│  │  (SQLite)   │                                              │
│  └─────────────┘                                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Cloudflare Tunnel
                              ▼
                    ┌─────────────────┐
                    │    Internet     │
                    └─────────────────┘
```

### 3.3 資料規格

#### 失敗記錄資料表 (SQLite)

| 欄位名稱 | 型別 | 說明 |
|---------|------|------|
| id | INTEGER | 主鍵，自動遞增 |
| instagram_url | TEXT | Instagram Reels 原始連結 |
| telegram_chat_id | TEXT | Telegram 聊天室 ID，用於重試後回覆 |
| error_type | TEXT | 錯誤類型（download/transcribe/summarize/sync） |
| error_message | TEXT | 錯誤訊息 |
| retry_count | INTEGER | 已重試次數（預設 0） |
| created_at | DATETIME | 建立時間 |
| last_retry_at | DATETIME | 最後重試時間 |
| status | TEXT | 狀態（pending/success/abandoned） |

#### 已處理 URL 記錄資料表 (SQLite)

| 欄位名稱 | 型別 | 說明 |
|---------|------|------|
| id | INTEGER | 主鍵，自動遞增 |
| url | TEXT | 已處理的 URL（唯一索引） |
| url_type | TEXT | URL 類型（instagram_reel/instagram_post/threads） |
| title | TEXT | 影片/貼文標題 |
| telegram_chat_id | TEXT | Telegram 聊天室 ID |
| note_path | TEXT | 筆記檔案路徑（可選） |
| processed_at | DATETIME | 處理完成時間 |

> **重複檢查機制**：收到 URL 時先查詢資料庫，若已處理過則回覆「📝 此連結已於 YYYY-MM-DD HH:MM 處理過」，避免重複處理。

#### NotebookLM Notebook 記錄資料表 (SQLite)

| 欄位名稱 | 型別 | 說明 |
|---------|------|------|
| id | INTEGER | 主鍵，自動遞增 |
| date | TEXT(10) | 日期（YYYY-MM-DD），唯一索引 |
| notebook_url | TEXT | Notebook URL |
| notebook_title | TEXT | Notebook 標題 |
| source_count | INTEGER | 已上傳的 source 數量 |
| created_at | DATETIME | 建立時間 |
| updated_at | DATETIME | 最後更新時間 |

> **每日 Notebook 管理**：每日自動建立一個 Notebook，所有當日的摘要與媒體都上傳到同一個 Notebook 中。若 Notebook 被刪除，系統會自動偵測並重新建立。

#### 摘要輸出格式

```json
{
  "instagram_url": "https://www.instagram.com/reel/xxx",
  "video_title": "影片標題（若有）",
  "transcript": "完整逐字稿內容...",
  "summary": "一段話的摘要內容...",
  "bullet_points": [
    "重點一",
    "重點二",
    "重點三"
  ],
  "tools_and_skills": [
    "工具/技能一",
    "工具/技能二"
  ],
  "visual_observations": [
    "畫面觀察一",
    "畫面觀察二"
  ],
  "visual_analysis": "完整影像分析內容（各時間點的畫面描述）...",
  "language_detected": "zh-TW",
  "processed_at": "2026-01-20T10:30:00+08:00"
}
```

### 3.4 Roam Research 頁面格式（標準 Markdown）

```markdown
# IG Reels - 2026-01-20 - 影片標題

#Instagram摘要

## 來源資訊

- **原始連結**: [Instagram Reels](https://www.instagram.com/reel/xxx)
- **處理時間**: 2026-01-20 10:30:00

## 摘要

這是一段話的影片摘要內容，概述影片的主要主題和核心觀點...

## 重點整理

- 重點一
- 重點二
- 重點三

## 工具與技能

- 工具/技能一
- 工具/技能二

## 畫面觀察

- 畫面觀察一
- 畫面觀察二

## 影像分析

[0秒] 畫面描述...
[2秒] 畫面描述...

## 逐字稿

> 完整的語音轉文字內容（有語音時使用引用區塊）

*或無語音時：*

*此影片無語音內容，以下為畫面描述*

[0秒] 畫面描述...
[2秒] 畫面描述...
```

### 3.5 Telegram Bot 回覆格式

```
✅ 摘要完成！

📝 摘要
這是一段話的影片摘要內容，概述影片的主要主題和核心觀點...

📌 重點
• 重點一
• 重點二
• 重點三

� 畫面觀察
• 畫面觀察一
• 畫面觀察二

�📎 Roam Research
https://roamresearch.com/#/app/your-graph/page/xxx

🔗 原始連結
https://www.instagram.com/reel/xxx
```

### 3.6 Prompt 與範例筆記系統

為確保生成的筆記格式一致，系統使用外部 Prompt 模板和範例筆記：

#### 資料夾結構

```
app/prompts/
├── examples/           # 範例筆記
│   ├── audio/         # 有語音的範例
│   │   ├── mavenhq.md
│   │   └── sundaskhalidd.md
│   └── visual_only/   # 無語音的範例
│       └── she_explores_data.md
├── system/            # System Prompt
│   └── note_system.txt
└── templates/         # 使用者 Prompt 模板
    └── note_prompt.txt
```

#### 運作機制

1. 根據影片是否有語音（`has_audio`），選擇對應類別的隨機範例
2. 將範例插入到 prompt 模板的 `{example_note}` 區塊
3. 三種後端（Ollama / Claude CLI / Copilot CLI）皆使用相同的外部模板

### 3.7 服務整合需求

| 服務 | 用途 | 需要的認證 |
|------|------|-----------|
| Telegram Bot API | 接收訊息與回覆 | Bot Token |
| Instagram | 下載 Reels 影片 | cookies.txt（從瀏覽器匯出） |
| faster-whisper | 本地語音轉錄 | 無（本地模型） |
| Ollama + Qwen3 | 本地摘要生成（預設） | 無（本地模型） |
| Claude Code CLI | 雲端摘要生成（可選） | Claude Pro 訂閱 |
| GitHub Copilot CLI | 雲端摘要生成（可選） | Copilot 訂閱 |
| Ollama + Gemma3 / MiniCPM-V | 本地視覺分析 | 無（本地模型） |
| Roam Research | 本地 Markdown 儲存 + Claude Code MCP 同步 | 無 |
| NotebookLM | 自動上傳摘要與媒體 (Chrome CDP) | Google 帳號登入 |

#### Instagram 認證設定

由於 Instagram 需要登入才能下載影片，需要從瀏覽器匯出 cookies：

1. 在瀏覽器（Chrome/Edge）登入 Instagram
2. 安裝「Get cookies.txt LOCALLY」擴充套件
3. 前往 instagram.com，點擊擴充套件匯出 cookies
4. 將檔案儲存為專案根目錄的 `cookies.txt`
5. 確認檔案包含 `sessionid` cookie

### 3.8 環境變數設定

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ALLOWED_CHAT_IDS=your_chat_id

# Whisper 本地模型設定
WHISPER_MODEL_SIZE=base  # tiny, base, small, medium, large-v2, large-v3
WHISPER_DEVICE=cpu       # cpu 或 cuda

# 摘要服務選擇
SUMMARIZER_BACKEND=ollama  # ollama（本地）、claude（Claude Code CLI）或 copilot（GitHub Copilot CLI）
CLAUDE_MODEL=sonnet        # sonnet, opus, haiku（僅 claude backend 使用）
COPILOT_MODEL=claude-opus-4.5  # gpt-4o, claude-sonnet-4.5, claude-opus-4.5（僅 copilot backend 使用）

# Ollama 本地 LLM 設定（SUMMARIZER_BACKEND=ollama 時使用）
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3:8b    # 可選: qwen2.5:7b, qwen2.5:14b
OLLAMA_VISION_MODEL=gemma3:4b  # 可選: minicpm-v

# Roam Research
ROAM_GRAPH_NAME=your_graph_name

# Webhook 設定 (Cloudflare Tunnel URL，不含 /webhook/telegram)
WEBHOOK_URL=https://your-tunnel-url.trycloudflare.com

# Claude Code 同步設定 (自動同步 Markdown 到 Roam Research)
CLAUDE_CODE_SYNC_ENABLED=false  # true 啟用 / false 停用

# NotebookLM 自動同步（可選，透過 Chrome CDP + Playwright）
NOTEBOOKLM_ENABLED=false          # true 啟用 / false 停用
NOTEBOOKLM_CDP_URL=http://localhost:9222  # Chrome CDP 連線地址
NOTEBOOKLM_UPLOAD_VIDEO=true      # 是否上傳影片/圖片為 source

# Threads 設定（可選）
THREADS_ENABLED=true             # 是否啟用 Threads 支援
THREADS_FETCH_REPLIES=true       # 是否拓取回覆串
THREADS_MAX_REPLIES=50           # 最大回覆數

# 系統設定
RETRY_ENABLED=true           # 是否啟用失敗重試功能
RETRY_INTERVAL_HOURS=1
MAX_RETRY_COUNT=3
TEMP_VIDEO_DIR=./temp_videos
```

## 4. 約束條件

### 4.1 效能要求

| 項目 | 要求 |
|------|------|
| 單一影片處理時間 | 60 秒內完成（不含網路延遲） |
| Reels 最大長度支援 | 90 秒（Instagram Reels 上限） |
| 並行處理 | 一次處理一個請求（個人使用，無需並行） |

### 4.2 相容性

| 項目 | 要求 |
|------|------|
| Instagram 連結格式 | 支援 `instagram.com/reel/xxx`、`instagram.com/p/xxx` 與 `threads.net/...` |
| 語言支援 | 中文（zh）、英文（en） |
| 作業系統 | Windows / macOS / Linux |

### 4.3 安全性

| 項目 | 要求 |
|------|------|
| 本地運行 | 所有 AI 處理在本地執行，資料不傳送至雲端 |
| Telegram 驗證 | 僅回應特定 chat_id（個人使用） |
| 暫存檔案 | 處理完成後立即刪除 |

## 5. 驗收標準

### 5.1 功能驗收

- [x] 能成功接收 Telegram 傳來的 Instagram Reels / 圖文貼文 / Threads 連結
- [x] 能正確下載 Instagram Reels 影片 (yt-dlp)
- [x] 能正確下載 Instagram 多圖貼文 (Instaloader)
- [x] 能正確下載 Threads 貼文含回覆串
- [x] 能正確偵測並下載 Threads 串文（作者多則連續貼文，排除他人回覆）
- [x] 能透過 faster-whisper 本地模型將影片語音轉為文字（支援中英文）
- [x] 能透過 Gemma3 / MiniCPM-V 本地模型分析影片畫面內容
- [x] 能透過 Ollama + Qwen3 本地模型生成中文摘要與條列重點
- [x] Telegram Bot 正確回覆摘要、重點、畫面觀察、Roam 與 NotebookLM 連結
- [x] 成功儲存 Markdown 檔案供匯入 Roam Research
- [x] 自動上傳摘要與媒體到 NotebookLM（文字 + 圖片批次上傳）
- [x] 頁面正確標記 `#Instagram摘要` hashtag
- [x] 失敗時正確記錄並顯示提示訊息
- [x] 每小時自動重試失敗的任務
- [x] 重試 3 次後正確標記為放棄並通知使用者
- [x] 處理完成後正確刪除暫存影片檔案

### 5.2 整合驗收

- [x] Cloudflare Tunnel 正確暴露本地服務
- [x] 手機 Instagram 分享至 Telegram Bot 流程順暢
- [x] 端對端流程可在 2 分鐘內完成

## 6. 建議的專案結構

```
instagram-reels-summarizer/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 設定與環境變數
│   ├── bot/
│   │   ├── __init__.py
│   │   └── telegram_handler.py # Telegram Bot 處理
│   ├── services/
│   │   ├── __init__.py
│   │   ├── downloader.py       # Instagram 下載 (yt-dlp + Instaloader)
│   │   ├── threads_downloader.py # Threads 貼文/串文下載（API + Googlebot SSR + Web Scraping）
│   │   ├── download_logger.py  # 下載記錄
│   │   ├── transcriber.py      # 本地 Whisper 轉錄 (faster-whisper)
│   │   ├── summarizer.py       # 本地 LLM 摘要 (Ollama + Qwen3)
│   │   ├── claude_summarizer.py  # Claude Code CLI 摘要
│   │   ├── copilot_summarizer.py # GitHub Copilot CLI 摘要
│   │   ├── summarizer_factory.py # 摘要服務工廠（自動選擇後端）
│   │   ├── visual_analyzer.py  # 視覺分析 (Ollama + Gemma3/MiniCPM-V)
│   │   ├── prompt_loader.py    # Prompt 模板載入器
│   │   ├── roam_sync.py        # Roam Research Markdown 儲存
│   │   └── notebooklm_sync.py  # NotebookLM 自動上傳 (Chrome CDP)
│   ├── prompts/                # AI Prompt 模板
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── retry_job.py        # 重試排程
│   └── database/
│       ├── __init__.py
│       └── models.py           # SQLite 模型
├── scripts/
│   ├── start_chrome_cdp.bat    # 啟動 Chrome CDP
│   └── test_*.py               # 各模組測試腳本
├── tests/
│   └── ...
├── .env.example
├── requirements.txt
├── start.ps1                   # 一鍵啟動腳本 (PowerShell)
├── start.bat                   # 一鍵啟動腳本 (CMD)
└── README.md
```

## 7. 附註

### 7.1 已知限制

- Instagram 可能會更改網頁結構，影響下載功能，需定期更新 yt-dlp
- 部分 Reels 可能有版權保護無法下載
- faster-whisper 對於背景音樂較大的影片，轉錄品質可能較差
- 本地 LLM 摘要品質取決於模型大小，建議使用 7B 以上模型
- 首次執行需下載模型，需要額外時間

### 7.2 系統需求

| 項目 | 最低需求 | 建議配置 |
|------|---------|----------|
| RAM | 8 GB | 16 GB |
| 磁碟空間 | 10 GB | 20 GB |
| GPU | 無（可用 CPU） | NVIDIA GPU (選用) |

### 7.3 未來擴展建議

- 支援 TikTok、YouTube Shorts 等其他短影片平台
- 加入影片分類自動標籤功能
- 支援多語言摘要輸出
- 建立 Web Dashboard 查看處理歷史
- 支援 GPU 加速提升處理速度
- NotebookLM Audio Overview 自動生成
- 整合 Roam Research API（待官方開放）

---

*本文件由需求分析師產出，可直接供 AI 進行開發*  
*產出時間: 2026-01-20*  
*更新: 2026-01-21 新增視覺分析功能 (MiniCPM-V)*  
*更新: 2026-01-21 新增工具與技能提取、影像分析區塊、重試開關設定*  
*更新: 2026-01-21 無語音影片自動使用視覺分析*  
*更新: 2026-01-21 改用本地 AI 模型 (faster-whisper + Ollama)*  
*更新: 2026-01-21 Instagram 認證改用 cookies.txt 檔案*  
*更新: 2026-01-21 Webhook 自動設定與啟動時清空舊訊息*  
*更新: 2026-01-21 筆記格式改用標準 Markdown（## 標題）*  
*更新: 2026-01-21 背景處理訊息避免 Telegram Webhook 超時*  
*更新: 2026-01-21 訊息 ID 去重防止重複處理*
*更新: 2026-01-21 LLM 直接生成 Markdown 筆記（智能格式適應內容）*
*更新: 2026-01-21 強化繁體中文輸出要求*
*更新: 2026-01-21 工具與技能改為必填欄位*
*更新: 2026-01-21 動態幀數（8-10 幀）根據影片長度調整*
*更新: 2026-01-21 幀分析並行處理（預設 2 並行）*
*更新: 2026-01-21 Claude Code MCP 自動同步到 Roam Research*
*更新: 2026-02-04 新增多後端摘要服務支援（Ollama / Claude Code CLI / GitHub Copilot CLI）*
*更新: 2026-02-10 新增 Instagram 圖文貼文支援、Threads 貼文支援*
*更新: 2026-02-16 新增 NotebookLM 自動同步（Chrome CDP + Playwright）*
*更新: 2026-02-17 NotebookLM 多圖批次上傳、頁面跳轉修復、更新預設模型為 Qwen3 + Gemma3*
*更新: 2026-02-19 Threads 串文支援（Googlebot SSR 自動偵測作者連續貼文、過濾他人回覆、per-post 媒體處理）*
