"""測試完整流程（包含視覺分析）

用法: python scripts/test_flow_visual.py
"""

import asyncio
from pathlib import Path
import sys

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.downloader import InstagramDownloader
from app.services.transcriber import WhisperTranscriber
from app.services.visual_analyzer import VideoVisualAnalyzer
from app.services.summarizer import OllamaSummarizer
from app.services.roam_sync import RoamSyncService


async def main():
    test_url = "https://www.instagram.com/reel/DMxowe6v2zY/"
    
    print("=" * 70)
    print("Instagram Reels 完整處理流程測試 (含視覺分析)")
    print("=" * 70)
    
    downloader = InstagramDownloader()
    transcriber = WhisperTranscriber()
    visual_analyzer = VideoVisualAnalyzer()
    summarizer = OllamaSummarizer()
    roam_sync = RoamSyncService()
    
    # Step 1: Download
    print("\n📥 Step 1: 下載影片...")
    download_result = await downloader.download(test_url)
    
    if not download_result.success:
        print(f"❌ 下載失敗: {download_result.error_message}")
        return
    
    print(f"✅ 下載成功!")
    print(f"   標題: {download_result.title}")
    print(f"   音訊: {download_result.audio_path}")
    print(f"   影片: {download_result.video_path}")
    
    # Step 2: Transcribe
    print("\n📝 Step 2: 語音轉文字...")
    transcribe_result = await transcriber.transcribe(download_result.audio_path)
    
    if not transcribe_result.success:
        print(f"❌ 轉錄失敗: {transcribe_result.error_message}")
        return
    
    print(f"✅ 轉錄成功!")
    print(f"   語言: {transcribe_result.language}")
    print(f"   逐字稿長度: {len(transcribe_result.transcript)} 字元")
    
    # Step 2.5: Visual Analysis
    visual_description = None
    if download_result.video_path and download_result.video_path.exists():
        print("\n👁 Step 2.5: 視覺分析...")
        visual_result = await visual_analyzer.analyze(download_result.video_path)
        
        if visual_result.success:
            visual_description = visual_result.overall_visual_summary
            print(f"✅ 視覺分析成功!")
            print(f"   分析幀數: {len(visual_result.frame_descriptions)}")
        else:
            print(f"⚠️ 視覺分析失敗: {visual_result.error_message}")
    else:
        print("\n⏭️ Step 2.5: 跳過視覺分析 (無影片檔案)")
    
    # Step 3: Summarize (with visual description)
    print("\n🤖 Step 3: 生成摘要...")
    summary_result = await summarizer.summarize(
        transcribe_result.transcript,
        visual_description
    )
    
    if not summary_result.success:
        print(f"❌ 摘要失敗: {summary_result.error_message}")
        return
    
    print(f"✅ 摘要成功!")
    print(f"\n📝 摘要:")
    print(f"   {summary_result.summary}")
    print(f"\n📌 重點:")
    for point in summary_result.bullet_points:
        print(f"   • {point}")
    
    if summary_result.visual_observations:
        print(f"\n👁 畫面觀察:")
        for obs in summary_result.visual_observations:
            print(f"   • {obs}")
    
    # Step 4: Sync to Roam
    print("\n📤 Step 4: 同步到 Roam...")
    roam_result = await roam_sync.sync_to_roam(
        test_url,
        download_result.title,
        summary_result.summary,
        summary_result.bullet_points,
        transcribe_result.transcript,
        summary_result.visual_observations
    )
    
    if roam_result.success:
        print(f"✅ 同步成功!")
        print(f"   頁面標題: {roam_result.page_title}")
    else:
        print(f"❌ 同步失敗: {roam_result.error_message}")
    
    # Cleanup
    print("\n🧹 清理暫存檔案...")
    await downloader.cleanup(download_result.audio_path)
    if download_result.video_path:
        await downloader.cleanup(download_result.video_path)
    
    print("\n" + "=" * 70)
    print("✅ 完整流程測試完成！")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
