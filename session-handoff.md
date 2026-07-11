# Session Handoff

> 最後更新：2026-07-11

## 這個 session 做了

- 修好荒廢 5 個月的下載壞損：yt-dlp 2026.01.19 → 2026.07.04（根因是版本跟不上 IG 改版，非 cookies；單變因驗證：同 cookies 舊版失敗新版成功），服務已經中台重啟
- 追補 harness：CLAUDE.md、init.ps1、feature_list.json（F1–F11，重驗基準）、docs/ARCHITECTURE.md、本檔；補裝 pytest（原本 tests/ 跑不了）→ 11 passed
- vault 建立 `projects/2026-01-reels摘要/`（PLAN / DEVLOG / DECISIONS）

## 做到一半 / 已知未修

- **F1 端到端重驗**：等 Ryan 對 bot 重傳 reel 連結（失敗任務不自動重試，RETRY_ENABLED=false）
- cookies.txt 無 sessionid：公開內容 OK，登入牆內容會失敗（F2 風險）——需要時從瀏覽器重新匯出
- httpx INFO log 印完整 bot token（與 offer-radar 同病）；token 輪替時兩支一起
- pydantic V2 deprecation warnings ×30（F11）

## 下一步（具體到可直接動手）

1. ~~F1 重驗~~ ✅ 2026-07-11 20:04 e2e 全通（F1、F6 隨之 passing）
2. ~~F7 NotebookLM~~ ✅ 已修並實證（UI 改版成 tab 佈局，_click_add_source 先切「來源」tab；20:02 失敗的摘要已補傳，notebook 1 個來源）。**待確認**：檔案上傳路徑同修但未實測——下支 reel 的 log 看 `_upload_files_source` 有沒有過
3. ~~F3 / F4 重驗~~ ✅ 2026-07-11 20:22–20:25 實測過（F3 走 Googlebot SSR fallback；F7 修復在正式流程也驗證了）
4. ~~F13~~ ✅ passing：cookies+UA 由 CDP Chrome 自動供應，Ryan 已登入，test_login 驗證過（DECISIONS D5）
5. **F2 卡上游**：instaloader 4.15.2 的 Post.from_shortcode graphql 被 IG 改版打壞（[instaloader#2710](https://github.com/instaloader/instaloader/issues/2710)，2026-07-06 開）。選項：A 等上游修版（每天 `pip install -U instaloader` 試一次或盯 issue）；B 自建 fallback——用已認證 session 打 iPhone API `api/v1/media/{pk}/info/`（shortcode→media_id 標準轉換），繞過 graphql。**等 Ryan 拍板再動**
6. F12：把 instaloader 未登入的 NoneType 錯誤映射成可行動訊息（TDD）
7. 修好後注意：instaloader venv 已升 4.15.2；session 檔已存 temp_videos/session-*（下次啟動直接載入不再打 test_login）
