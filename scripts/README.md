# 測試腳本

這個目錄包含手動測試腳本，用於單獨測試各個模組功能。

## 使用方式

所有腳本都需要從**專案根目錄**執行：

```bash
# 確保已啟動虛擬環境
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # macOS/Linux

# 執行測試腳本
python scripts/test_download.py
```

## 腳本說明

| 腳本 | 說明 | 前置需求 |
|------|------|----------|
| `test_download.py` | 測試 Instagram 影片下載 | cookies.txt |
| `test_transcribe.py` | 測試 faster-whisper 語音轉錄 | test_download.py |
| `test_summarize.py` | 測試 Ollama 摘要生成 | test_transcribe.py, Ollama 服務 |
| `test_visual.py` | 測試 MiniCPM-V 視覺分析 | Ollama 服務 |
| `test_flow.py` | 完整流程測試（不含視覺） | 所有服務 |
| `test_flow_visual.py` | 完整流程測試（含視覺分析） | 所有服務 |

## 測試順序

建議按以下順序執行，確保每個模組正常運作：

1. **下載測試** - 確認 cookies.txt 和 yt-dlp 正常
   ```bash
   python scripts/test_download.py
   ```

2. **轉錄測試** - 確認 faster-whisper 正常（首次會下載模型）
   ```bash
   python scripts/test_transcribe.py
   ```

3. **摘要測試** - 確認 Ollama 服務和模型正常
   ```bash
   python scripts/test_summarize.py
   ```

4. **視覺分析測試** - 確認 MiniCPM-V 模型正常
   ```bash
   python scripts/test_visual.py
   ```

5. **完整流程測試**
   ```bash
   python scripts/test_flow_visual.py
   ```

## 注意事項

- 測試檔案會儲存在 `temp_videos/` 目錄，該目錄已被 `.gitignore` 排除
- 首次執行轉錄測試會下載 Whisper 模型（約 150MB）
- 請確保 Ollama 服務已啟動再執行摘要和視覺測試
