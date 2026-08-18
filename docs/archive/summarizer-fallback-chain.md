# F18 — 摘要 backend 自動 fallback 鏈

> 建立：2026-07-23。狀態：待實作（brainstorming 定案，acceptance 待簽核後凍結進 feature_list.json）

## 要解的問題

摘要／筆記生成目前固定走單一 backend（production＝GitHub Copilot CLI）。當 Copilot **額度耗盡**（AI credits / premium requests 用完）、rate limit、CLI 不可用或執行錯誤時，整條 pipeline 的摘要步驟直接失敗，使用者傳連結收不到摘要。

要一條「Copilot 失效 → 自動改用下一家 backend，直到某家成功」的容錯鏈，讓摘要不因單一供應商斷流而中斷。

## 範圍界定（為什麼只蓋摘要步驟）

pipeline 有三個 LLM 觸點，只有一個吃 Copilot 額度：

| 觸點 | 用什麼 | 吃 Copilot 額度 |
|---|---|---|
| 轉錄 | faster-whisper（本地） | 否 |
| 視覺分析（幀描述） | Ollama vision（本地） | 否 |
| **摘要／筆記生成** | **summarizer backend（copilot）** | **是 ← F18 蓋這裡** |
| vault_sync 連結 pass（F14） | claude CLI headless（非 copilot） | 否 |

唯一消耗 Copilot 額度的是摘要／筆記生成。視覺分析走本地 Ollama、連結 pass 走 claude，都不受 Copilot 額度影響，故 F18 不擴及這兩處（YAGNI；連結 pass 若要保護是另一個獨立 feature）。

## 決策紀錄（brainstorming 2026-07-23）

- **觸發策略＝反應式 fallback**：不主動查額度 %。原因：Copilot 剩餘額度 % 沒有穩定的非互動取得管道——CLI 只在互動 UI（footer / `/usage` / `/statusline`）顯示，GitHub REST API 無個人層級 Copilot 用量端點（`user/copilot/usage` → 404 實測）。唯一拿 % 的路是 scrape 互動 UI 或架 OTel，脆弱且高維護，踩本專案「用檔案系統就不要用瀏覽器」的教訓。反應式在執行失敗當下 fallback，對使用者透明。
- **fallback 鏈＝Copilot → Codex → Claude → Ollama**：需新寫 Codex summarizer（目前不是 backend）。Ollama 本地保底。
- **無狀態、每請求重試**：每則摘要先試 primary，失敗才往下；不記憶 Copilot 掛掉狀態（額度耗盡時每次多一個快速失敗的 CLI 呼叫，換取零狀態、最簡單）。
- **一般化**：不特判 copilot，任何 primary 失敗都走鏈（production primary 就是 copilot）。
- **接手標註**：`SummaryResult` / `NoteResult` 加 `backend` 欄位；Telegram 端在發生 fallback（接手者 ≠ primary）時標一行「🤖 本則由 <backend> 接手」，正常走 primary 不標。

## 架構（3 個變動）

### 1. 新增 `CodexCLISummarizer`（`app/services/codex_summarizer.py`）

- 鏡像 `CopilotCLISummarizer` 介面：`summarize` / `generate_note` / `generate_post_note` / `generate_threads_note`（皆 async，回傳 `SummaryResult` / `NoteResult`）+ 模組層 `check_codex_cli_available()`。
- 底層呼叫：`codex exec "<prompt>" -o <outfile> --skip-git-repo-check -s read-only -C <tempdir> --ephemeral`（可選 `-m <CODEX_MODEL>`），讀 `<outfile>` 取最終訊息。prompt 過長比照 copilot 寫暫存檔傳入。
- 沿用 `prompt_loader` 的外部模板（prompt 邏輯與其他 backend 共用）。
- system prompt 強化「不要建立檔案、不要使用任何工具、直接輸出文字」（codex 為 agentic，read-only sandbox 為第二道防線）。
- 錯誤（未安裝／逾時／執行失敗）一律回 `success=False` 的結果物件，不拋例外穿透。

### 2. 新增 `FallbackSummarizer`（`app/services/fallback_summarizer.py`）

