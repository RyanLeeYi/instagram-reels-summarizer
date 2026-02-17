"""
測試 Instagram 貼文下載 + NotebookLM 多圖上傳

使用方式:
  1. 先啟動 Chrome CDP: scripts/start_chrome_cdp.bat
  2. python scripts/test_post_upload.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TEST_URL = "https://www.instagram.com/p/DUvXL60geS3"


async def download_post():
    """下載貼文圖片"""
    from app.services.downloader import InstagramDownloader

    downloader = InstagramDownloader()
    result = await downloader.download_post(TEST_URL)

    if not result.success:
        print(f"❌ 下載失敗: {result.error_message}")
        return None

    print(f"✅ 下載成功")
    print(f"   標題: {result.title}")
    print(f"   圖片數: {len(result.image_paths)}")
    for i, p in enumerate(result.image_paths, 1):
        print(f"   圖片 {i}: {p}")

    return result


async def test_upload_post():
    """測試下載 + 上傳完整流程"""
    from app.services.notebooklm_sync import NotebookLMSyncService
    from app.database.models import init_db

    await init_db()

    # Step 1: 下載貼文
    print("=" * 50)
    print("Step 1: 下載 Instagram 貼文")
    print("=" * 50)
    download_result = await download_post()
    if not download_result:
        return False

    image_paths = [Path(p) for p in download_result.image_paths]
    title = download_result.title or "unknown"

    # Step 2: 上傳到 NotebookLM
    print("\n" + "=" * 50)
    print("Step 2: 上傳到 NotebookLM")
    print("=" * 50)

    test_markdown = f"""# 測試貼文 - {title}

## 重點摘要
這是一則測試用的 Instagram 貼文。

## 來源資訊
- 標題: {title}
- 連結: {TEST_URL}
- 類型: Post 圖文貼文
- 圖片數: {len(image_paths)} 張
"""

    service = NotebookLMSyncService()

    print(f"🚀 開始上傳到 NotebookLM...")
    print(f"   圖片數: {len(image_paths)}")
    for i, p in enumerate(image_paths, 1):
        size_kb = p.stat().st_size / 1024 if p.exists() else 0
        print(f"   圖片 {i}: {p.name} ({size_kb:.0f} KB)")

    result = await service.upload_post(
        markdown_content=test_markdown,
        image_paths=image_paths,
        title=f"測試貼文 - {title}",
    )

    if result.success:
        print(f"\n✅ 上傳成功！")
        print(f"   Notebook URL: {result.notebook_url}")
        print(f"   Notebook Title: {result.notebook_title}")
    else:
        print(f"\n❌ 上傳失敗: {result.error_message}")

    return result.success


if __name__ == "__main__":
    success = asyncio.run(test_upload_post())
    sys.exit(0 if success else 1)
