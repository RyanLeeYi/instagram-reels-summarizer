# Vault Sync — 摘要整併知識庫（取代 NotebookLM）

> 2026-07-11 brainstorming 定案。Ryan 拍板：換掉 NotebookLM；圖片進、影片不進；LLM 連結 pass 要做。

## 目標

摘要 pipeline 的入庫終點從 NotebookLM（Playwright UI 自動化，UI 改版就壞）改為直接寫入 Obsidian vault（純檔案操作），並與既有知識庫建立 `[[連結]]`。

## 行為規格

### F14-a 寫入 clippings

- Reels / IG 圖文 → `<VAULT_PATH>/clippings/ig-reels/`；Threads → `<VAULT_PATH>/clippings/threads/`
- 檔名沿用現行：`IG Reels - YYYY-MM-DD HHMMSS - <標題>.md`、`Threads - YYYY-MM-DD HHMMSS - @<作者>.md`（標題清理沿用 roam_sync 規則 + 保留 `@`）
- 檔首 frontmatter：`updated`（ISO 日期）、`tags`（`[clipping, ig-reels|threads]`）、`summary`（一句話，取自「## 摘要」首行，取不到用標題）、`source`（原始連結）
- 本體 = summarizer 產出的 Markdown 原樣

### F14-b 圖片進 assets

- 圖文貼文的圖片 copy 到 `<VAULT_PATH>/assets/clippings/<sha256 前 12 碼><原副檔名>`
- 筆記末尾附「## 圖片」段，相對連結 `../../assets/clippings/<hash>.jpg`
- 影片一律不進 vault

### F14-c INDEX 同步（vault 強制規則 #1）

- 寫檔同一動作內更新 `clippings/INDEX.md`：在同組（`- ig-reels/` 或 `- threads/`）最後一行後插入 `- <子資料夾>/<檔名> — <summary 一句話>`；找不到同組就 append 檔尾
- 更新 INDEX frontmatter 的 `updated:` 日期

### F14-d LLM 連結 pass

- 寫入成功後，headless `claude -p`（stdin 傳 prompt、無工具，同 roam_sync 的 CLI 呼叫模式）：輸入 = 新筆記全文 + `knowledge/`、`learning/`、`projects/` 三份 INDEX 內容；要求輸出**只有** 0–5 行 `- [[筆記名]] — 為什麼相關`，無相關輸出 `NONE`
- Python 端驗證輸出行格式（`- [[` 開頭才收），通過才在筆記尾 append「## 相關筆記」段——LLM 永遠不直接改檔
- `VAULT_LINK_ENRICH=false` 或 CLI 失敗 → 跳過，筆記照樣落地

### F14-e 接線與容錯

- `telegram_handler` 三個 NotebookLM 呼叫點換成 `vault_sync.upload_reel/upload_post/upload_threads`（介面形狀對齊 NotebookLMSyncService，另加 `source_url` 參數）
- Telegram 回覆的 NotebookLM 連結段換成「`📚 知識庫`＋換行＋檔名」（與 Roam 段同風格；2026-07-11 驗收時 Ryan 確認排版）
- vault 寫入任何失敗：log ERROR、回傳 failure result、不擋 Roam 儲存與 Telegram 回覆
- NotebookLM 程式碼保留、`NOTEBOOKLM_ENABLED` 預設改 false

### Config

| 變數 | 預設 |
|------|------|
| `VAULT_SYNC_ENABLED` | `true` |
| `VAULT_PATH` | `C:\Users\user\OneDrive\Desktop\Obsidian` |
| `VAULT_LINK_ENRICH` | `true` |

## 驗收（= feature_list F14）

1. `pytest tests/test_vault_sync.py` 全過（tmp 假 vault：命名/frontmatter/INDEX 插入位置/圖片 hash 與連結/連結段格式驗證/失敗降級）
2. e2e：傳一則真連結，vault 出現新筆記 + INDEX 有條目 +（若有相關）相關筆記段；Telegram 回覆含知識庫檔名

## 不做

- vault git commit/push（檔案落地即可，git 由 Ryan 的 vault session 管）
- 歷史 roam_backup 回填（另案）
- Roam 同步路徑改動（維持現狀；roam-sync 匯入遇同名檔照 note-intake 去重）
