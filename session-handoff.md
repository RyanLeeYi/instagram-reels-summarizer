# Session Handoff

> 最後更新：2026-08-31（F26 `/backend` 切換摘要 backend、F28 其 inline keyboard 皆 passing 歸檔；主檔 failing：F21（歷史紀錄）、**F27 未簽核**——init.ps1 煙霧測試 pip 以 cp950 讀 requirements.txt 中文註解失敗，8/27 綠 8/31 紅，待查是 pip 版本還是 locale）

## 2026-08-31 摘要

- F26：`/backend` 無參數查詢、`/backend <name>` 即時切換（只存記憶體，重啟回 .env），`describe_summarizer()` 依實例型別回報實際生效；factory fallback 分支同步回寫 settings。
- F28：`/backend` 無參數回覆帶三顆按鈕（使用中／不可用標記），`_switch_backend` 為文字與 callback 共用；pattern `^backend:` 註冊在通用 CallbackQueryHandler 之前。
- 測試基準 130 passed + 2 failed（F27）。服務由中台重啟後已線上驗證 `/backend`。
- 已知：F27 兩條紅測試不是 F26/F28 造成；F26 未授權回覆少一個 emoji 前綴（hook 擋新字串 emoji），授權邏輯相同。


## 收官狀態（2026-08-27，agent-brief 無人看管 session）

- **F24 passing、F25 passing**，各 1 輪獨立驗收即過、無 finding。兩條原文已搬進 `docs/archive/features.jsonl`（累計 23 條），主檔只剩 F21。
- 全套 pytest **115 → 121 passed**（新增 6 條：F24 四條、F25 兩條 host parametrize）。
- **主檔剩餘 failing 只有 F21**——已裁決、`superseded_by: F22`，當歷史紀錄留著，不再推進。

### F24 的關鍵結論：告警的「送達」要由最外層那個人負責定義

`IGCookieProvider` 的「同一段斷線只告警一次」配額，是**看 callback 有沒有正常回來**決定的。所以配額正不正確，取決於 `app/main.py` 那個扇出函式肯不肯在失敗時拋出去。原實作對每個 `chat_id` 各自 try/except 又從不 re-raise，等於對 provider 謊報送達。

修法是抽出 `make_ig_alert_callback(bot, chat_ids)`：**`delivered == 0` 就 raise**，至少一個成功才安靜返回。**改這塊時不要把例外吞回去**——吞掉的那一刻，bot token 失效／`allowed_chat_ids` 設錯或為空／全域斷網這三種情況就會回到「一次都沒人收到卻永遠不再重試」。

`allowed_chat_ids` 為空是 acceptance 明列的情境，走的是同一條路：沒有任何人收得到，就不算送達。

### F25：F20 只修了一半，另一半在煙霧測試階段

`init.ps1` 現在在 `pytest` 之後檢查 `$LASTEXITCODE`，非零就印 `[smoke-test]` 說明並 `exit 1`。**`[smoke-test]` 這個標記刻意用 ASCII**——兩個 PowerShell host 都以 cp950 輸出中文，測試端用 utf-8 收會變亂碼，中文斷言抓不到（與檔頭 F20 那條同一個坑）。

`tests/test_init_script.py` 的 F25 測試是**真的跑一次 `init.ps1`**，不是比對腳本內容；離線建 venv 的手法是把主 venv 的 site-packages 用 `.pth` 掛進去，讓 `PIP_NO_INDEX` 下的 `pip install pytest` 變成「already satisfied」。要改這支測試前先讀那段 docstring。

### F21 仍會出現在 dispatch 清單（狀態未變）

`signed_off: true` + `failing` 的組合讓它每次都被列成「待做」。要讓它消失需要 harness 新增終態值，那需要 Ryan 認可，本 session 同樣沒動。


## 收官狀態（2026-08-23，agent-brief 無人看管 session）

- **F12 passing**（2 輪獨立驗收）、**F15 passing**（1 輪即過）、**F23 passing**（1 輪即過）。三條原文已搬進 `docs/archive/features.jsonl`，主檔只剩 failing。
- 全套 pytest **115 passed**；`.\init.ps1` 實跑 **exit 0**。已 commit + push（`79398fd`），`origin/main` 與 HEAD 同步。
- **主檔剩餘 failing：F21（已裁決，維持歷史紀錄）、F24、F25（兩條都待 Ryan 簽核）。**

### F23 的關鍵結論：metathreads 不是版本問題，是根本無解

