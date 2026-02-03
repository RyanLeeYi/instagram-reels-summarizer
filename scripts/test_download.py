"""測試 Instagram 影片下載

用法: python scripts/test_download.py [--browser BROWSER]

選項:
    --browser BROWSER   使用指定瀏覽器的 cookies (chrome, edge, firefox, brave)
"""

import sys
import argparse
from pathlib import Path

# 加入專案路徑
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yt_dlp


def check_cookies_file(cookies_file: Path) -> dict:
    """檢查 cookies.txt 的有效性"""
    result = {
        "exists": cookies_file.exists(),
        "has_sessionid": False,
        "has_csrftoken": False,
        "has_ds_user_id": False,
        "cookie_count": 0,
    }
    
    if not result["exists"]:
        return result
    
    try:
        with open(cookies_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('#') or not line.strip():
                    continue
                parts = line.split('\t')
                if len(parts) >= 6:
                    result["cookie_count"] += 1
                    cookie_name = parts[5] if len(parts) > 5 else ""
                    if cookie_name == "sessionid":
                        result["has_sessionid"] = True
                    elif cookie_name == "csrftoken":
                        result["has_csrftoken"] = True
                    elif cookie_name == "ds_user_id":
                        result["has_ds_user_id"] = True
    except Exception as e:
        print(f"⚠️ 無法讀取 cookies 檔案: {e}")
    
    return result


def test_download(use_browser: str = None):
    """測試下載指定的 Instagram Reels"""
    
    url = "https://www.instagram.com/reel/DMxowe6v2zY/?igsh=MW45MnFjNnMwYTNvdA=="
    
    # 建立暫存目錄
    temp_dir = PROJECT_ROOT / "temp_videos"
    temp_dir.mkdir(exist_ok=True)
    
    output_template = str(temp_dir / "test_video")
    
    # 檢查 cookies.txt 是否存在
    cookies_file = PROJECT_ROOT / "cookies.txt"
    
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
    
    # 根據選項決定認證方式
    if use_browser:
        # 使用瀏覽器 cookies
        ydl_opts["cookiesfrombrowser"] = (use_browser,)
        print(f"🌐 使用瀏覽器 cookies: {use_browser}")
        print("💡 請確保該瀏覽器已登入 Instagram")
    elif cookies_file.exists():
        # 檢查 cookies.txt 有效性
        cookie_status = check_cookies_file(cookies_file)
        print(f"🍪 cookies.txt 狀態:")
        print(f"   - Cookie 數量: {cookie_status['cookie_count']}")
        print(f"   - sessionid: {'✅' if cookie_status['has_sessionid'] else '❌ 缺少（需要登入）'}")
        print(f"   - csrftoken: {'✅' if cookie_status['has_csrftoken'] else '❌'}")
        print(f"   - ds_user_id: {'✅' if cookie_status['has_ds_user_id'] else '❌'}")
        
        if not cookie_status['has_sessionid']:
            print()
            print("⚠️ cookies.txt 缺少 sessionid，認證可能失敗！")
            print("💡 請重新匯出 cookies 或使用 --browser 選項")
            print("   例如: python scripts/test_download.py --browser chrome")
            print()
        
        ydl_opts["cookiefile"] = str(cookies_file)
        print(f"📂 使用 cookies 檔案: {cookies_file}")
    else:
        print("⚠️ 未找到 cookies.txt，嘗試無認證下載（可能失敗）")
        print("💡 建議使用 --browser 選項: python scripts/test_download.py --browser chrome")
    
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
        print()
        print("💡 可能的解決方案:")
        print("   1. 重新匯出 cookies.txt（確保包含 sessionid）")
        print("   2. 使用瀏覽器 cookies: python scripts/test_download.py --browser chrome")
        print("   3. 更新 yt-dlp: pip install -U yt-dlp")
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="測試 Instagram 影片下載")
    parser.add_argument(
        "--browser", 
        choices=["chrome", "edge", "firefox", "brave", "opera", "chromium"],
        help="使用指定瀏覽器的 cookies 進行認證"
    )
    args = parser.parse_args()
    
    test_download(use_browser=args.browser)
