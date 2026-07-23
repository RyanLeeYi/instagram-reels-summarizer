# Session Handoff

> 最後更新：2026-07-23（第八場：F18 fallback 鏈**只完成設計**，待簽核後實作）

## 這個 session 做了（2026-07-23 第八場）

- **F18 設計定案、未實作**：`docs/prd/summarizer-fallback-chain.md`（commit efc7310）。需求源自 Ryan「Copilot 沒流量時自動切 Codex/Claude」
  - ⚠️ **F18 尚未寫進 feature_list.json**——照 harness 規矩 acceptance 要 Ryan 簽核才凍結。spec 最後一段就是待簽核的 acceptance
  - **關鍵查證結論**：Copilot 剩餘額度 % 沒有非互動取得管道（CLI 只在互動 UI 顯示；`gh api user/copilot/usage` → 404）。原需求「剩 <5% 就切」不可行 → 改**反應式 fallback**（執行失敗當下換手）。詳見 vault DECISIONS D6
  - **設計摘要**：新增 `CodexCLISummarizer`（`codex exec -o <file> --skip-git-repo-check -s read-only`）+ `FallbackSummarizer` 包裝器（無狀態、每請求從鏈頭重試）+ factory 組鏈（`SUMMARIZER_FALLBACK_ENABLED` / `SUMMARIZER_FALLBACK_CHAIN`）。鏈＝Copilot→Codex→Claude→Ollama，一般化不特判 copilot
  - **容錯落點改變**：現行 factory 是「建構時」查 CLI 可用性才 fallback（只抓 CLI 沒裝）；F18 改「執行時」失敗才 fallback（額度耗盡是 runtime 錯誤）
  - **結果物件加 `backend` 欄位**，Telegram 僅在 fallback 發生時標「🤖 本則由 <backend> 接手」
  - **範圍界定**：pipeline 只有「摘要／筆記生成」吃 Copilot 額度（視覺分析走本地 Ollama、F14 連結 pass 走 claude 且失敗已優雅降級）→ F18 不擴及那兩處

## 之前的 session 做了（第七場 2026-07-23）

- **F17 passing**：Threads `/share/<code>` 分享短連結支援。症狀＝`threads.com/share/BAUrkxxv3Q/` 完全處理不了。根因：兩層 URL 辨識都不認 `/share/` 格式——①`telegram_handler.THREADS_URL_PATTERN` 不匹配 → `_extract_threads_url` 回 None → 訊息掉到「無法辨識」提示，根本沒進 Threads 流程；②`ThreadsDownloader.validate_url` 也拒收；且 share code 是不透明轉址 token（非 post_id），必須先跟隨 302 才拿得到 `/@user/post/<id>`。
  - 修法：threads_downloader 加 `/share/` pattern + `SHARE_URL_PATTERN` + `is_share_url()` + `_resolve_share_url()`（跟隨轉址、去 query、失敗降級回原 url）；`download()` 對 share 連結先正規化再 `extract_post_id`。telegram_handler `THREADS_URL_PATTERN` 加 `share` 分支。
  - 證據：TDD（tests/test_threads_share_url.py 10 tests RED→GREEN），全套件 **46 passed**；真實 e2e：`share/BAUrkxxv3Q` → `@dustin_gmat/post/DbHiGmWD10O`。Codex review 無缺陷。
  - ⚠️ 服務由 mission-control 管理（`reels-summarizer`, port 8001），改動要生效需經中台重啟。

## 之前的 session 做了

