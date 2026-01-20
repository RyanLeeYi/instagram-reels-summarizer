# Instagram Reels 影片自動摘要系統 開發規格

## 1. 概述

- **功能描述**: 透過 Telegram Bot 接收 Instagram Reels 連結，自動下載影片、轉錄語音、生成摘要，並同步至 Roam Research
- **開發背景**: 簡化 Instagram Reels 影片內容的擷取與知識管理流程，實現自動化筆記整理
- **目標使用者**: 個人使用
- **特點**: 完全免費，使用本地 AI 模型，無需任何 API Key

## 2. 功能需求

### 2.1 核心功能

| 功能項目 | 說明 | 優先級 |
|---------|------|--------|
| Telegram Bot 接收連結 | 接收使用者分享的 Instagram Reels 連結 | 高 |
| Instagram 影片下載 | 解析連結並下載 Reels 短影片 | 高 |
| 語音轉逐字稿 | 使用 faster-whisper 本地模型將影片音訊轉為文字 | 高 |
| AI 摘要生成 | 使用 Ollama + Qwen2.5 本地模型生成摘要與條列重點 | 高 |
| Telegram 回覆 | 回傳摘要、重點與 Roam 頁面連結 | 高 |
| Roam Research 同步 | 儲存為本地 Markdown 檔案供匯入 Roam Research | 高 |
| 失敗重試機制 | 記錄失敗連結並自動定時重試 | 中 |

### 2.2 使用流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                          使用者操作流程                              │
└─────────────────────────────────────────────────────────────────────┘

1. 使用者在手機 Instagram App 看到感興趣的 Reels
2. 點擊分享 → 選擇 Telegram → 發送給 Bot
3. Bot 回覆「處理中...」
4. 等待處理完成
5. Bot 回覆：
   - 摘要段落
   - 條列式重點
   - Roam Research 頁面連結
6. 內容同步出現在 Roam Research

┌─────────────────────────────────────────────────────────────────────┐
│                          系統處理流程                                │
└─────────────────────────────────────────────────────────────────────┘

┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────────┐
│ Telegram │───▶│ 下載影片  │───▶│ faster-whisper │───▶│ Ollama/Qwen  │
│   Bot    │    │          │    │ 本地轉錄       │    │ 本地摘要     │
└──────────┘    └──────────┘    └──────────────┘    └──────────────┘
                                                      │
                     ┌────────────────────────────────┤
                     ▼                                ▼
              ┌──────────┐                     ┌──────────┐
              │ Telegram │                     │  Roam    │
              │ 回覆     │                     │ Research │
              └──────────┘                     └──────────┘
```

### 2.3 例外處理

| 情境 | 處理方式 |
|------|---------|
| Instagram 連結無效 | 回傳錯誤訊息：「無法解析此連結，請確認是否為有效的 Instagram Reels 連結」 |
| 影片下載失敗 | 記錄連結至失敗清單，回傳「下載失敗，已排入重試佇列」 |
| 語音轉錄失敗 | 記錄連結至失敗清單，回傳「轉錄失敗，已排入重試佇列」 |
| 影片無語音/靜音 | 回傳「此影片無可辨識的語音內容」 |
| Ollama 摘要失敗 | 記錄連結至失敗清單，回傳「摘要生成失敗，已排入重試佇列」 |
| Roam Research 同步失敗 | 先回傳 Telegram 摘要，記錄同步失敗待重試 |
| 重試 3 次仍失敗 | 回傳「處理失敗已達重試上限，請手動重新分享」 |

## 3. 技術規格

### 3.1 技術堆疊

| 項目 | 技術選擇 |
|------|---------|
| 程式語言 | Python 3.10+ |
| Web 框架 | FastAPI |
| Telegram Bot | python-telegram-bot 套件 |
| Instagram 下載 | yt-dlp |
| 語音轉錄 | faster-whisper 本地模型 |
| 摘要生成 | Ollama + Qwen2.5 本地模型 |
| Roam 整合 | 本地 Markdown 檔案儲存 |
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
│  │  Bot API    │───▶│  (yt-dlp)   │───▶│ 本地轉錄      │        │
│  └─────────────┘    └─────────────┘    └─────────────┘        │
│         │                                      │               │
│         │                                      ▼               │
│         │                              ┌─────────────┐        │
│         │                              │ Ollama +    │        │
│         │                              │ Qwen2.5     │        │
│         │                              └─────────────┘        │
│         │                                      │               │
│         ▼                                      ▼               │
│  ┌─────────────┐                       ┌─────────────┐        │
│  │  回覆訊息   │◀──────────────────────│ Markdown  │        │
│  └─────────────┘                       │ 本地儲存    │        │
│                                       └─────────────┘        │
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐                           │
│  │  失敗記錄   │◀───│  排程器     │                           │
│  │  (SQLite)   │───▶│ (每小時)    │                           │
│  └─────────────┘    └─────────────┘                           │
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
  "language_detected": "zh-TW",
  "processed_at": "2026-01-20T10:30:00+08:00"
}
```

