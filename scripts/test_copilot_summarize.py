"""測試 GitHub Copilot CLI 摘要功能

用法: python scripts/test_copilot_summarize.py
"""

import asyncio
import sys
from pathlib import Path

# 確保可以導入 app 模組
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.copilot_summarizer import CopilotCLISummarizer, check_copilot_cli_available


def test_copilot_available():
    """測試 Copilot CLI 是否可用"""
    print("=" * 60)
    print("🔍 檢查 Copilot CLI 是否可用...")
    print("=" * 60)
    
    if check_copilot_cli_available():
        print("✅ Copilot CLI 已安裝並可用")
        summarizer = CopilotCLISummarizer()
        print(f"   路徑: {summarizer.copilot_path}")
        return True
    else:
        print("❌ Copilot CLI 未找到")
        print("   請執行: winget install GitHub.Copilot")
        return False


async def test_simple_prompt():
    """測試簡單的提示"""
    print("\n" + "=" * 60)
    print("🧪 測試簡單提示...")
    print("=" * 60)
    
    summarizer = CopilotCLISummarizer()
    
    try:
        response = summarizer._run_copilot_cli(
            "請用繁體中文回答：什麼是 Python？用一句話說明。",
        )
        print(f"✅ 回應: {response}")
        return True
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        return False


async def test_summarize():
    """測試摘要功能"""
    print("\n" + "=" * 60)
    print("🧪 測試摘要功能...")
    print("=" * 60)
    
    summarizer = CopilotCLISummarizer()
    
    # 模擬逐字稿
    transcript = """
    大家好，今天要跟大家分享五個提升工作效率的工具。
    第一個是 Notion，它是一個非常強大的筆記和專案管理工具。
    第二個是 Todoist，可以幫助你管理每日待辦事項。
    第三個是 Obsidian，這是一個本地優先的知識管理系統。
    第四個是 Raycast，Mac 上超好用的效率工具。
    第五個是 Arc Browser，全新設計的瀏覽器體驗。
    這些工具都可以大幅提升你的工作效率，趕快試試看吧！
    """
    
    print("📝 測試逐字稿:")
    print(transcript[:100] + "...")
    print("-" * 60)
    
    result = await summarizer.summarize(transcript)
    
    if result.success:
        print("✅ 摘要生成成功！")
        print(f"\n📋 摘要:\n{result.summary}")
        print(f"\n📌 重點:")
        for i, point in enumerate(result.bullet_points or [], 1):
            print(f"   {i}. {point}")
        if result.tools_and_skills:
            print(f"\n🛠️ 工具與技能:")
            for tool in result.tools_and_skills:
                print(f"   • {tool}")
        return True
    else:
        print(f"❌ 摘要生成失敗: {result.error_message}")
        return False


async def test_generate_note():
    """測試筆記生成功能"""
    print("\n" + "=" * 60)
    print("🧪 測試筆記生成功能...")
    print("=" * 60)
    
    summarizer = CopilotCLISummarizer()
    
    url = "https://www.instagram.com/reel/test123/"
    title = "Video by productivity_tips"
    transcript = """
    想要提高程式開發效率嗎？今天分享三個 VS Code 必裝外掛。
    第一個是 GitHub Copilot，AI 幫你寫程式碼。
    第二個是 Prettier，自動格式化程式碼。
    第三個是 GitLens，讓你看到每行程式碼是誰寫的。
    這三個外掛可以大幅提升你的開發體驗！
    """
    
    result = await summarizer.generate_note(
        url=url,
        title=title,
        transcript=transcript,
        has_audio=True,
    )
    
    if result.success:
        print("✅ 筆記生成成功！")
        print(f"\n📄 Markdown 內容:\n")
        print("-" * 40)
        print(result.markdown_content)
        print("-" * 40)
        return True
    else:
        print(f"❌ 筆記生成失敗: {result.error_message}")
        return False


async def main():
    """主測試流程"""
    print("\n" + "=" * 60)
    print("🚀 Copilot CLI Summarizer 測試")
    print("=" * 60)
    
    # 檢查 Copilot CLI
    if not test_copilot_available():
        return
    
    # 測試簡單提示
    await test_simple_prompt()
    
    # 測試摘要
    await test_summarize()
    
    # 測試筆記生成
    await test_generate_note()
    
    print("\n" + "=" * 60)
    print("✅ 所有測試完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
