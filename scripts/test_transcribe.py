"""測試 faster-whisper 本地語音轉錄

用法: python scripts/test_transcribe.py
"""

from pathlib import Path
from faster_whisper import WhisperModel

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent


def test_local_transcribe():
    """使用 faster-whisper 本地轉錄"""
    
    # 音訊檔案路徑
    audio_path = PROJECT_ROOT / "temp_videos" / "test_video.mp3"
    
    if not audio_path.exists():
        print(f"❌ 音訊檔案不存在: {audio_path}")
        print("   請先執行 test_download.py 下載影片")
        return
    
    print(f"🎵 音訊檔案: {audio_path}")
    print(f"📊 檔案大小: {audio_path.stat().st_size / 1024:.2f} KB")
    print("-" * 50)
    
    # 載入模型 (首次會自動下載)
    # 模型大小: tiny, base, small, medium, large-v2, large-v3
    # 建議使用 "base" 或 "small" 平衡速度和準確度
    print("📦 載入 Whisper 模型 (首次需下載，請稍候)...")
    print("   使用模型: base (較快，適合測試)")
    
    model = WhisperModel("base", device="cpu", compute_type="int8")
    
    print("✅ 模型載入完成！")
    print("-" * 50)
    print("🎤 開始轉錄...")
    
    # 執行轉錄
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        language=None,  # 自動偵測語言
        vad_filter=True,  # 過濾靜音段落
    )
    
    print(f"🌐 偵測語言: {info.language} (信心度: {info.language_probability:.2%})")
    print(f"⏱️ 音訊時長: {info.duration:.2f} 秒")
    print("-" * 50)
    print("📝 逐字稿內容:")
    print("-" * 50)
    
    # 收集所有文字
    full_transcript = ""
    for segment in segments:
        print(f"[{segment.start:.1f}s - {segment.end:.1f}s] {segment.text}")
        full_transcript += segment.text + " "
    
    full_transcript = full_transcript.strip()
    
    print("-" * 50)
    print(f"📊 字數統計: {len(full_transcript)} 字")
    
    # 儲存逐字稿
    output_path = PROJECT_ROOT / "temp_videos" / "transcript.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_transcript)
    print(f"💾 逐字稿已儲存: {output_path}")
    
    print("-" * 50)
    print("✅ 本地轉錄完成！無需 API Key！")


if __name__ == "__main__":
    test_local_transcribe()