`metathreads` **任何版本都裝不起來**——PyPI 最高 0.0.4，而 0.0.4 硬釘 `httpx==0.24.1`，與本專案 `httpx>=0.25.0`（python-telegram-bot 需要）直接衝突，pip 回 `ResolutionImpossible`。所以原草案的方向 (a)「降版釘 0.0.4」**在技術上不可行**，不是取捨問題。已採方向 (b) 移除。

連帶要知道的坑：`threads_enabled` 預設是 **true**，而 `_get_api()` 缺套件時丟 `RuntimeError`，`_download_sync` 原本直接把它變成硬失敗，**跳過了本來就不需要該套件的 Googlebot SSR / Web Scraping 兩條 fallback**。已改成降級走 fallback——**不要把這段改回去**，否則全新環境的 Threads 連結會靜默失敗。

### F12 修正時踩到的兩件事（改這塊前先讀）

1. **acceptance 寫「Telegram 回覆與 log」是並列要求**。原實作只有貼文路徑記 log，Reel 路徑（本專案主流程）完全靜默，維運者看 log tail 看不到登入態失效。現在兩個 login-failure 分支都走 `_login_required_result()` 統一出口，log 與回覆用同一則訊息——**新增分支時記得走這個出口**，不要再各自 return。
2. **「只告警一次」的配額只有在訊息真的送出去之後才算用掉**。原實作在檢查 callback 是否存在**之前**就設 `_alert_sent = True`，管道還沒接上時偵測到斷線就會永久燒掉配額。已改成 `await callback(...)` 成功回來才消耗。

### 新增兩條待簽核

- **F24（P3）**：`app/main.py:68-73` 的 `_alert_ig_disconnected` 對每個 `chat_id` 各自 try/except 且**從不重新拋出**，所以上面第 2 點的修正在「所有 chat_id 都送失敗」時仍會被誤判成已送達、不再重試。等於一次都沒人收到卻不會補送——就是 2026-07-12 事故的另一種形狀。
- **F25（P4）**：`init.ps1` 的煙霧測試失敗時仍無條件印 `init OK`（F20 只修了 pip install 階段）。

### F21 已裁決，但會一直出現在 dispatch 清單

Ryan 2026-08-23 回覆「直接把影片給 any CLI 看，不需要逐幀分析」＝否決 frame-per-process、確認 F22（整支影片一次分析，已 passing）就是採用方案。已維持 `failing` + `superseded_by: F22` 當歷史紀錄。**但它 `signed_off: true` 且 `failing`，所以每次 dispatch 都還是會被列成「待做」**——要讓它消失需要 harness 新增終態值，那需要 Ryan 認可，本 session 沒動。


## 收官狀態（2026-08-11）

- **F22 已正式 passing**：Claude Code canonical review 最終 `integrity=true`、無功能缺陷；前兩輪 reviewer HIGH（泛用例外 fallback、單檔 workspace 防跨請求讀取）已 FIX，唯一 MEDIUM「agy missing 測試缺口」已補。
- Claude Sonnet acceptance verifier `integrity=true`，R1–R8 全 pass，明確建議 passing；targeted **13 passed**、全套 **90 passed**。
- 真實 isolated hardlink + `--sandbox` MP4 smoke：**14.9s、1347 字**可辨識摘要。F21 維持 failing，`superseded_by: F22`。
- 剩餘 failing：**F11、F12、F15、F20、F21**；依順序下一條是 **F11**。

## 這個 session 做了（2026-08-10：F22 Antigravity CLI native video）

