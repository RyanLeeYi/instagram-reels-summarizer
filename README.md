# Instagram Reels 影片自動摘要系統

透過 Telegram Bot 接收 Instagram Reels 連結，自動下載影片、轉錄語音、生成摘要，並同步至 Roam Research。

## 功能特色

- 📱 **Telegram Bot 整合**：直接分享 Instagram Reels 連結即可處理
- 🎬 **自動下載**：使用 yt-dlp + cookies.txt 下載 Instagram Reels 影片
- 🎤 **語音轉錄**：使用 faster-whisper 本地模型（免費、無需 API Key）
- 👁️ **視覺分析**：使用 MiniCPM-V 分析影片畫面（動態 8-10 幀、並行處理）
- 📝 **AI 摘要**：使用 Ollama + Qwen2.5 整合語音與畫面生成繁體中文摘要
- 📚 **Roam Research 同步**：本地 Markdown + Claude Code MCP 自動同步
- 🔄 **失敗重試**：自動重試失敗的任務
- ⚡ **並行處理**：幀分析支援並行加速

## 💡 完全免費

本專案使用本地 AI 模型，**不需要任何 API Key**：
- 語音轉錄：faster-whisper（本地）
- 摘要生成：Ollama + Qwen2.5（本地）

## 系統需求

- Python 3.10+
- FFmpeg（用於音訊處理）
- Cloudflare Tunnel（用於 Webhook）

## 安裝步驟

### 1. 複製專案

```bash
cd instagram-reels-summarizer
```

### 2. 建立虛擬環境

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. 安裝依賴

```bash
pip install -r requirements.txt
```

### 4. 安裝 FFmpeg

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
sudo apt update
sudo apt install ffmpeg
```

### 5. 安裝 Ollama

**Windows:**
```bash
winget install Ollama.Ollama
```

**macOS:**
```bash
brew install ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

下載模型：
```bash
# 文字摘要模型
ollama pull qwen2.5:7b

# 視覺分析模型
ollama pull minicpm-v
```

### 6. 設定環境變數

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

# Whisper 本地模型設定（無需 API Key）
WHISPER_MODEL_SIZE=base  # tiny, base, small, medium, large-v2, large-v3
WHISPER_DEVICE=cpu  # cpu 或 cuda (需要 NVIDIA GPU)

# Ollama 本地 LLM 設定（無需 API Key）
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b  # 可選: qwen2.5:3b, qwen2.5:14b
OLLAMA_VISION_MODEL=minicpm-v  # 視覺分析模型

# Roam Research Graph 名稱
ROAM_GRAPH_NAME=your_graph_name

# Claude Code 同步（可選，需先設定 Roam MCP）
CLAUDE_CODE_SYNC_ENABLED=false  # true 啟用自動同步到 Roam
```

### 7. 設定 Instagram Cookies

為了下載 Instagram Reels，需要提供登入後的 cookies：

1. 安裝瀏覽器擴充功能 "Get cookies.txt LOCALLY"（或類似工具）
2. 在瀏覽器登入 Instagram
3. 前往 instagram.com
4. 使用擴充功能匯出 cookies
5. 儲存為專案根目錄下的 `cookies.txt`

> ⚠️ **安全提醒**：`cookies.txt` 包含你的登入憑證，**絕對不要上傳到 GitHub**。此檔案已在 `.gitignore` 中排除。

### 8. 取得 Telegram Chat ID

1. 啟動 Bot 後，發送任意訊息給 Bot
2. 查看伺服器日誌，會顯示您的 Chat ID
3. 將 Chat ID 填入 `TELEGRAM_ALLOWED_CHAT_IDS`

## 啟動服務

### 開發模式

```bash
python -m app.main
```

或使用 uvicorn：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 設定 Cloudflare Tunnel

1. 安裝 cloudflared：
   ```bash
   # Windows
   winget install cloudflare.cloudflared

   # macOS
   brew install cloudflare/cloudflare/cloudflared

   # Linux
   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
   chmod +x cloudflared
   ```

2. 建立 Tunnel：
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```

3. 記下產生的 URL（如 `https://xxx.trycloudflare.com`）

### 設定 Telegram Webhook

使用 API 設定 Webhook：

```bash
curl -X POST "http://localhost:8000/webhook/setup?webhook_url=https://your-tunnel-url.trycloudflare.com"
```

## 使用方式

1. 在 Instagram App 找到想要摘要的 Reels
2. 點擊「分享」按鈕
3. 選擇 Telegram，發送給 Bot
4. Bot 會回覆「處理中...」
5. 等待處理完成，Bot 會回覆：
   - 摘要段落
   - 條列式重點
   - 畫面觀察
   - Roam Research 頁面連結

## API 端點

| 端點 | 方法 | 說明 |
|------|------|------|
| `/` | GET | 健康檢查 |
| `/health` | GET | 健康狀態 |
| `/webhook/telegram` | POST | Telegram Webhook |
| `/webhook/setup` | POST | 設定 Webhook |
| `/stats` | GET | 系統統計資訊 |

## 專案結構

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
│   │   ├── downloader.py       # Instagram 下載
│   │   ├── transcriber.py      # Whisper 轉錄
│   │   ├── visual_analyzer.py  # MiniCPM-V 視覺分析
│   │   ├── summarizer.py       # Ollama 摘要
│   │   └── roam_sync.py        # Roam Research 同步
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── retry_job.py        # 重試排程
│   └── database/
│       ├── __init__.py
│       └── models.py           # SQLite 模型
├── scripts/                    # 手動測試腳本
│   ├── README.md
│   ├── test_download.py        # 下載測試
│   ├── test_transcribe.py      # 轉錄測試
│   ├── test_summarize.py       # 摘要測試
│   ├── test_visual.py          # 視覺分析測試
│   ├── test_flow.py            # 完整流程測試
│   └── test_flow_visual.py     # 完整流程測試（含視覺）
├── tests/                      # pytest 單元測試
│   ├── __init__.py
│   ├── test_downloader.py
│   └── test_summarizer.py
├── .env.example                # 環境變數範例
├── .gitignore                  # Git 忽略規則
├── cookies.txt.example         # Cookies 範例
├── requirements.txt            # Python 依賴
├── start.bat                   # Windows 啟動腳本
├── start.ps1                   # PowerShell 啟動腳本
└── README.md
```

## 故障排除

### 常見問題

**Q: 下載失敗，顯示「無法存取」**
- Instagram 可能限制了存取，請稍後再試
- 確認連結是否為公開的 Reels
- 確認 `cookies.txt` 有效（可能需要重新匯出）

**Q: 轉錄失敗**
- 確認 faster-whisper 已正確安裝
- 影片可能沒有語音內容

**Q: Webhook 無法接收訊息**
- 確認 Cloudflare Tunnel 正在運行
- 確認 Webhook URL 正確設定

**Q: Roam Research 同步失敗**
- 目前使用本地備份作為替代方案
- 內容會儲存在 `roam_backup` 資料夾

### 查看日誌

```bash
# 開發模式會自動顯示日誌
# 或設定 LOG_LEVEL=DEBUG
```

## 更新 yt-dlp

Instagram 可能會更改網頁結構，需要定期更新 yt-dlp：

```bash
pip install --upgrade yt-dlp
```

## 授權

本專案僅供個人學習使用。

---

*建立時間: 2026-01-20*  
*更新時間: 2026-01-21 - 新增視覺分析功能*  
*更新時間: 2026-01-22 - 新增 Claude Code MCP 同步、並行幀分析、動態幀數*
