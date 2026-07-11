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
2. **F7 NotebookLM 確認壞損**：UI 改版找不到 'Add source' 按鈕——log（20:02:43）有現行按鈕清單，照著更新 notebooklm_sync.py 的 selector；建議順便把「emoji-keyboard」等雜訊按鈕過濾掉
3. 依序重驗 F2（圖文）、F3（Threads）、F4（重複 URL，把同一條 reel 再傳一次最快）——各傳一條真實連結即可