- **F22 實作完成，但為補 Harness 流程已退回 failing**：Ryan 於 2026-08-11 明確同意「先補流程」，視為對既有 F22 acceptance 原文的正式簽核；acceptance 不改寫。Reel 視覺分析新增 `VISUAL_ANALYZER_BACKEND=antigravity`。成功路徑對完整 MP4 只啟一個 `agy`，不先抽 8–10 幀；失敗才降級原本 FFmpeg + Ollama frame pipeline，fallback 明確不再呼叫 agy。
- 新增 `app/services/antigravity_visual_analyzer.py` 與 workspace custom agent `.agents/agents/reels-vision/agent.md`。agent 只允許 `view_file`、`commandExecutionPolicy: off`；prompt 把影片內文字視為 untrusted content，只描述不執行。
- 關鍵 discovery：`agy -p` 若沿用錯的 active project，會讀到別的 workspace 或 tool-call timeout；固定用**絕對 media path + `--add-dir <media parent>`**後，headless image/video 都能穩定讀取。
- Windows 實測再抓到 stdout encoding：agy 回 UTF-8，但 Python subprocess 預設 CP950，中文/符號會 `UnicodeDecodeError`；adapter 已釘 `encoding="utf-8", errors="replace"`。
- 真實 smoke：Python adapter 讀 `temp_videos/73d5cde3_video.mp4` 成功回 **1343 字**視覺摘要，辨識 Data Analyst / Data Scientist / ML Engineer / GenAI Engineer 及 SQL、Power BI、PyTorch、LangChain、Vector Databases 等畫面文字。
- 現有技術證據：targeted **11 passed**；全套 **88 passed**；`py_compile`、`git diff --check` 通過。先前 Gemini code review=`NO_FINDINGS`、fresh Gemini verifier=7/7 PASS，只保留為補充 evidence，**不再當成 HARNESS canonical checker**。2026-08-11 補 canonical review：`codex exec review --uncommitted --ephemeral` 有啟動且自行重跑 targeted 11 passed，但 180s 內無最終 verdict → 無效；依 `/codex-review` skill fallback 到 headless Claude reviewer，又因 workspace 尚未接受 Claude Code trust dialog 而 180s timeout、無 verdict。下一層依 skill 只能由 Ryan 在 Claude Code 手動輸入 `/code-review`，agent 不可用 Bash 繞過。故 F22 維持 failing，`/codex-verify` 尚未跑。
- **F21 保留 failing 並 `superseded_by: F22`**：逐幀各啟一個 agy process 雖可行，但單次 tool-call 可超過 45s，8–10 次會傷害專案 `<5 分鐘` 成功指標，不進 production path。
- 本機 `.env`（gitignored）已設 `VISUAL_ANALYZER_BACKEND=antigravity`、agent `reels-vision`、model `gemini-3.6-flash-high`、timeout 120s；**要由 mission-control 重啟 `reels-summarizer` 後才載入新 runtime 設定**。

## 這個 session 做了（2026-08-10：F2 instaloader 上游修版重驗）

- **F2 正式 passing**：venv `instaloader` 4.15.2 → 4.15.3；`requirements.txt` 最低版同步升為 `instaloader>=4.15.3`。
- 真實重現：原 blocker shortcode `DaSd-YuD_x8` 現在成功回 `post_carousel`、8 張圖、caption 699 字；另用歷史單圖 `DU2HrdsDs_D` 成功回 `post_image`、1 張 162254-byte 圖、caption 618 字。
- 兩案仍會看到 IG high-quality endpoint 的 `login_required` warning，但 Instaloader 4.15.3 能取得可用 metadata 與圖片，不再讓整體下載失敗；**不要因 warning 又回頭自建 iPhone API fallback，除非未來成功路徑真的再次壞掉**。
- 全套 `.venv\\Scripts\\python.exe -m pytest tests -q`：**77 passed**。`pip check` 仍因既有 `metathreads 0.0.4` 相依衝突失敗，屬 F20/環境舊帳，非本次回歸。
- 最終 acceptance 已由 Ryan 2026-08-10 直接黑箱實測：從 Telegram bot 傳公開 IG 圖文貼文後**成功收到圖片視覺分析 + caption 整合摘要**，補齊整條使用者路徑。自動 verifier 狀態如實保留：Claude fresh verifier 300s timeout、空 report 且 repo 無變更；Codex fresh-context fallback 因 usage limit（重置 2026-08-16 09:32）無法執行。本條以使用者實際 operational acceptance 收官。

## 這個 session 做了（2026-08-03 第九場）

- **F16 passing**：retry 路徑對齊主 pipeline。修法是**委派**不是複製——新增 `TelegramBotHandler.process_url()` 作為型別分流的**唯一事實來源**，`handle_message`／reprocess callback／retry 三條路徑共用；handler 改回傳 `ProcessResult`（`app/bot/process_result.py`）並支援 `retry_mode`；`retry_job` 刪掉自建的簡化 pipeline，由 `main.py` 注入 handler 後委派。tests 65→**77 passed**，codex-verify 5/5 pass
  - ⚠️ **retry_mode 的三個約束**（都是 codex review 抓出來的，改動時別破壞）：①重試時不得再寫 failed_task（否則每小時長一筆 pending）②重試時 Roam 同步失敗要回 `fail(SYNC)`，不能回 ok（否則任務被標 success 就再也不同步）③`save_processed_url` 已改 **upsert**——委派後同一 URL 會重跑，舊的純 insert 會撞 unique 然後被誤報成下載失敗
  - `THREADS_ENABLED=false` 時 threads URL 現在明確拒收，不再掉進 IG 貼文下載器

