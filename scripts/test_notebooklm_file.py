"""
測試 NotebookLM 檔案上傳功能（影片/圖片）

使用方式:
  python scripts/test_notebooklm_file.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_file_upload():
    """測試檔案上傳：建立 notebook → 上傳文字 + 影片"""
    from app.services.notebooklm_sync import NotebookLMSyncService
    from app.database.models import init_db

    await init_db()
    service = NotebookLMSyncService()

    test_markdown = """# FastAPI 入門教學

## 重點摘要
本影片介紹了 FastAPI 的基本用法，包括路由設計、請求驗證、和回應模型。

## 詳細分析

### 路由設計
- 使用 `@app.get()` 和 `@app.post()` 裝飾器
- 路徑參數和查詢參數自動解析
- 支援非同步處理 (async/await)

### 請求驗證
- Pydantic 模型自動驗證
- 自訂 validator
- 錯誤訊息自動生成

## 來源資訊
- 作者: @test_fastapi_tips
- 連結: https://www.instagram.com/reel/TEST_FILE_UPLOAD/
- 類型: Reel 影片
"""

    video_path = Path("temp_videos/8789e8fd_video.mp4")
    if not video_path.exists():
        print(f"❌ 測試影片不存在: {video_path}")
        return False

    print(f"🚀 開始測試 NotebookLM 檔案上傳...")
    print(f"   影片: {video_path} ({video_path.stat().st_size / 1024:.0f} KB)")

    result = await service.upload_reel(
        markdown_content=test_markdown,
        video_path=video_path,
        title="FastAPI 入門教學",
    )

    if result.success:
        print(f"✅ 上傳成功！")
        print(f"   Notebook URL: {result.notebook_url}")
        print(f"   Notebook Title: {result.notebook_title}")
    else:
        print(f"❌ 上傳失敗: {result.error_message}")

    return result.success


if __name__ == "__main__":
    success = asyncio.run(test_file_upload())
    sys.exit(0 if success else 1)
