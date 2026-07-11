# Session Handoff

> 最後更新：2026-07-11（第六場：F14/F5/F8 驗收 passing、F2 拍板等上游）

## 這個 session 做了

- **F5 passing**：三 backend 實測切換（claude/sonnet、ollama/qwen3:14b、copilot restore），各自 log + 摘要成功證據；verifier 7/7 pass。.env 已 restore copilot
- **F8 passing**：失敗寫入（id 25/26/27）+ 排程器啟動 log（RETRY_ENABLED=true 短暫開啟實抓）+ 沙盒重試 1→2→3→abandoned 全鏈。**RETRY_ENABLED 已關回 false**——app.db 有 27 筆 pending（1–2 月舊案 22 筆 + 今天 5 筆含重複），一開就每小時整批重跑；怎麼清等 Ryan 拍板：a) 清雜訊留舊案給 retry 補收 b) 全標 abandoned c) 維持關閉
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

1. 剩餘 failing：**F11**（pydantic V2 遷移）、**F12**（下載失敗錯誤訊息可行動化，TDD）、**F15**（CDP 不可用時快速降級，TDD）、F2（卡上游）。M3 的 F1–F8 重驗除 F2 外全綠
2. Ryan 拍板 failed_tasks 27 筆 pending 清法後，決定是否常開 RETRY_ENABLED（retry 路徑另一觀察：_retry_full_process 只同步 Roam，沒接 vault_sync 也沒做視覺分析——與主 pipeline 漂移，若常開 retry 前值得先對齊，屆時加 feature）
2. F12 做的時候順便把 instaloader#2710 這類上游壞損映射成「IG 改版，等上游修復」訊息（現在回 'Fetching Post metadata failed' 對使用者不可行動）
3. vault 端未 commit：clippings 新筆記＋INDEX＋DEVLOG 更新，由 Ryan 的 vault sync 習慣處理（PRD「不做」明訂 vault git 不歸本服務管）
