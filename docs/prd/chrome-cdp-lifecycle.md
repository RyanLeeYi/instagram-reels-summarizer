# F19：CDP Chrome 生命週期收斂（停止時收掉、啟動時清殘留）

> 建立：2026-08-03。狀態：**acceptance 已於 2026-08-03 經 Ryan 簽核並凍結進 feature_list.json（F19）**；實作完成，驗收進行中。

## 要解的問題

服務為了 IG cookies 刷新（F13）與 NotebookLM（F7，現已停用）會**自動啟動一個 Chrome**（`_start_chrome_cdp`，獨立 profile `~/.chrome-cdp-notebooklm` + remote debugging port 9222）。這個 Chrome 從來沒有人關：

- `_chrome_process` 有記下 PID，但沒有任何路徑 terminate 它
- `_close_browser()` 明訂「只斷 CDP 連線、不關瀏覽器」
- 啟動者是 `ig_cookie_provider._fetch_from_cdp()` 每次現場 `NotebookLMSyncService()` 建一個，用完即丟——**PID 握把每次都遺失**
- Chrome 以 `DETACHED_PROCESS` 啟動，不在服務的 process tree 內，所以 mission-control 的 `kill_tree` 也收不到

結果：服務停掉後，這個 Chrome 視窗留在桌面上變孤兒。

而服務被強制 kill（中台逾時、工作管理員、當機）時 lifespan 根本不會跑，所以「停止時關閉」不可能是完整解——**必須配一個啟動時的殘留回收**，否則每次非正常結束都留一個孤兒。

## 範圍

**做**：
1. 服務停止（lifespan shutdown）時，關掉**本服務啟動的**那個 CDP Chrome
2. 服務啟動（lifespan startup）時，偵測上一輪殘留的 Chrome 並**收養**（見下方決策）

**不做**：
- 不做「每次用完就關」——IG session 的活性靠這個真瀏覽器維持（F13 原理），常關會傷 session 新鮮度並讓每則連結多付冷啟動成本
- 不碰使用者自己開的任何 Chrome（見下方擁有權規則）
- 不改 F13 cookies 刷新的既有行為

## 設計

### 1. 擁有權（關鍵約束）

只關「自己啟動的」。判斷點在既有的 `_launch_browser()`：

- `_is_cdp_running()` 為 true → Chrome 早就在跑（可能是 Ryan 手動開來登入 IG／Google 的）→ **不擁有，不得關閉**
- `_is_cdp_running()` 為 false 且 `_start_chrome_cdp()` 成功 → **擁有**，記下 PID

擁有權狀態必須放**模組層級**（不是 instance 屬性）——cookie 刷新每次 new 一個 `NotebookLMSyncService()`，放 instance 等於每次歸零。

### 1b. 擁有權要跨行程存活：狀態檔

啟動時要分辨「殘留 vs Ryan 手開的」，記憶體裡的旗標不夠——上一個行程已經死了。用狀態檔 `~/.chrome-cdp-notebooklm/.owned-by-reels.json`（放 profile 目錄內，與該 Chrome 同生共死，不污染 repo）：

```json
{ "pid": 12345, "port": 9222, "profile": "...", "launched_at": "2026-08-03T10:00:00" }
```

- 啟動 Chrome 成功 → 寫檔
- 正常關閉成功 → 刪檔

### 1c. 啟動時的回收判定（決策：收養，不是殺掉重開）

lifespan startup 時：

| 狀態檔 | port 9222 | 檔中 PID 還活著且是 chrome.exe | 判定 |
|---|---|---|---|
| 無 | 有回應 | — | Ryan 手開的 → **不碰**（不擁有） |
| 無 | 無回應 | — | 乾淨 |
| 有 | 有回應 | 是 | **上輪殘留 → 收養**（標記擁有，本輪結束時關掉） |
| 有 | 有回應 | 否 | PID 已被回收／換人 → 不可信 → 刪狀態檔、**不擁有** |
| 有 | 無回應 | — | Chrome 早就沒了 → 刪狀態檔 |

**為什麼收養而不是殺掉重開**：殘留的 Chrome 已經開著、profile 已登入、session 是熱的。殺掉只是為了 15 秒後在 cookies 刷新時原地再開一個，白付冷啟動又動搖 IG session 活性（F13 原理）。收養達成同一個目的——**沒有任何 Chrome 活得比服務久**——而且零成本。

「PID 還活著且是 chrome.exe」用 `tasklist /FI "PID eq <pid>" /FI "IMAGENAME eq chrome.exe"` 驗，堵住 PID 被作業系統回收後誤殺無關程序的洞；同時也擋掉「狀態檔是崩潰殘留、但 port 上其實是 Ryan 新開的 Chrome」這個誤收養情境（那種情況舊 PID 早已不存在）。

