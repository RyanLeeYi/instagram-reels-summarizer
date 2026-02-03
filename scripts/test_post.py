"""測試 Instagram 貼文下載與分析流程"""

import asyncio
import sys
from pathlib import Path

# 加入專案路徑
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.downloader import InstagramDownloader
from app.services.visual_analyzer import VideoVisualAnalyzer


async def test_post_download():
    """測試貼文下載"""
    print("=" * 60)
    print("Instagram 貼文下載測試")
    print("=" * 60)
    
    # 請替換為實際的 Instagram 貼文連結
    test_url = input("請輸入 Instagram 貼文連結 (/p/ 格式): ").strip()
    
    if not test_url:
        print("❌ 未提供連結，跳過測試")
        return
    
    downloader = InstagramDownloader()
    
    # 判斷內容類型
    is_reel = downloader.is_reel_url(test_url)
    print(f"\n📌 URL 類型判斷: {'Reel（影片）' if is_reel else '貼文（圖片）'}")
    
    if is_reel:
        print("此連結為 Reel，請使用原有的影片下載流程")
        return
    
    # 下載貼文
    print("\n⏳ 正在下載貼文...")
    result = await downloader.download_post(test_url)
    
    if not result.success:
        print(f"❌ 下載失敗: {result.error_message}")
        return
    
    print(f"✅ 下載成功！")
    print(f"   內容類型: {result.content_type}")
    print(f"   標題: {result.title}")
    print(f"   圖片數量: {len(result.image_paths)}")
    print(f"   說明文字長度: {len(result.caption or '')} 字元")
    
    if result.caption:
        print(f"\n📝 貼文說明 (前 200 字):")
        print(f"   {result.caption[:200]}...")
    
    print(f"\n📂 圖片路徑:")
    for i, path in enumerate(result.image_paths, 1):
        print(f"   {i}. {path}")
    
    # 測試圖片分析
    print("\n" + "=" * 60)
    print("圖片分析測試")
    print("=" * 60)
    
    analyze_input = input("\n是否要測試圖片分析？(y/n): ").strip().lower()
    if analyze_input == 'y':
        analyzer = VideoVisualAnalyzer()
        print(f"\n⏳ 正在分析 {len(result.image_paths)} 張圖片...")
        
        visual_result = await analyzer.analyze_images(result.image_paths)
        
        if visual_result.success:
            print(f"\n✅ 分析成功！")
            print(f"\n📊 整體視覺描述:")
            print("-" * 40)
            print(visual_result.overall_visual_summary)
        else:
            print(f"❌ 分析失敗: {visual_result.error_message}")
    
    # 清理暫存檔案
    print("\n⏳ 清理暫存檔案...")
    await downloader.cleanup_post_images(result.image_paths)
    print("✅ 清理完成")


if __name__ == "__main__":
    asyncio.run(test_post_download())
