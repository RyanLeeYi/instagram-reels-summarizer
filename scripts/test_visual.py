"""測試視覺分析功能

用法: python scripts/test_visual.py
"""

import asyncio
from pathlib import Path
import sys

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.visual_analyzer import VideoVisualAnalyzer


async def download_test_video():
    """下載測試影片"""
    import yt_dlp
    
    test_url = "https://www.instagram.com/reel/DMxowe6v2zY/"
    output_path = PROJECT_ROOT / "temp_videos" / "test_video.mp4"
    
    if output_path.exists():
        print(f"✅ 已有測試影片: {output_path}")
        return output_path
    
    print(f"⏳ 正在下載測試影片...")
    
    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": str(output_path),
        "quiet": False,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([test_url])
    
    print(f"✅ 影片已下載: {output_path}")
    return output_path


async def main():
    print("=" * 60)
    print("測試視覺分析功能 (MiniCPM-V)")
    print("=" * 60)
    
    # 下載測試影片
    video_path = await download_test_video()
    
    if not video_path.exists():
        print("❌ 無法取得測試影片")
        return
    
    print(f"\n📹 測試影片: {video_path}")
    print("-" * 60)
    
    analyzer = VideoVisualAnalyzer()
    
    print("\n⏳ 正在分析影片...")
    result = await analyzer.analyze(video_path)
    
    if result.success:
        print("\n✅ 視覺分析成功！")
        print("-" * 60)
        
        print("\n📷 各幀描述:")
        for fd in result.frame_descriptions:
            print(f"  [{fd.timestamp:.0f}秒] {fd.description}")
        
        print("\n📝 整體視覺摘要:")
        print(result.overall_visual_summary)
    else:
        print(f"\n❌ 視覺分析失敗: {result.error_message}")


if __name__ == "__main__":
    asyncio.run(main())