- **F19 passing**：CDP Chrome 生命週期收斂（停止時關掉自己啟動的、啟動時收養上一輪殘留）。PRD `docs/archive/chrome-cdp-lifecycle.md`（Ryan 當場簽核 acceptance）；新模組 `app/services/chrome_lifecycle.py`；`notebooklm_sync._start_chrome_cdp` 成功後 `mark_owned(pid)`；`main.lifespan` startup 收養、shutdown 關閉。TDD 19 tests，全套 **65 passed**（原 46）
  - **擁有權規則**：`_is_cdp_running()` 已為 true → 不擁有（使用者自己開的，絕不關）；自己啟動成功 → 擁有。狀態放**模組層級**＋持久化到 `~/.chrome-cdp-notebooklm/.owned-by-reels.json`（cookies 刷新每次 new 一個 service 實例，放 instance 會歸零；服務被強制 kill 時 lifespan 不跑，殘留只能靠下次啟動回收）
  - **收養而非殺掉重開**：殘留的 Chrome 已登入且 session 是熱的，殺掉只是 15 秒後再開一個
  - **收尾預算是關鍵**：原始實作耗時 **20.12 秒**（每個 CDP HTTP 呼叫 2s 逾時 × 多 target ＋輪詢）> 中台 grace 10 秒 → 行程在清狀態檔前被強殺。改總預算制（HTTP 逾時 1s、graceful 60%／輪詢 40%、強殺也綁預算），修後 6.06s
  - ⚠️ **改這塊時務必守住的反例**（codex review P1）：**不可以**為了防殘檔而在關閉「之前」刪狀態檔——中途被強殺會變成「Chrome 活著但沒狀態檔」，下次啟動當成使用者手開的，永遠收不回來。留下的殘檔反而自癒（判定表對 port 已死的殘檔會清掉）。已有測試 `test_state_file_survives_when_chrome_does` 釘住
- **F20 新增（failing）**：`init.ps1` 在 `pip install metathreads>=1.0.0` 失敗（PyPI 已無此套件）時仍 exit 0 並印 `init OK`——全新環境恢復失敗會被誤判成功

## 之前的 session 做了（2026-07-23 第八場）

- **F18 設計定案、未實作**：`docs/archive/summarizer-fallback-chain.md`（commit efc7310）。需求源自 Ryan「Copilot 沒流量時自動切 Codex/Claude」
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

-1. **未觀察**：F16 尚未經歷一次真實的每小時排程重試（目前 14 筆 pending 多數卡 instaloader#2710）。下次排程觸發時看 log 確認委派路徑實跑。另 **Copilot CLI 目前在本機找不到**（log：`Copilot CLI 未找到 → fallback 到 Ollama`），F18 的動機正在發生
0. **F18 續行**：請 Ryan 簽核 `docs/archive/summarizer-fallback-chain.md` 末段 acceptance → 寫進 feature_list.json 標 failing → TDD 實作（先 FallbackSummarizer 的鏈行為測試，再 CodexCLISummarizer，最後 factory 組鏈；mock subprocess 不燒真 Codex 額度）。Ryan 曾問「要不要順便保護 F14 連結 pass」，已答不建議（走 claude 非 copilot、失敗已優雅降級），要做就開 F19 分開
1. 其餘 failing：**F11**（pydantic V2 遷移）、**F12**（下載失敗錯誤訊息可行動化，TDD）、**F15**（CDP 不可用時快速降級，TDD）、**F16**（retry 路徑對齊主 pipeline）、F2（卡上游）。M3 的 F1–F8 重驗除 F2 外全綠
2. 首次排程觸發約 2026-07-12 00:32——看 log「開始執行失敗任務重試」確認真實定時觸發（可補進 F8 evidence 補齊 R4）；預期一波 Telegram 通知
3. retry 路徑與主 pipeline 漂移：_retry_full_process 只同步 Roam，沒接 vault_sync、沒做視覺分析、/p/ 貼文也走 reel 下載路徑——retry 已常開，值得盡快加 feature 對齊
2. F12 做的時候順便把 instaloader#2710 這類上游壞損映射成「IG 改版，等上游修復」訊息（現在回 'Fetching Post metadata failed' 對使用者不可行動）
3. vault 端未 commit：clippings 新筆記＋INDEX＋DEVLOG 更新，由 Ryan 的 vault sync 習慣處理（PRD「不做」明訂 vault git 不歸本服務管）
