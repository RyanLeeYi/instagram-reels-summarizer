"""
測試 NotebookLM CDP 連線 + 完整上傳流程

使用方式:
  1. 先執行 scripts/start_chrome_cdp.bat 啟動 Chrome CDP
  2. python scripts/test_notebooklm.py
"""

import asyncio
import sys
from pathlib import Path

# 確保可以 import app 模組
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_full_upload():
    """測試完整上傳流程：建立 notebook → 設定標題 → 上傳文字 source"""
    # lazy import to avoid heavy module loading
    from app.services.notebooklm_sync import NotebookLMSyncService, NotebookLMResult
    from app.database.models import init_db

    # 初始化 DB
    await init_db()

    service = NotebookLMSyncService()

    # 模擬一份摘要內容
    test_markdown = """# Python 開發技巧：使用列表推導式

## 重點摘要

本影片介紹了 Python 中列表推導式的進階用法，包括條件過濾、巢狀迴圈、以及如何搭配字典推導式使用。

## 詳細分析

### 列表推導式基本語法
- `[expr for item in iterable]` 是基本形式
- 可加入條件過濾: `[expr for item in iterable if condition]`
- 巢狀推導式用於多維資料處理

### 效能優勢
- 比傳統 for 迴圈快 10-30%
- 記憶體使用更有效率
- 程式碼更簡潔易讀

### 實用範例
1. 過濾偶數: `[x for x in range(100) if x % 2 == 0]`
2. 字串處理: `[s.strip().lower() for s in names]`
3. 字典推導: `{k: v for k, v in items if v > 0}`

## 來源資訊
- 作者: @test_python_tips
- 連結: https://www.instagram.com/reel/TEST123/
- 類型: Reel 影片
"""

    print("🚀 開始測試 NotebookLM 上傳...")
    result = await service.upload_reel(
        markdown_content=test_markdown,
        video_path=None,
        title="Python 列表推導式技巧",
    )

    if result.success:
        print(f"✅ 上傳成功！")
        print(f"   Notebook URL: {result.notebook_url}")
        print(f"   Notebook Title: {result.notebook_title}")
        print(f"\n📋 請在瀏覽器中確認 Notebook 內容:")
        print(f"   {result.notebook_url}")
    else:
        print(f"❌ 上傳失敗: {result.error_message}")

    return result.success


if __name__ == "__main__":
    result = asyncio.run(test_full_upload())
