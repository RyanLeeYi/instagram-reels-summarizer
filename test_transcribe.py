"""測試 Whisper 語音轉錄"""

import asyncio
import os
from pathlib import Path

from openai import AsyncOpenAI


async def test_transcribe():
    """測試轉錄剛下載的音訊檔案"""
    
    # 檢查 API Key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ 請設定 OPENAI_API_KEY 環境變數")
        print("   PowerShell: $env:OPENAI_API_KEY = 'your-api-key'")
        return
    
    # 音訊檔案路徑
    audio_path = Path(__file__).parent / "temp_videos" / "test_video.mp3"
    
    if not audio_path.exists():
        print(f"❌ 音訊檔案不存在: {audio_path}")
        print("   請先執行 test_download.py 下載影片")
        return
    
    print(f"🎵 音訊檔案: {audio_path}")
    print(f"📊 檔案大小: {audio_path.stat().st_size / 1024:.2f} KB")
    print("-" * 50)
    
    client = AsyncOpenAI(api_key=api_key)
    
    try:
        print("🎤 開始轉錄...")
        
        with open(audio_path, "rb") as audio_file:
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
            )
        
        transcript = response.text.strip()
        language = getattr(response, "language", "未知")
        duration = getattr(response, "duration", "未知")
        
        print("-" * 50)
        print("✅ 轉錄成功！")
        print(f"🌐 偵測語言: {language}")
        print(f"⏱️ 音訊時長: {duration} 秒")
        print("-" * 50)
        print("📝 逐字稿內容:")
        print("-" * 50)
        print(transcript)
        print("-" * 50)
        print(f"📊 字數統計: {len(transcript)} 字")
        
        # 儲存逐字稿
        output_path = Path(__file__).parent / "temp_videos" / "transcript.txt"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(transcript)
        print(f"💾 逐字稿已儲存: {output_path}")
        
    except Exception as e:
        print(f"❌ 轉錄失敗: {e}")


if __name__ == "__main__":
    asyncio.run(test_transcribe())
