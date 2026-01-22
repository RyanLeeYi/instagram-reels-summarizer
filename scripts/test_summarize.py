"""測試 Ollama + Qwen2.5 本地摘要

用法: python scripts/test_summarize.py
"""

import ollama
from pathlib import Path

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent


def test_ollama_summarize():
    """使用 Ollama + Qwen2.5 測試本地摘要"""
    
    # 讀取逐字稿
    transcript_path = PROJECT_ROOT / "temp_videos" / "transcript.txt"
    
    if not transcript_path.exists():
        print("❌ 逐字稿檔案不存在")
        print("   請先執行 test_local_transcribe.py")
        return
    
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = f.read()
    
    print(f"📝 逐字稿長度: {len(transcript)} 字")
    print("-" * 50)
    
    # 摘要 prompt
    system_prompt = """你是一個專業的內容摘要助手。你的任務是將影片逐字稿整理成清晰、有條理的摘要。

請遵循以下規則：
1. 摘要應以繁體中文撰寫
2. 摘要應簡潔明瞭，約 100-200 字
3. 條列重點應提取 3-5 個最重要的要點
4. 保持客觀，不要加入個人意見"""

    user_prompt = f"""請根據以下影片逐字稿，生成摘要和條列重點。

逐字稿內容：
{transcript}

請以以下格式回覆：

【摘要】
（一段話的摘要）

【重點】
• 重點一
• 重點二
• 重點三
（視內容而定，3-5 點）"""

    print("🤖 正在使用 Qwen2.5 生成摘要...")
    print("-" * 50)
    
    try:
        response = ollama.chat(
            model="qwen2.5:7b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            options={
                "temperature": 0.7,
                "num_predict": 1024,
            }
        )
        
        content = response["message"]["content"]
        
        print("✅ 摘要生成成功！")
        print("-" * 50)
        print(content)
        print("-" * 50)
        
        # 儲存摘要
        summary_path = PROJECT_ROOT / "temp_videos" / "summary.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"💾 摘要已儲存: {summary_path}")
        
    except ollama.ResponseError as e:
        if "model" in str(e).lower() and "not found" in str(e).lower():
            print("❌ 模型未安裝")
            print("   請執行: ollama pull qwen2.5:7b")
        else:
            print(f"❌ 錯誤: {e}")
    except Exception as e:
        if "connection" in str(e).lower():
            print("❌ Ollama 服務未啟動")
            print("   請先啟動 Ollama 應用程式")
        else:
            print(f"❌ 錯誤: {e}")


if __name__ == "__main__":
    test_ollama_summarize()