### 3.4 Roam Research 頁面格式

```markdown
[[IG Reels - 2026-01-20 - 影片標題]]

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

## 逐字稿
> 完整的語音轉文字內容...
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

📎 Roam Research
https://roamresearch.com/#/app/your-graph/page/xxx

🔗 原始連結
https://www.instagram.com/reel/xxx
```

### 3.6 服務整合需求

| 服務 | 用途 | 需要的懑證 |
|------|------|-----------|
| Telegram Bot API | 接收訊息與回覆 | Bot Token |
| faster-whisper | 本地語音轉錄 | 無（本地模型） |
| Ollama + Qwen2.5 | 本地摘要生成 | 無（本地模型） |
| Roam Research | 本地 Markdown 儲存 | 無 |

### 3.7 環境變數設定

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ALLOWED_CHAT_IDS=your_chat_id

# Whisper 本地模型設定
WHISPER_MODEL_SIZE=base  # tiny, base, small, medium, large-v2, large-v3
WHISPER_DEVICE=cpu       # cpu 或 cuda

# Ollama 本地 LLM 設定
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b  # 可選: qwen2.5:3b, qwen2.5:14b

# Roam Research
ROAM_GRAPH_NAME=your_graph_name

# 系統設定
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
| Instagram 連結格式 | 支援 `instagram.com/reel/xxx` 與 `instagram.com/p/xxx` |
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

- [x] 能成功接收 Telegram 傳來的 Instagram Reels 連結
- [x] 能正確下載 Instagram Reels 影片
- [x] 能透過 faster-whisper 本地模型將影片語音轉為文字（支援中英文）
- [ ] 能透過 Ollama + Qwen2.5 本地模型生成中文摘要與條列重點
- [ ] Telegram Bot 正確回覆摘要、重點與 Roam 連結
- [ ] 成功儲存 Markdown 檔案供匯入 Roam Research
- [ ] 頁面正確標記 `#Instagram摘要` hashtag
- [ ] 失敗時正確記錄並顯示提示訊息
- [ ] 每小時自動重試失敗的任務
- [ ] 重試 3 次後正確標記為放棄並通知使用者
- [ ] 處理完成後正確刪除暫存影片檔案

### 5.2 整合驗收

- [ ] Cloudflare Tunnel 正確暴露本地服務
- [ ] 手機 Instagram 分享至 Telegram Bot 流程順暢
- [ ] 端對端流程可在 2 分鐘內完成

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
│   │   ├── downloader.py       # Instagram 下載 (yt-dlp)
│   │   ├── transcriber.py      # 本地 Whisper 轉錄 (faster-whisper)
│   │   ├── summarizer.py       # 本地 LLM 摘要 (Ollama + Qwen2.5)
│   │   └── roam_sync.py        # Markdown 儲存
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── retry_job.py        # 重試排程
│   └── database/
│       ├── __init__.py
│       └── models.py           # SQLite 模型
├── tests/
│   └── ...
├── .env.example
├── requirements.txt
├── README.md
└── docker-compose.yml          # 可選：Docker 部署
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
- 整合 Roam Research API（待官方開放）

---

*本文件由需求分析師產出，可直接供 AI 進行開發*  
*產出時間: 2026-01-20*  
*更新: 改用本地 AI 模型 (faster-whisper + Ollama)*
