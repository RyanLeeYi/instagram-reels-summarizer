# instagram-reels-summarizer

Telegram bot：收 IG Reels / 圖文貼文 / Threads 連結 → 下載、轉錄、AI 摘要 → 回覆 + Roam/NotebookLM 同步。
架構與邊界：`docs/ARCHITECTURE.md`。

## 啟動與驗證

- 環境恢復：`.\init.ps1`
- **本服務由 mission-control 管理**（服務名 `reels-summarizer`，port 8001）：重啟走中台（Web UI / MCP / REST），**不要自己再起一份**，會撞埠
- 測試：`.venv\Scripts\python.exe -m pytest tests -q`（宣告 feature 完成前必跑並貼輸出）
- 手動端到端驗證：對 Telegram bot 傳一條 IG 連結，收到摘要才算通（webhook 模式，訊息走 Cloudflare tunnel → localhost:8001）

## 專案結構與邊界

- `app/bot/` 只管 Telegram 收發；業務流程在 `app/services/`，bot 不得直接碰 yt-dlp/instaloader
- `app/services/` 各檔單一職責（downloader / transcriber / visual_analyzer / summarizer_factory / roam_sync / notebooklm_sync）
- 密鑰只在 `.env`、`cookies.txt`、`notebooklm_cookies.txt`（皆已 gitignore，**絕不 commit**）
- `cookies.txt` 會被 yt-dlp 回寫——修 cookies 問題時先備份再動

## 陷阱（踩過的坑）

- 改埠之前先查外部路由：Telegram webhook 經 Cloudflare tunnel ingress 指向本服務埠（dashboard 管理，不在 repo 裡）
- yt-dlp 舊版對 IG 一律回「empty media response」，跟 cookies 無關——先 `yt-dlp --version` 再懷疑 cookies
- httpx INFO log 會印完整 bot token 進 log——中台 F14 會遮蔽 tail 輸出，但根治要調 logger 等級

## 工作規則

1. 一次只推進一個 envelope（沒有 envelope 就是一條 feature，看 `feature_list.json` 挑第一個 failing）。
   同 envelope 內的 slice 可同批實作，序列或平行皆可；平行需 `touches` 無交集且各自 worktree。
   **驗收一律逐條、依 `prerequisites` 順序、各自 evidence**——上游改動會讓已通過的下游驗收失效
2. status 只能 failing → passing 且必附 evidence
3. list 之外的新事項先加進 list 標 failing，不直接做
4. session 結束前更新 session-handoff.md
5. 收工檢查 git status；有改動就 commit 並 push（remote：https://github.com/RyanLeeYi/instagram-reels-summarizer）
