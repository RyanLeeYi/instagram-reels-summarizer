# ARCHITECTURE

FastAPI 單 process，webhook 驅動的內容摘要 pipeline。由 mission-control 中台管理（服務名 `reels-summarizer`，port 8001，health `/health`）。

```
Telegram ── Cloudflare tunnel（my-ig-to-roam.my-super-dev-server.work，dashboard 管 ingress → localhost:8001）
   │
   ▼ POST /webhook/telegram
app/bot/telegram_handler.py ──依 URL 類型分流──┐
   │                                            │
   ▼ Reel/影片                                  ▼ 圖文貼文 / Threads
downloader.py（yt-dlp + cookies.txt）        downloader.download_post（instaloader）
   │                                         threads_downloader.py（Googlebot SSR）
   ▼
transcriber.py（faster-whisper 本地轉錄）
visual_analyzer.py（Ollama vision 逐幀分析，並行）
   │
   ▼
summarizer_factory.py → ollama / claude CLI / copilot CLI（SUMMARIZER_BACKEND 切換）
   │
   ├─ Telegram 回覆（editMessageText 更新進度）
   ├─ roam_sync.py：roam_backup/ 本地 Markdown 備份（+可選 Claude Code MCP 同步 Roam）
   └─ notebooklm_sync.py：Playwright + Chrome CDP 上傳當日 Notebook（可選）
```

## 目錄職責

```
app/
  main.py             FastAPI 組裝：webhook 註冊、DB 初始化、重試排程器（RETRY_ENABLED）
  config.py           Settings（pydantic-settings，.env）
  bot/telegram_handler.py   訊息收發、URL 分流、進度回報——不碰下載細節
  services/
    downloader.py     IG 下載唯一出口（yt-dlp 影音 / instaloader 圖文+caption）
    threads_downloader.py   Threads 貼文與串文
    transcriber.py    faster-whisper 語音轉文字
    visual_analyzer.py      Ollama vision 幀分析
    summarizer_factory.py   摘要 backend 工廠（ollama/claude/copilot）
    roam_sync.py      本地備份 + Roam MCP 同步
    notebooklm_sync.py      NotebookLM 上傳（Chrome CDP）
    download_logger.py / prompt_loader.py   輔助
  database/models.py  SQLAlchemy：failed_tasks / processed_urls / notebooklm_notebooks（app.db）
  scheduler/retry_job.py    APScheduler 失敗重試
tests/                pytest（test_downloader / test_summarizer）
```

## 邊界規則

- bot 層不得 import yt_dlp / instaloader——下載一律經 `services/downloader.py`
- 密鑰只在 `.env`、`cookies.txt`、`notebooklm_cookies.txt`（gitignored）；程式碼與 log 不得印 token（httpx INFO 目前會，見 feature list）
- 埠 8001 是 tunnel ingress 指的位置——改埠必須同步改 Cloudflare Zero Trust dashboard

## 外部依賴（環境敗點）

| 依賴 | 用途 | 失效症狀 |
|------|------|----------|
| cookies.txt（IG 登入態） | yt-dlp / instaloader 認證 | 登入牆內容 empty media response / LoginRequired |
| yt-dlp 版本 | IG 改版跟進 | 舊版一律 empty media response（2026-07-11 教訓） |
| Ollama（中台管理） | vision 分析 / ollama backend | 幀分析失敗 |
| Copilot / Claude CLI 登入態 | 雲端摘要 backend | 摘要步驟失敗 |
| Chrome CDP profile | NotebookLM 上傳 | F7 失敗，主流程不受影響 |
