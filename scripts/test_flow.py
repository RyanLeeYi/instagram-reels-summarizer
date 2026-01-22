"""測試完整流程：下載 -> 轉錄 -> 摘要 -> Roam 同步

用法: python scripts/test_flow.py
"""

import asyncio
import sys
from pathlib import Path

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.downloader import InstagramDownloader
from app.services.transcriber import WhisperTranscriber
from app.services.summarizer import OllamaSummarizer
from app.services.roam_sync import RoamSyncService


async def test_full_flow(url: str):
    """測試完整流程"""
    
    print("=" * 60)
    print("Instagram Reels 摘要系統 - 完整流程測試")
    print("=" * 60)
    print(f"\n📎 測試連結: {url}\n")
    
    # Step 1: 下載影片
    print("-" * 40)
    print("📥 Step 1: 下載影片...")
    print("-" * 40)
    
    downloader = InstagramDownloader()
    
    if not downloader.validate_url(url):
        print("❌ 無效的 Instagram 連結")
        return
    
    download_result = await downloader.download(url)
    
    if not download_result.success:
        print(f"❌ 下載失敗: {download_result.error_message}")
        return
    
    print(f"✅ 下載成功!")
    print(f"   標題: {download_result.title}")
    print(f"   音訊路徑: {download_result.audio_path}")
    
    # Step 2: 語音轉錄
    print("\n" + "-" * 40)
    print("🎤 Step 2: 語音轉文字...")
    print("-" * 40)
    print("   （首次執行會下載 Whisper 模型，請稍候...）")
    
    transcriber = WhisperTranscriber()
    transcribe_result = await transcriber.transcribe(download_result.audio_path)
    
    if not transcribe_result.success:
        print(f"❌ 轉錄失敗: {transcribe_result.error_message}")
        return
    
    print(f"✅ 轉錄成功!")
    print(f"   偵測語言: {transcribe_result.language}")
    print(f"   逐字稿長度: {len(transcribe_result.transcript)} 字")
    print(f"\n   📝 逐字稿內容:")
    print("   " + "-" * 36)
    # 顯示逐字稿（限制長度）
    transcript_preview = transcribe_result.transcript
    if len(transcript_preview) > 500:
        transcript_preview = transcript_preview[:500] + "..."
    for line in transcript_preview.split('\n'):
        print(f"   {line}")
    print("   " + "-" * 36)
    
    # Step 3: 生成摘要
    print("\n" + "-" * 40)
    print("📝 Step 3: 生成 AI 摘要...")
    print("-" * 40)
    
    summarizer = OllamaSummarizer()
    summary_result = await summarizer.summarize(transcribe_result.transcript)
    
    if not summary_result.success:
        print(f"❌ 摘要生成失敗: {summary_result.error_message}")
        return
    
    print(f"✅ 摘要生成成功!")
    print(f"\n   📋 摘要:")
    print("   " + "-" * 36)
    for line in summary_result.summary.split('\n'):
        print(f"   {line}")
    print("   " + "-" * 36)
    
    if summary_result.bullet_points:
        print(f"\n   📌 重點:")
        for point in summary_result.bullet_points:
            print(f"   • {point}")
    
    # Step 4: 同步到 Roam Research (本地 Markdown)
    print("\n" + "-" * 40)
    print("📚 Step 4: 儲存到 Roam Research (Markdown)...")
    print("-" * 40)
    
    roam_service = RoamSyncService()
    roam_result = await roam_service.sync_to_roam(
        instagram_url=url,
        video_title=download_result.title,
        summary=summary_result.summary,
        bullet_points=summary_result.bullet_points or [],
        transcript=transcribe_result.transcript,
    )
    
    if not roam_result.success:
        print(f"❌ Roam 同步失敗: {roam_result.error_message}")
    else:
        print(f"✅ Roam 同步成功!")
        print(f"   📄 頁面標題: {roam_result.page_title}")
        print(f"   📁 檔案位置: roam_backup/{roam_result.page_title}.md")
        print(f"   🔗 Roam URL: {roam_result.page_url}")
    
    # 完成
    print("\n" + "=" * 60)
    print("✅ 完整流程測試完成!")
    print("=" * 60)
    
    # 清理暫存檔案
    if download_result.audio_path and download_result.audio_path.exists():
        download_result.audio_path.unlink()
        print(f"\n🗑️  已清理暫存檔案")


if __name__ == "__main__":
    url = "https://www.instagram.com/reel/DMxowe6v2zY/?igsh=MW45MnFjNnMwYTNvdA=="
    asyncio.run(test_full_flow(url))