### 2. 關閉流程（`close_owned_chrome()`，模組層級 async 函式）

1. 沒有擁有權 → 直接回傳，不做事
2. **graceful**：`GET /json/list` 取所有 target，逐一 `GET /json/close/{id}`；輪詢 `/json/version` 直到失效（上限 5 秒）
3. **強制**：graceful 逾時才 `taskkill /PID <pid> /T /F`（Windows；非 Windows 走 `kill` process group）——只殺 PID 會留下 renderer 子程序
4. 任一步例外只記 WARNING，**不得**讓 shutdown 拋錯或卡住
5. 收尾清掉擁有權狀態

不引入 psutil（本 repo 無此依賴），用 DevTools HTTP 端點 + `taskkill` 即可。

### 3. 掛載點

- **startup**：`app/main.py` lifespan yield 之前呼叫 `reclaim_orphan_chrome()`（依 1c 判定表）
- **shutdown**：yield 之後、`telegram_app.shutdown()` 附近呼叫 `close_owned_chrome()`

mission-control 停服務是先送 `CTRL_BREAK_EVENT`（uvicorn 走完 lifespan shutdown），逾時才 `kill_tree`——graceful 路徑會執行到。強制 kill 的情況由下一次啟動的回收接手。

**殘餘限制**：服務停掉之後、下次啟動之前的這段空窗，殘留 Chrome 仍在桌面上（沒有常駐程序可以收它）。要消掉這段只能靠 mission-control 側介入，不在本 feature 範圍。

## 測試（TDD）

mock `requests`、`subprocess` 與狀態檔（tmp_path），不真的開關 Chrome。

**關閉（shutdown）**
- 擁有：本服務啟動 → shutdown 會關
- 不擁有：CDP 早已在跑 → shutdown **不**關（最重要的一條）
- 擁有權跨實例存活（模擬 cookie 刷新 new 多個 service 實例）
- graceful 成功 → 不呼叫 taskkill
- graceful 逾時 → 呼叫 taskkill 且帶 `/T`
- 關閉過程拋例外 → 不外漏、shutdown 正常完成
- 關閉後擁有權與狀態檔皆清空（重複呼叫不重複殺）

**回收（startup）**——照 1c 判定表逐列
- 無狀態檔 + port 有回應 → 不擁有、不關（Ryan 手開的）
- 有狀態檔 + port 有回應 + PID 是活的 chrome.exe → 收養（標記擁有，且**不**重啟 Chrome）
- 有狀態檔 + port 有回應 + PID 已死／非 chrome → 刪檔、不擁有
- 有狀態檔 + port 無回應 → 刪檔、不擁有
- 狀態檔毀損（非法 JSON／缺欄位）→ 當作無檔處理，不拋錯

**真實驗證**（宣告 passing 前）三種情境並附 log：
1. 中台 stop 服務 → Chrome 視窗消失、port 9222 無回應
2. 手動先開 CDP Chrome → 啟停服務 → 該視窗仍在
3. 模擬崩潰（強制 kill 服務留下殘留）→ 重新啟動服務 → log 顯示收養、Chrome 沒被重開；再 stop → 視窗消失

## Acceptance（2026-08-03 Ryan 簽核，已凍結進 feature_list.json F19；動工後不得修改）

> **停止**：服務走完 uvicorn lifespan shutdown 時，若 CDP Chrome 為本服務所擁有，該 Chrome 連同子程序一併關閉且 port 9222 不再回應；非本服務啟動（服務啟動前就已在執行）的 Chrome 不得被關閉。**啟動**：lifespan startup 依狀態檔判定回收——狀態檔存在、port 有回應且檔中 PID 仍是存活的 chrome.exe 時**收養**該殘留 Chrome（標記為擁有、不重啟它，使其於本輪結束時被關閉）；狀態檔不存在、PID 已死或非 chrome、port 無回應、狀態檔毀損等情況一律不擁有並清掉無效狀態檔。**擁有權**記錄於模組層級並持久化到 profile 目錄下的狀態檔（啟動 Chrome 成功時寫、成功關閉後刪），跨多次 NotebookLMSyncService 實例與跨行程皆有效。**關閉流程**先走 CDP graceful（關閉所有 target 並輪詢 port 上限 5 秒），逾時才強制 kill process tree；startup 與 shutdown 兩側任何失敗只記 WARNING、不拋錯、不阻塞（各自增加耗時 < 10 秒）。**測試**：單元測試以 mock 覆蓋擁有／不擁有／跨實例／graceful 成功不強殺／逾時才強殺／例外不外漏，以及 1c 判定表五種回收情境；真實驗證涵蓋「本服務啟動的會被關」「手動開的不被關」「崩潰殘留於下次啟動被收養且不重開」三種情境並附 log 證據。
