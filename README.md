# Instagram Reels 影片自動摘要系統

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20AI-orange.svg)](https://ollama.com/)
[![License](https://img.shields.io/badge/License-Personal%20Use-lightgrey.svg)](#授權)

> 透過 Telegram Bot 接收 Instagram Reels / 圖文貼文 / Threads 連結，自動下載影片與圖片、轉錄語音、生成摘要，並同步至 Roam Research 與 NotebookLM。完全免費，使用本地 AI 模型，無需任何 API Key。

---

## 目錄

- [功能特色](#功能特色)
- [技術堆疊](#技術堆疊)
- [系統架構](#系統架構)
- [系統需求](#系統需求)
- [安裝步驟](#安裝步驟)
- [專案結構](#專案結構)
- [啟動服務](#啟動服務)
- [使用方式](#使用方式)
- [API 端點](#api-端點)
- [開發工作流程](#開發工作流程)
- [編碼規範](#編碼規範)
- [測試](#測試)
- [故障排除](#故障排除)
- [貢獻指南](#貢獻指南)
- [授權](#授權)

---

## 功能特色

| 功能 | 說明 | 技術 |
|------|------|------|
| 📱 **Telegram Bot 整合** | 直接分享連結即可處理 | python-telegram-bot |
| 🎬 **Instagram Reels 下載** | 下載 Reels 影片並轉錄 | yt-dlp + cookies.txt |
| 🖼️ **Instagram 圖文貼文** | 下載多圖 Carousel 貼文 | Instaloader |
| 🧵 **Threads 支援** | 下載 Threads 貼文與串文（自動偵測作者連續貼文） | Googlebot SSR + Threads API |
| 🎤 **語音轉錄** | 本地語音轉文字（免費、無需 API Key） | faster-whisper |
| 👁️ **視覺分析** | 分析影片畫面（動態 8-10 幀、並行處理） | Gemma3 / MiniCPM-V |
| 📝 **AI 摘要** | 整合語音與畫面生成繁體中文摘要 | Ollama / Claude CLI / Copilot CLI |
| 📚 **Roam Research 同步** | 本地備份 + 可選自動同步至 Roam | Claude Code + Roam MCP |
| 🤖 **NotebookLM 同步** | 自動上傳摘要與媒體到 NotebookLM | Playwright + Chrome CDP |
| 🔄 **失敗重試** | 自動重試失敗的任務（最多 3 次） | APScheduler |
| ⚡ **並行處理** | 幀分析支援並行加速 | asyncio |
| 🔒 **URL 重複檢查** | 避免重複處理同一連結，提示已處理過 | SQLite |
| 🌐 **網路容錯** | 網路超時不中斷處理，自動重試 | HTTPXRequest |

### 💡 彈性選擇：本地或雲端

**本地模式（完全免費，無需 API Key）：**

- **語音轉錄**：faster-whisper（本地運行）
- **視覺分析**：Gemma3 / MiniCPM-V（透過 Ollama 本地運行）
- **摘要生成**：Ollama + Qwen3（本地運行）

**雲端模式（需訂閱）：**

- **Claude Code CLI**：使用 Claude Sonnet/Opus（需 Claude Pro 訂閱）
- **GitHub Copilot CLI**：使用 GPT-4o/Claude（需 Copilot 訂閱）

### 🔗 Claude Code MCP 同步（可選）

透過 Claude Code CLI 和 Roam Research MCP，可實現摘要自動同步到 Roam Research：

- 摘要完成後自動儲存 Markdown 到本地 `roam_backup/` 資料夾
- 若啟用同步，會呼叫 Claude Code 使用 Roam MCP 建立頁面
- 即使同步失敗，本地備份仍會保留

> 詳細設定請參考 [安裝步驟 - 設定 Claude Code MCP](#安裝步驟)

### 🤖 NotebookLM 自動同步（可選）

透過 Chrome CDP 連線 + Playwright 自動化，將摘要與媒體上傳到 Google NotebookLM：

- 每日自動建立 Notebook（以日期命名）
- 摘要文字以「複製的文字」方式上傳為 source
- 影片 / 圖片批次上傳為檔案 source（一次多選）
- 使用獨立 Chrome Profile，不干擾日常瀏覽器
- 自動偵測 Notebook 是否被刪除並重新建立

> 詳細設定請參考 [安裝步驟 - 設定 NotebookLM 同步](#安裝步驟)

---

## 技術堆疊

| 類別 | 技術 | 版本 |
|------|------|------|
| **程式語言** | Python | 3.10+ |
| **Web 框架** | FastAPI | 0.109+ |
| **Telegram Bot** | python-telegram-bot | 20.7+ |
| **影片下載** | yt-dlp | 2024.12+ |
| **語音轉錄** | faster-whisper | 1.0+ |
| **摘要生成** | Ollama / Claude Code CLI / Copilot CLI | Latest |
| **視覺分析** | Ollama + Gemma3 / MiniCPM-V | Latest |
| **資料庫** | SQLite + SQLAlchemy | 2.0+ |
| **非同步資料庫** | aiosqlite | 0.19+ |
| **任務排程** | APScheduler | 3.10+ |
| **HTTP 客戶端** | httpx | 0.25+ |
| **瀏覽器自動化** | Playwright | 1.40+ |
| **設定管理** | pydantic-settings | 2.2+ |
| **反向代理** | Cloudflare Tunnel | Latest |

---

## 系統架構

```
┌──────────────────────────────────────────────────────────────────┐
│                         本地端伺服器                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌───────────┐    ┌───────────┐    ┌─────────────┐              │
│  │ Telegram  │───▶│  下載器   │───▶│faster-whisper│              │
│  │  Bot API  │    │ yt-dlp /  │    │  本地轉錄   │              │
│  └───────────┘    │Instaloader│    └─────────────┘              │
│        │          └───────────┘           │                      │
│        │                         ┌───────┴───────┐               │
│        │                         ▼               ▼               │
│        │                 ┌─────────────┐ ┌─────────────┐        │
│        │                 │   Gemma3    │ │ Ollama +    │        │
│        │                 │  視覺分析   │─▶│ Qwen3       │        │
│        │                 └─────────────┘ └─────────────┘        │
│        │                                        │                │
│        ▼                                        ▼                │
│  ┌───────────┐                         ┌─────────────┐          │
│  │ 回覆訊息  │◀────────────────────────│  Markdown   │          │
│  └───────────┘                         │  本地儲存   │          │
│        │                               └──────┬──────┘          │
│        │                                      │                  │
│        │         ┌─────────────┐  ┌───────────┴───┐             │
│        │         │ NotebookLM  │  │ Roam Research │             │
│        │         │ (Chrome CDP)│  │ (Claude MCP)  │             │
│        │         └─────────────┘  └───────────────┘             │
│        │                                                         │
│  ┌───────────┐    ┌───────────┐                                 │
│  │ 失敗記錄  │◀───│  排程器   │                                 │
│  │ (SQLite)  │───▶│ (每小時)  │                                 │
│  └───────────┘    └───────────┘                                 │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
                             │
                             │ Cloudflare Tunnel
                             ▼
                   ┌──────────────────┐
                   │     Internet     │
                   └──────────────────┘
```

---

## 系統需求

| 項目 | 需求 |
|------|------|
| **作業系統** | Windows / macOS / Linux |
| **Python** | 3.10 或更高版本 |
| **FFmpeg** | 用於音訊處理 |
| **Ollama** | 本地 LLM 運行環境 |
| **Cloudflare Tunnel** | 用於 Telegram Webhook |
| **RAM** | 建議 8GB 以上 |
| **GPU（可選）** | NVIDIA GPU 可加速轉錄 |
| **Google Chrome** | NotebookLM 同步需要（可選） |

---

---

## 安裝步驟

### 快速開始

```bash
# 1. 複製專案
git clone <repository-url>
cd instagram-reels-summarizer

# 2. 建立虛擬環境並安裝依賴
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env 填入你的設定

# 4. 啟動服務
python -m app.main
```

### 詳細安裝說明

<details>
<summary><strong>1. 建立虛擬環境</strong></summary>

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

</details>

<details>
<summary><strong>2. 安裝依賴</strong></summary>

```bash
pip install -r requirements.txt
```

</details>

<details>
<summary><strong>3. 安裝 FFmpeg</strong></summary>

**Windows:**
```bash
winget install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux:**
```bash
sudo apt update && sudo apt install ffmpeg
```

</details>

<details>
<summary><strong>4. 安裝 Ollama 並下載模型</strong></summary>

**安裝 Ollama：**

| 平台 | 安裝指令 |
|------|---------|
| Windows | `winget install Ollama.Ollama` |
| macOS | `brew install ollama` |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` |

**下載模型：**
```bash
# 文字摘要模型（預設）
ollama pull qwen3:8b

# 視覺分析模型（預設）
ollama pull gemma3:4b

# 可選替代模型
# ollama pull qwen2.5:7b
# ollama pull minicpm-v
```

</details>

<details>
<summary><strong>5. 設定環境變數</strong></summary>

複製 `.env.example` 為 `.env` 並填入設定：

```bash
cp .env.example .env
```

編輯 `.env` 檔案：

```env
# Telegram Bot Token（從 @BotFather 取得）
TELEGRAM_BOT_TOKEN=your_bot_token

# 允許使用 Bot 的 Chat ID（可選，留空表示允許所有人）
TELEGRAM_ALLOWED_CHAT_IDS=your_chat_id

# Whisper 本地模型設定
WHISPER_MODEL_SIZE=base    # tiny, base, small, medium, large-v2, large-v3
WHISPER_DEVICE=cpu         # cpu 或 cuda (需要 NVIDIA GPU)

# 摘要服務選擇
SUMMARIZER_BACKEND=ollama  # ollama（本地）、claude（Claude Code CLI）或 copilot（GitHub Copilot CLI）
CLAUDE_MODEL=sonnet        # sonnet, opus, haiku（僅 claude backend 使用）
COPILOT_MODEL=claude-opus-4.5  # gpt-4o, claude-sonnet-4.5, claude-opus-4.5（僅 copilot backend 使用）

# Ollama 本地 LLM 設定（SUMMARIZER_BACKEND=ollama 時使用）
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3:8b      # 可選: qwen2.5:7b, qwen2.5:14b
OLLAMA_VISION_MODEL=gemma3:4b  # 可選: minicpm-v

# Roam Research Graph 名稱
ROAM_GRAPH_NAME=your_graph_name

# Webhook 設定（Cloudflare Tunnel URL）
WEBHOOK_URL=https://your-tunnel-url.trycloudflare.com

# Claude Code 同步（可選）
CLAUDE_CODE_SYNC_ENABLED=false

# NotebookLM 自動同步（可選）
NOTEBOOKLM_ENABLED=false
NOTEBOOKLM_CDP_URL=http://localhost:9222
NOTEBOOKLM_UPLOAD_VIDEO=true

# Threads 設定（可選）
THREADS_ENABLED=true
THREADS_FETCH_REPLIES=true
THREADS_MAX_REPLIES=50
```

</details>

<details>
<summary><strong>6. 設定 Claude Code MCP 自動同步（可選）</strong></summary>

此功能可將摘要自動同步到 Roam Research，需要先設定 Claude Code 和 Roam MCP。

**前置需求：**

1. 安裝 [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
2. 設定 Roam Research MCP 伺服器

**設定 Roam MCP：**

在 Claude Code 的 MCP 設定檔中加入 Roam Research MCP：

```json
{
  "mcpServers": {
    "roam-research": {
      "command": "npx",
      "args": ["-y", "@anthropic/roam-research-mcp"],
      "env": {
        "ROAM_API_TOKEN": "your_roam_api_token",
        "ROAM_GRAPH_NAME": "your_graph_name"
      }
    }
  }
}
```

**啟用同步：**

在 `.env` 中設定：

```env
CLAUDE_CODE_SYNC_ENABLED=true
ROAM_GRAPH_NAME=your_graph_name
```

**運作方式：**

```
1. 摘要生成完成
       │
       ▼
2. 儲存 Markdown 到 roam_backup/
       │
       ▼
3. 呼叫 Claude Code CLI（非互動模式）
       │
       ▼
4. Claude Code 使用 Roam MCP 建立頁面
       │
       ▼
5. 內容自動出現在 Roam Research
```

> 💡 **提示**：即使 Claude Code 同步失敗，摘要仍會保存在本地 `roam_backup/` 資料夾中。

</details>

<details>
<summary><strong>7. 設定 NotebookLM 自動同步（可選）</strong></summary>

此功能透過 Chrome CDP + Playwright 自動化，將摘要與媒體上傳到 Google NotebookLM。

**前置需求：**

1. 安裝 Google Chrome
2. 安裝 Playwright：`pip install playwright && playwright install chromium`

**啟用方式：**

在 `.env` 中設定：

```env
NOTEBOOKLM_ENABLED=true
NOTEBOOKLM_CDP_URL=http://localhost:9222
NOTEBOOKLM_UPLOAD_VIDEO=true
```

**首次使用：**

1. 執行 `scripts\start_chrome_cdp.bat` 啟動 CDP Chrome（使用獨立 Profile）
2. 在開啟的 Chrome 視窗中登入 Google 帳號
3. 後續啟動會自動記住登入狀態

**運作方式：**

```
1. 摘要生成完成
       │
       ▼
2. 透過 CDP 連接到 Chrome
       │
       ▼
3. 建立或開啟當日 Notebook
       │
       ▼
4. 上傳摘要文字（作為 source）
       │
       ▼
5. 批次上傳影片 / 圖片（一次多選）
       │
       ▼
6. NotebookLM URL 回寫至 Roam 筆記
```

> 💡 **提示**：使用 `start.ps1` 一鍵啟動時，會自動啟動 Chrome CDP。

</details>

<details>
<summary><strong>8. 設定 Instagram Cookies</strong></summary>

為了下載 Instagram Reels，需要提供登入後的 cookies：

1. 安裝瀏覽器擴充功能 **"Get cookies.txt LOCALLY"**
2. 在瀏覽器登入 Instagram
3. 前往 instagram.com
4. 使用擴充功能匯出 cookies
5. 儲存為專案根目錄下的 `cookies.txt`

> ⚠️ **安全提醒**：`cookies.txt` 包含你的登入憑證，**絕對不要上傳到 GitHub**。此檔案已在 `.gitignore` 中排除。

</details>

<details>
<summary><strong>9. 取得 Telegram Chat ID</strong></summary>

1. 啟動 Bot 後，發送任意訊息給 Bot
2. 查看伺服器日誌，會顯示您的 Chat ID
3. 將 Chat ID 填入 `TELEGRAM_ALLOWED_CHAT_IDS`

</details>

---

## 啟動服務

### 開發模式

```bash
# 方法一：直接執行
python -m app.main

# 方法二：使用 uvicorn（支援熱重載）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 方法三：使用啟動腳本 (Windows)
.\start.ps1
# 或
start.bat
```

### 設定 Cloudflare Tunnel

<details>
<summary><strong>安裝 cloudflared</strong></summary>

| 平台 | 安裝指令 |
|------|---------|
| Windows | `winget install cloudflare.cloudflared` |
| macOS | `brew install cloudflare/cloudflare/cloudflared` |
| Linux | 參考 [Cloudflare 官方文件](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/) |

</details>

**建立 Tunnel：**
```bash
cloudflared tunnel --url http://localhost:8000
```

記下產生的 URL（如 `https://xxx.trycloudflare.com`）

### 設定 Telegram Webhook

```bash
curl -X POST "http://localhost:8000/webhook/setup?webhook_url=https://your-tunnel-url.trycloudflare.com"
```

---

## 使用方式

### Instagram Reels / 圖文貼文

```
1. 📱 在 Instagram App 找到想要摘要的 Reels 或圖文貼文
         │
         ▼
2. 📤 點擊「分享」按鈕
         │
         ▼
3. 📲 選擇 Telegram，發送給 Bot
         │
         ▼
4. ⏳ Bot 回覆「處理中...」
         │
         ▼
5. ✅ 處理完成，Bot 回覆：
      • 📝 摘要段落
      • 📌 條列式重點
      • 👁️ 畫面觀察（Reels）/ 📸 圖片分析（貼文）
      • 📎 Roam Research 頁面連結
      • 🤖 NotebookLM 連結（如啟用）
```

### Threads 貼文 / 串文

```
1. 🧵 在 Threads App 找到想要摘要的貼文
         │
         ▼
2. 📤 複製連結，發送給 Telegram Bot
         │
         ▼
3. ⏳ Bot 自動下載文字、圖片、影片
   ├── 單一貼文：直接處理
   └── 串文（作者多則連續貼文）：自動偵測並合併
         │
         ▼
4. ✅ 處理完成，Bot 回覆完整摘要
```

> **串文支援**：當作者以多則連續貼文發佈內容時（串文），系統會透過 Googlebot SSR 自動偵測並合併所有作者的貼文，排除其他人的回覆。每則貼文中的圖片與影片也會一併下載分析。

### 輸出範例

```
✅ 摘要完成！

📝 摘要
這是一段關於資料科學技巧的影片，分享了三個實用的 Python 資料處理方法...

📌 重點
• 使用 pandas 的 apply 函數進行資料轉換
• 利用 list comprehension 加速資料處理
• 掌握 groupby 進行分組統計

👁️ 畫面觀察
• 螢幕顯示 Jupyter Notebook 程式碼
• 講者使用螢光筆標記重點程式碼

📎 Roam Research
本地備份已儲存

🔗 原始連結
https://www.instagram.com/reel/xxx
```

---

## API 端點

| 端點 | 方法 | 說明 |
|------|------|------|
| `/` | GET | 健康檢查（根路徑） |
| `/health` | GET | 健康狀態端點 |
| `/webhook/telegram` | POST | Telegram Webhook 接收端點 |
| `/webhook/setup` | POST | 設定 Telegram Webhook |
| `/stats` | GET | 系統統計資訊 |

---

## 專案結構

```
instagram-reels-summarizer/
├── 📁 app/                      # 主要應用程式
│   ├── __init__.py
│   ├── main.py                  # FastAPI 入口與 Webhook 路由
│   ├── config.py                # Pydantic 設定與環境變數管理
│   ├── 📁 bot/
│   │   └── telegram_handler.py  # Telegram Bot 訊息處理
│   ├── 📁 services/
│   │   ├── downloader.py        # Instagram 下載 (yt-dlp + Instaloader)
│   │   ├── ig_cookie_provider.py # IG cookies/UA 自動供應（Chrome CDP）
│   │   ├── threads_downloader.py # Threads 貼文/串文下載（API + Googlebot SSR）
│   │   ├── download_logger.py   # 下載記錄（大小與連結）
│   │   ├── transcriber.py       # 語音轉錄 (faster-whisper)
│   │   ├── visual_analyzer.py   # 視覺分析 (Ollama + Vision Model)
│   │   ├── summarizer.py        # AI 摘要生成 (Ollama + LLM)
│   │   ├── summarizer_factory.py # 摘要服務工廠
│   │   ├── claude_summarizer.py # Claude Code CLI 摘要
│   │   ├── copilot_summarizer.py # GitHub Copilot CLI 摘要
│   │   ├── prompt_loader.py     # Prompt 模板載入器
│   │   ├── vault_sync.py        # Obsidian vault 知識庫寫入（含 INDEX 同步與 LLM 連結）
│   │   ├── roam_sync.py         # Roam Research 本地同步
│   │   └── notebooklm_sync.py   # NotebookLM 自動上傳 (Chrome CDP，已由 vault_sync 取代、預設停用)
│   ├── 📁 prompts/              # AI Prompt 模板
│   │   ├── 📁 examples/         # 範例筆記（供 AI 參考）
│   │   │   ├── 📁 audio/        # 有語音的影片範例
│   │   │   └── 📁 visual_only/  # 純視覺影片範例
│   │   ├── 📁 system/           # 系統提示詞
│   │   └── 📁 templates/        # 使用者模板
│   ├── 📁 scheduler/
│   │   └── retry_job.py         # 失敗任務重試排程
│   └── 📁 database/
│       └── models.py            # SQLite 模型（FailedJob + ProcessedURL）
├── 📁 scripts/                  # 手動測試腳本
│   ├── README.md                # 腳本使用說明
│   ├── start_chrome_cdp.bat     # 啟動 Chrome CDP（NotebookLM 用）
│   ├── test_download.py         # 下載功能測試
│   ├── test_transcribe.py       # 轉錄功能測試
│   ├── test_summarize.py        # 摘要功能測試
│   ├── test_visual.py           # 視覺分析測試
│   ├── test_flow.py             # 完整流程測試（不含視覺）
│   ├── test_flow_visual.py      # 完整流程測試（含視覺）
│   ├── test_post.py             # Instagram 貼文下載測試
│   ├── test_post_upload.py      # 貼文下載 + NotebookLM 上傳測試
│   ├── test_googlebot_thread.py # Threads Googlebot SSR 測試
│   ├── test_threads_full.py     # Threads 完整流程測試
│   ├── test_notebooklm.py       # NotebookLM 上傳測試
│   ├── test_notebooklm_file.py  # NotebookLM 檔案上傳測試
│   ├── test_claude_summarize.py # Claude 摘要測試
│   ├── test_copilot_summarize.py # Copilot 摘要測試
│   └── cleanup_notebooklm.py   # NotebookLM Notebook 清理
├── 📁 tests/                    # pytest 單元測試
│   ├── test_downloader.py       # 下載模組測試
│   ├── test_ig_cookie_provider.py # cookies/UA 自動供應測試
│   ├── test_summarizer.py       # 摘要模組測試
│   └── test_vault_sync.py       # vault 知識庫寫入測試
├── 📁 docs/                     # 專案文件
│   ├── ARCHITECTURE.md          # 架構與模組邊界
│   ├── telegram-deduplication.md
│   ├── 📁 prd/                  # 需求規格（vault-sync.md）
│   └── 📁 code-review/          # 程式碼審查紀錄
├── 📁 roam_backup/              # Roam Research 本地備份
├── 📁 temp_videos/              # 暫存影片目錄（自動清理）
├── 📁 note_example/             # 輸出筆記範例
├── .env.example                 # 環境變數範例
├── cookies.txt.example          # Instagram Cookies 範例
├── notebooklm_cookies.txt.example # NotebookLM Cookies 範例
├── categories.txt               # 分類清單
├── requirements.txt             # Python 依賴套件
├── CLAUDE.md                    # AI agent 工作規則
├── feature_list.json            # 功能清單與驗收狀態
├── session-handoff.md           # 開發交接紀錄
├── init.ps1                     # 環境恢復腳本
├── instagram-reels-summarizer-spec.md  # 完整功能規格
├── start.bat                    # Windows 啟動腳本 (CMD)
├── start.ps1                    # Windows 啟動腳本 (PowerShell)
└── README.md                    # 專案說明
```

---

## 故障排除

### 常見問題

<details>
<summary><strong>❌ 下載失敗，顯示「無法存取」</strong></summary>

**可能原因與解決方案：**
- Instagram 可能限制了存取 → 請稍後再試
- 連結可能不是公開的 Reels → 確認連結是否為公開內容
- `cookies.txt` 可能已過期 → 重新從瀏覽器匯出 cookies

</details>

<details>
<summary><strong>❌ 轉錄失敗</strong></summary>

**可能原因與解決方案：**
- faster-whisper 未正確安裝 → 執行 `pip install faster-whisper`
- 影片可能沒有語音內容 → 系統會自動改用視覺分析

</details>

<details>
<summary><strong>❌ Webhook 無法接收訊息</strong></summary>

**可能原因與解決方案：**
- Cloudflare Tunnel 未運行 → 確認 `cloudflared tunnel` 正在執行
- Webhook URL 設定錯誤 → 重新執行 `/webhook/setup` 端點
- 檢查防火牆設定 → 確保 port 8000 可被存取

</details>

<details>
<summary><strong>❌ Roam Research 同步失敗</strong></summary>

**解決方案：**
- 目前使用本地備份作為替代方案
- 內容會自動儲存在 `roam_backup` 資料夾
- 可透過 Claude Code MCP 手動同步

</details>

<details>
<summary><strong>❌ Ollama 模型載入失敗</strong></summary>

**可能原因與解決方案：**
- Ollama 服務未啟動 → 執行 `ollama serve`
- 模型未下載 → 執行 `ollama pull qwen3:8b` 和 `ollama pull gemma3:4b`
- 記憶體不足 → 嘗試使用較小的模型

</details>

<details>
<summary><strong>❌ NotebookLM 上傳失敗</strong></summary>

**可能原因與解決方案：**
- Chrome CDP 未啟動 → 執行 `scripts\start_chrome_cdp.bat` 或使用 `start.ps1`
- Google 未登入 → 在 CDP Chrome 視窗中登入 Google 帳號
- Notebook 被刪除 → 系統會自動偵測並重新建立
- CDK Overlay 遮擋按鈕 → 系統已自動處理（使用 JS click 繞過）
- 頁面跳轉導致上傳中斷 → 系統已自動偵測並導航回 Notebook

</details>

### 查看日誌

```bash
# 開發模式會自動顯示日誌
# 設定 LOG_LEVEL=DEBUG 可顯示更詳細的日誌
```

### 更新 yt-dlp

Instagram 可能會更改網頁結構，需要定期更新 yt-dlp：

```bash
pip install --upgrade yt-dlp
```

---

## 開發工作流程

### 分支策略

1. **main** - 穩定的生產版本
2. **feature/*** - 新功能開發分支
3. **fix/*** - 錯誤修復分支

### 開發流程

```
1. 建立功能分支
   git checkout -b feature/amazing-feature

2. 執行測試腳本驗證功能
   python scripts/test_flow_visual.py

3. 執行單元測試
   pytest tests/

4. 提交變更
   git commit -m 'Add amazing feature'

5. 推送並建立 Pull Request
   git push origin feature/amazing-feature
```

### 測試流程

建議按以下順序執行測試腳本，確保每個模組正常運作：

1. **下載測試** - 確認 cookies.txt 和 yt-dlp 正常
2. **轉錄測試** - 確認 faster-whisper 正常
3. **摘要測試** - 確認 Ollama 服務和模型正常
4. **視覺分析測試** - 確認視覺模型正常
5. **完整流程測試** - 端對端驗證

詳細說明請參考 [scripts/README.md](scripts/README.md)

---

## 編碼規範

### Python 程式碼風格

- 遵循 PEP 8 編碼規範
- 使用 Type Hints 標註函數參數與回傳值
- 函數與類別使用 docstring 說明用途
- 設定管理使用 Pydantic Settings
- 非同步操作使用 `async/await` 語法

### 檔案組織

- 服務邏輯放置於 `app/services/`
- Bot 處理邏輯放置於 `app/bot/`
- 資料庫模型放置於 `app/database/`
- 排程任務放置於 `app/scheduler/`
- Prompt 模板放置於 `app/prompts/`

### 錯誤處理

- 使用適當的例外處理機制
- 記錄失敗任務至資料庫以便重試
- 回傳有意義的錯誤訊息給使用者

### 安全性考量

- 敏感資料（cookies、tokens）不納入版本控制
- 使用環境變數管理機密設定
- Telegram 訊息驗證使用 Chat ID 白名單
- 處理完成後刪除暫存影片檔案

---

## 測試

### 單元測試

使用 pytest 進行單元測試：

```bash
# 執行所有測試
pytest tests/

# 執行特定測試檔案
pytest tests/test_downloader.py

# 執行並顯示詳細輸出
pytest tests/ -v
```

### 手動測試腳本

專案提供手動測試腳本，用於單獨測試各個模組：

```bash
# 從專案根目錄執行
python scripts/test_download.py      # 測試下載功能
python scripts/test_transcribe.py    # 測試轉錄功能
python scripts/test_summarize.py     # 測試摘要功能
python scripts/test_visual.py        # 測試視覺分析
python scripts/test_flow_visual.py   # 完整流程測試
```

### 測試覆蓋範圍

- **test_downloader.py** - Instagram 影片 / 貼文下載測試
- **test_summarizer.py** - AI 摘要生成測試
- **test_notebooklm.py** - NotebookLM 上傳測試

---

## 貢獻指南

### 如何貢獻

1. Fork 此專案
2. 建立功能分支（`git checkout -b feature/amazing-feature`）
3. 提交變更（`git commit -m 'Add amazing feature'`）
4. 推送分支（`git push origin feature/amazing-feature`）
5. 開啟 Pull Request

### 程式碼審查

提交 Pull Request 前，請確保：

- 程式碼遵循專案的編碼規範
- 新增功能已包含對應的測試
- 所有現有測試通過
- 更新相關文件（如適用）

參考程式碼範例可查看 `app/services/` 目錄中的現有模組實作。

### 安全性審查

專案包含安全審查指引，請參考：
- [.github/agents/se-security-reviewer.agent.md](.github/agents/se-security-reviewer.agent.md) - 安全審查標準
- [.github/instructions/code-review-generic.instructions.md](.github/instructions/code-review-generic.instructions.md) - 程式碼審查指引

---

## 授權

本專案僅供個人學習使用。

---

## 相關文件

| 文件 | 說明 |
|------|------|
| [instagram-reels-summarizer-spec.md](instagram-reels-summarizer-spec.md) | 完整功能規格與技術規格 |
| [scripts/README.md](scripts/README.md) | 測試腳本使用說明 |
| [docs/telegram-deduplication.md](docs/telegram-deduplication.md) | Telegram 訊息去重機制說明 |

---

## 已知限制

- Instagram 可能會更改網頁結構，需定期更新 yt-dlp
- 部分 Reels 可能有版權保護無法下載
- faster-whisper 對於背景音樂較大的影片，轉錄品質可能較差
- 本地 LLM 摘要品質取決於模型大小
- 首次執行需下載模型，需要額外時間
- NotebookLM 同步需要保持 Chrome CDP 視窗開啟
- NotebookLM 介面可能更新導致選擇器失效，需適時調整

---

## 未來規劃

- 支援 TikTok、YouTube Shorts 等其他短影片平台
- 加入影片分類自動標籤功能
- 支援多語言摘要輸出
- 建立 Web Dashboard 查看處理歷史
- 支援 GPU 加速提升處理速度
- NotebookLM Audio Overview 自動生成

---

## 更新日誌

| 日期 | 版本 | 更新內容 |
|------|------|---------|
| 2026-02-19 | v1.7.0 | Threads 串文支援（Googlebot SSR 自動偵測作者連續貼文、過濾回覆） |
| 2026-02-17 | v1.6.0 | NotebookLM 多圖批次上傳（一次多選）、頁面跳轉修復 |
| 2026-02-16 | v1.5.0 | NotebookLM 改用 Chrome CDP 連線、獨立 Profile、Notebook 自動偵測 |
| 2026-02-10 | v1.4.0 | 新增 Instagram 圖文貼文支援、Threads 貼文支援、NotebookLM 同步 |
| 2026-02-03 | v1.3.0 | 更新預設模型為 Qwen3:8b 和 Gemma3:4b |
| 2026-01-22 | v1.2.0 | 新增 Claude Code MCP 同步、並行幀分析、動態幀數 |
| 2026-01-21 | v1.1.0 | 新增 MiniCPM-V 視覺分析功能 |
| 2026-01-20 | v1.0.0 | 初始版本發布 |

---

<div align="center">

**Made with ❤️ for personal knowledge management**

</div>
