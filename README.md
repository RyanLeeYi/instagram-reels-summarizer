# Instagram Reels 影片自動摘要系統

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20AI-orange.svg)](https://ollama.com/)
[![License](https://img.shields.io/badge/License-Personal%20Use-lightgrey.svg)](#授權)

> 透過 Telegram Bot 接收 Instagram Reels 連結，自動下載影片、轉錄語音、生成摘要，並同步至 Roam Research。

---

## 目錄

- [功能特色](#功能特色)
- [系統架構](#系統架構)
- [系統需求](#系統需求)
- [安裝步驟](#安裝步驟)
- [啟動服務](#啟動服務)
- [使用方式](#使用方式)
- [API 端點](#api-端點)
- [專案結構](#專案結構)
- [故障排除](#故障排除)
- [授權](#授權)

---

## 功能特色

| 功能 | 說明 | 技術 |
|------|------|------|
| 📱 **Telegram Bot 整合** | 直接分享 Instagram Reels 連結即可處理 | python-telegram-bot |
| 🎬 **自動下載** | 下載 Instagram Reels 影片 | yt-dlp + cookies.txt |
| 🎤 **語音轉錄** | 本地語音轉文字（免費、無需 API Key） | faster-whisper |
| 👁️ **視覺分析** | 分析影片畫面（動態 8-10 幀、並行處理） | MiniCPM-V |
| 📝 **AI 摘要** | 整合語音與畫面生成繁體中文摘要 | Ollama + Qwen2.5 |
| 📚 **Roam Research 同步** | 本地 Markdown + Claude Code MCP 自動同步 | Markdown + MCP |
| 🔄 **失敗重試** | 自動重試失敗的任務（最多 3 次） | APScheduler |
| ⚡ **並行處理** | 幀分析支援並行加速 | asyncio |

### 💡 完全免費

本專案使用本地 AI 模型，**不需要任何 API Key**：

- **語音轉錄**：faster-whisper（本地運行）
- **視覺分析**：MiniCPM-V（本地運行）
- **摘要生成**：Ollama + Qwen2.5（本地運行）

---

## 系統架構

```
┌──────────────────────────────────────────────────────────────────┐
│                         本地端伺服器                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌───────────┐    ┌───────────┐    ┌─────────────┐              │
│  │ Telegram  │───▶│  下載器   │───▶│faster-whisper│              │
│  │  Bot API  │    │ (yt-dlp)  │    │  本地轉錄   │              │
│  └───────────┘    └───────────┘    └─────────────┘              │
│        │                                 │                       │
│        │                         ┌───────┴───────┐               │
│        │                         ▼               ▼               │
│        │                 ┌─────────────┐ ┌─────────────┐        │
│        │                 │  MiniCPM-V  │ │ Ollama +    │        │
│        │                 │  視覺分析   │─▶│ Qwen2.5     │        │
│        │                 └─────────────┘ └─────────────┘        │
│        │                                        │                │
│        ▼                                        ▼                │
│  ┌───────────┐                         ┌─────────────┐          │
│  │ 回覆訊息  │◀────────────────────────│  Markdown   │          │
│  └───────────┘                         │  本地儲存   │          │
│                                        └─────────────┘          │
│                                                                  │
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
# 文字摘要模型
ollama pull qwen2.5:7b

# 視覺分析模型
ollama pull minicpm-v
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

# Ollama 本地 LLM 設定
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b    # 可選: qwen2.5:3b, qwen2.5:14b
OLLAMA_VISION_MODEL=minicpm-v

# Roam Research Graph 名稱
ROAM_GRAPH_NAME=your_graph_name

# Webhook 設定（Cloudflare Tunnel URL）
WEBHOOK_URL=https://your-tunnel-url.trycloudflare.com

# Claude Code 同步（可選）
CLAUDE_CODE_SYNC_ENABLED=false
```

</details>

<details>
<summary><strong>6. 設定 Instagram Cookies</strong></summary>

為了下載 Instagram Reels，需要提供登入後的 cookies：

1. 安裝瀏覽器擴充功能 **"Get cookies.txt LOCALLY"**
2. 在瀏覽器登入 Instagram
3. 前往 instagram.com
4. 使用擴充功能匯出 cookies
5. 儲存為專案根目錄下的 `cookies.txt`

> ⚠️ **安全提醒**：`cookies.txt` 包含你的登入憑證，**絕對不要上傳到 GitHub**。此檔案已在 `.gitignore` 中排除。

</details>

<details>
<summary><strong>7. 取得 Telegram Chat ID</strong></summary>

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

```
1. 📱 在 Instagram App 找到想要摘要的 Reels
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
      • 👁️ 畫面觀察
      • 📎 Roam Research 頁面連結
```

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
│   ├── main.py                  # FastAPI 入口
│   ├── config.py                # 設定與環境變數
│   ├── 📁 bot/
│   │   └── telegram_handler.py  # Telegram Bot 處理
│   ├── 📁 services/
│   │   ├── downloader.py        # Instagram 下載
│   │   ├── transcriber.py       # Whisper 轉錄
│   │   ├── visual_analyzer.py   # MiniCPM-V 視覺分析
│   │   ├── summarizer.py        # Ollama 摘要
│   │   └── roam_sync.py         # Roam Research 同步
│   ├── 📁 scheduler/
│   │   └── retry_job.py         # 重試排程
│   └── 📁 database/
│       └── models.py            # SQLite 模型
├── 📁 scripts/                  # 手動測試腳本
│   ├── test_download.py         # 下載測試
│   ├── test_transcribe.py       # 轉錄測試
│   ├── test_summarize.py        # 摘要測試
│   ├── test_visual.py           # 視覺分析測試
│   ├── test_flow.py             # 完整流程測試
│   └── test_flow_visual.py      # 完整流程測試（含視覺）
├── 📁 tests/                    # pytest 單元測試
│   ├── test_downloader.py
│   └── test_summarizer.py
├── 📁 roam_backup/              # Roam Research 本地備份
├── 📁 temp_videos/              # 暫存影片目錄
├── .env.example                 # 環境變數範例
├── cookies.txt.example          # Cookies 範例
├── requirements.txt             # Python 依賴
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
- 模型未下載 → 執行 `ollama pull qwen2.5:7b` 和 `ollama pull minicpm-v`
- 記憶體不足 → 嘗試使用較小的模型（如 `qwen2.5:3b`）

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

## 技術堆疊

| 類別 | 技術 |
|------|------|
| **Web 框架** | FastAPI |
| **Telegram Bot** | python-telegram-bot |
| **影片下載** | yt-dlp |
| **語音轉錄** | faster-whisper |
| **摘要生成** | Ollama + Qwen2.5 |
| **視覺分析** | Ollama + MiniCPM-V |
| **資料庫** | SQLite + SQLAlchemy |
| **任務排程** | APScheduler |
| **反向代理** | Cloudflare Tunnel |

---

## 貢獻指南

1. Fork 此專案
2. 建立功能分支（`git checkout -b feature/amazing-feature`）
3. 提交變更（`git commit -m 'Add amazing feature'`）
4. 推送分支（`git push origin feature/amazing-feature`）
5. 開啟 Pull Request

---

## 授權

本專案僅供個人學習使用。

---

## 更新日誌

| 日期 | 版本 | 更新內容 |
|------|------|---------|
| 2026-01-22 | v1.2.0 | 新增 Claude Code MCP 同步、並行幀分析、動態幀數 |
| 2026-01-21 | v1.1.0 | 新增 MiniCPM-V 視覺分析功能 |
| 2026-01-20 | v1.0.0 | 初始版本發布 |

---

<div align="center">

**Made with ❤️ for personal knowledge management**

</div>