- **F5 passing**：三 backend 實測切換（claude/sonnet、ollama/qwen3:14b、copilot restore），各自 log + 摘要成功證據；verifier 7/7 pass。.env 已 restore copilot
- **F8 passing**：失敗寫入（id 25/26/27）+ 排程器啟動 log + 沙盒重試 1→2→3→abandoned 全鏈
- **failed_tasks 已清雜訊（Ryan 拍板方案 a）**：27 pending → 14（7 筆後來成功過標 success、6 筆同 shortcode 重複標 abandoned，只 UPDATE 不 DELETE，備份在 scratchpad app.db.bak-20260711-233150）。**RETRY_ENABLED=true 已常開**，排程器 23:32:25 啟動、每小時整批重試 14 筆——summarize 類 5 筆大概率補收成功；4 筆 /p/ 貼文卡上游會重試 3 次後 abandoned＋通知（上游修復後手動重傳）
- **F15 新增（failing）**：CDP Chrome 未開時 cookies 刷新空等 180s CDP timeout 才降級——F8 沙盒實測發現，待做快速降級

- **F14 收官**：Ryan 傳 Threads 連結（@oneday0013/DajnyLDIKbt 重跑）走 bot 全程 e2e——vault 筆記落地、INDEX 同步、連結 pass 加入 [[Redis]]（真實筆記非幻覺）、NotebookLM 未執行、Ryan 實收「📚 知識庫」段。acceptance-verifier 逐條驗收 8/8 pass → **F14 passing**
- PRD 排版描述對齊實作（📚 知識庫段為換行風格，Ryan 確認 OK）
- **F2 拍板：選 A 等上游**。複現確認 `/p/DaSd-YuD_x8` 失敗根因＝instaloader#2710（session 載入成功仍 `Fetching Post metadata failed`；issue OPEN 零留言、PyPI 無新版 4.15.2 即最新）。該 URL 已入 failed_tasks，上游修好後可重跑

## 做到一半 / 已知未修

- **F2 等上游**：盯 [instaloader#2710](https://github.com/instaloader/instaloader/issues/2710)；有新版就 `pip install -U instaloader` 重測 `/p/DaSd-YuD_x8`。若久等不修，備案 B（iPhone API `media/{pk}/info/` fallback，F13 session 已就緒）隨時可啟動
- F7 NotebookLM 已停用（NOTEBOOKLM_ENABLED=false，F14 取代）；程式碼保留，檔案上傳路徑修了但未實測——除非重新啟用，否則不用管
- httpx INFO log 印完整 bot token（與 offer-radar 同病）；token 輪替時兩支一起
- pydantic V2 deprecation warnings ×34（F11）

## 下一步（具體到可直接動手）

0. **F18 續行（最優先）**：請 Ryan 簽核 `docs/prd/summarizer-fallback-chain.md` 末段 acceptance → 寫進 feature_list.json 標 failing → TDD 實作（先 FallbackSummarizer 的鏈行為測試，再 CodexCLISummarizer，最後 factory 組鏈；mock subprocess 不燒真 Codex 額度）。Ryan 曾問「要不要順便保護 F14 連結 pass」，已答不建議（走 claude 非 copilot、失敗已優雅降級），要做就開 F19 分開
1. 其餘 failing：**F11**（pydantic V2 遷移）、**F12**（下載失敗錯誤訊息可行動化，TDD）、**F15**（CDP 不可用時快速降級，TDD）、**F16**（retry 路徑對齊主 pipeline）、F2（卡上游）。M3 的 F1–F8 重驗除 F2 外全綠
2. 首次排程觸發約 2026-07-12 00:32——看 log「開始執行失敗任務重試」確認真實定時觸發（可補進 F8 evidence 補齊 R4）；預期一波 Telegram 通知
3. retry 路徑與主 pipeline 漂移：_retry_full_process 只同步 Roam，沒接 vault_sync、沒做視覺分析、/p/ 貼文也走 reel 下載路徑——retry 已常開，值得盡快加 feature 對齊
2. F12 做的時候順便把 instaloader#2710 這類上游壞損映射成「IG 改版，等上游修復」訊息（現在回 'Fetching Post metadata failed' 對使用者不可行動）
3. vault 端未 commit：clippings 新筆記＋INDEX＋DEVLOG 更新，由 Ryan 的 vault sync 習慣處理（PRD「不做」明訂 vault git 不歸本服務管）
