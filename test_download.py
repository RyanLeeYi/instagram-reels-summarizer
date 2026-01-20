"""測試 Instagram 影片下載"""

import asyncio
import sys
from pathlib import Path

# 加入專案路徑
sys.path.insert(0, str(Path(__file__).parent))

import yt_dlp


def test_download():
    """測試下載指定的 Instagram Reels"""
    
    url = "https://www.instagram.com/reel/DMxowe6v2zY/?igsh=MW45MnFjNnMwYTNvdA=="
    
    # 建立暫存目錄
    temp_dir = Path(__file__).parent / "temp_videos"
    temp_dir.mkdir(exist_ok=True)
    
    output_template = str(temp_dir / "test_video")
    
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template + ".%(ext)s",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "quiet": False,
        "no_warnings": False,
        "extract_flat": False,
    }
    
    print(f"🔗 測試連結: {url}")
    print(f"📂 輸出目錄: {temp_dir}")
    print("-" * 50)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print("📥 開始下載...")
            info = ydl.extract_info(url, download=True)
            
            if info:
                print("-" * 50)
                print("✅ 下載成功！")
                print(f"📌 標題: {info.get('title', '未知')}")
                print(f"⏱️ 時長: {info.get('duration', '未知')} 秒")
                print(f"👤 上傳者: {info.get('uploader', '未知')}")
                
                # 檢查輸出檔案
                mp3_path = Path(f"{output_template}.mp3")
                if mp3_path.exists():
                    file_size = mp3_path.stat().st_size / 1024
                    print(f"🎵 音訊檔案: {mp3_path}")
                    print(f"📊 檔案大小: {file_size:.2f} KB")
                else:
                    print("⚠️ MP3 檔案未找到，檢查其他格式...")
                    for ext in ["m4a", "webm", "opus"]:
                        alt_path = Path(f"{output_template}.{ext}")
                        if alt_path.exists():
                            file_size = alt_path.stat().st_size / 1024
                            print(f"🎵 音訊檔案: {alt_path}")
                            print(f"📊 檔案大小: {file_size:.2f} KB")
                            break
            else:
                print("❌ 無法取得影片資訊")
                
    except yt_dlp.utils.DownloadError as e:
        print(f"❌ 下載失敗: {e}")
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")


if __name__ == "__main__":
    test_download()