- 建構時接一條有序的 backend 實例鏈，記住 primary 名稱。
- 實作同 4 個 async 方法。每個方法：依序呼叫各 backend 的對應方法 → `result.success` 為真就設定 `result.backend`（若尚未設）並回傳、log INFO「由 <backend> 產出」；為假則 log WARNING「<backend> 失敗：<error_message>，改試下一家」續試。
- 全鏈皆失敗 → 回傳最後一個失敗結果（`success=False`），**不 crash**。
- 無狀態：每次方法呼叫都從鏈頭重試。

### 3. `summarizer_factory.py` 改造

- 新增 config（`app/config.py`）：
  - `summarizer_fallback_enabled: bool = True`
  - `summarizer_fallback_chain: str = "codex,claude,ollama"`（逗號分隔、有序）
  - `codex_model: str`（Codex 模型，預設用 codex 內建）
- `get_summarizer()`：
  - fallback 關閉 → 維持現行單一 backend 行為（向後相容）。
  - 開啟 → 鏈 = `[primary] + [b for b in fallback_chain if b != primary]`（primary 去重），各 backend 名稱經 builder map 建實例，包成 `FallbackSummarizer` 回傳。
- backend builder map：`{"copilot": ..., "codex": ..., "claude": ..., "ollama": ...}`，集中一處管理避免散落。

### 4. 資料物件與 Telegram 標註

- `SummaryResult` / `NoteResult` 各加 `backend: Optional[str] = None`（四個 summarizer 檔的 dataclass 同步加）。
- `telegram_handler.py` 三個回覆組裝點（`generate_note` / `generate_post_note` / `generate_threads_note` 之後）：`result.backend` 存在且 ≠ 設定的 primary backend 時，在回覆末端加「🤖 本則由 <backend> 接手」。

## 容錯落點說明

現行 factory 在**建構時**查 CLI 可用性才 fallback（只能抓「CLI 沒裝」）。F18 改在**執行時**失敗才 fallback——額度耗盡是 runtime 錯誤，只有執行時抓得到。CLI 沒裝的情況也一併被執行時 `success=False` 接住，行為不退化。

## 測試（TDD）

mock subprocess，不燒真 Codex 額度。

- **FallbackSummarizer**：primary 成功短路（後續 backend 不被呼叫）、primary 失敗換手成功、全鏈皆失敗回最後失敗結果、4 個方法都正確代理、鏈順序與 primary 去重、`backend` 欄位正確標記。
- **CodexCLISummarizer**：`codex exec` 指令建構（含 `-o`/`--skip-git-repo-check`/sandbox）、outfile 解析、`check_codex_cli_available()`、錯誤 → `success=False`。
- **factory**：依 config 組出正確鏈、fallback 關閉時單 backend、primary 去重。
- **telegram 標註**：fallback 發生時加標註、正常不加（可用既有 handler 測試風格）。
- **一次真實 e2e**（手動，宣告 passing 前）：模擬 Copilot 失效（或直接把 primary 設 codex）確認 codex 真的產得出摘要並入庫。

## Acceptance（待 Ryan 簽核後凍結進 feature_list.json）

> SUMMARIZER_BACKEND=copilot 且 Copilot 摘要失敗（額度耗盡／rate limit／CLI 不可用／執行錯誤）時，摘要自動依序 fallback Codex → Claude → Ollama 直到某家成功；log 顯示每次 fallback 原因與最終接手 backend；全鏈皆失敗時回傳最後失敗結果且不 crash；新增 CodexCLISummarizer 與現有三家介面一致（summarize / generate_note / generate_post_note / generate_threads_note）；FallbackSummarizer 無狀態每請求重試；SummaryResult/NoteResult 帶 backend 欄位，Telegram 在 fallback 發生時標註接手 backend；單元測試 mock 覆蓋鏈順序／短路／全滅與 Codex 指令建構解析；一次真實 e2e 確認 codex 產出摘要。

## 不做（範圍外）

- 不主動查詢 Copilot 額度 %（無穩定非互動管道）。
- 不加 in-memory 冷卻或持久化 Copilot 失效狀態（無狀態設計）。
- 不擴及 vault_sync 連結 pass 與視覺分析的 fallback（不吃 Copilot 額度）。
