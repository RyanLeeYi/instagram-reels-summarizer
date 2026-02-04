"""Claude Code CLI 摘要生成服務"""

import asyncio
import logging
import subprocess
import shutil
from dataclasses import dataclass
from typing import List, Optional

from app.config import settings
from app.services.prompt_loader import get_prompt_loader


logger = logging.getLogger(__name__)


@dataclass
class SummaryResult:
    """摘要結果"""

    success: bool
    summary: Optional[str] = None
    bullet_points: Optional[List[str]] = None
    tools_and_skills: Optional[List[str]] = None
    visual_observations: Optional[List[str]] = None
    error_message: Optional[str] = None


@dataclass
class NoteResult:
    """筆記生成結果"""

    success: bool
    markdown_content: Optional[str] = None
    summary: Optional[str] = None  # 用於 Telegram 回覆
    bullet_points: Optional[List[str]] = None  # 用於 Telegram 回覆
    error_message: Optional[str] = None


class ClaudeCodeSummarizer:
    """使用 Claude Code CLI 的摘要生成服務"""

    SYSTEM_PROMPT = """你是一個專業的內容摘要助手。收到影片逐字稿後，請直接輸出摘要結果，不要詢問使用者，不要使用任何工具。

規則：
1. 摘要以繁體中文撰寫，約 100-200 字
2. 條列重點 3-5 個要點
3. 保持客觀，不加個人意見
4. 特別注意工具名稱、技術術語
5. 直接輸出結果，不要問問題"""

    USER_PROMPT_TEMPLATE = """以下是影片逐字稿，請直接生成摘要（不要問問題，直接輸出結果）：

逐字稿：
{transcript}

請以此格式輸出：

【摘要】
（一段話的摘要）

【重點】
• 重點一
• 重點二
• 重點三"""

    USER_PROMPT_WITH_VISUAL_TEMPLATE = """以下是影片內容，請直接生成摘要（不要問問題，直接輸出結果）：

【語音逐字稿】
{transcript}

【畫面描述】
{visual_description}

請以此格式輸出：

【摘要】
（結合語音和畫面的摘要）

【重點】
• 重點一
• 重點二  
• 重點三

【工具與技能】
• （如有提到工具/技術請列出，若無則省略此區塊）

【畫面觀察】
• （重要視覺資訊，1-3 點）"""

    NOTE_SYSTEM_PROMPT = """你是筆記整理助手。收到影片資訊後，直接輸出 Markdown 筆記，不要詢問使用者，不要使用工具。

規則：
1. 全部使用繁體中文（台灣用語）
2. 使用 ## 二級標題分隔區塊
3. 列表使用 - 符號
4. 直接輸出 Markdown，不要加說明"""

    NOTE_PROMPT_TEMPLATE = """根據以下影片資訊，直接輸出 Markdown 筆記（不要問問題）：

## 影片資訊
- 連結：{url}
- 標題：{title}
- 時間：{processed_time}

## 影片內容
{content}

直接輸出以下格式的 Markdown：

## 來源資訊
- 連結：[原始連結]({url})
- 處理時間：{processed_time}

## 摘要
（2-3 句話概述）

## 重點整理
- 重點一
- 重點二
- 重點三

（如有步驟或工具，加上對應區塊）"""

    def __init__(self, model: str = "sonnet"):
        """
        初始化 Claude Code Summarizer
        
        Args:
            model: Claude 模型名稱 (sonnet, opus, haiku)
        """
        self.model = model
        self.claude_path = self._find_claude_cli()
        # 初始化 PromptLoader（含快取機制）
        self.prompt_loader = get_prompt_loader(settings.prompts_path)
        
        if not self.claude_path:
            logger.warning("Claude Code CLI 未找到，請確保已安裝")

    def _find_claude_cli(self) -> Optional[str]:
        """尋找 Claude CLI 執行檔路徑"""
        # 嘗試在 PATH 中尋找
        claude_path = shutil.which("claude")
        if claude_path:
            return claude_path
        
        # Windows 常見路徑
        import os
        possible_paths = [
            os.path.expanduser("~/.claude/local/claude.exe"),
            os.path.expanduser("~/AppData/Local/Programs/claude/claude.exe"),
            "C:/Program Files/Claude/claude.exe",
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        return None

    def _run_claude_cli(self, prompt: str, system_prompt: str = None) -> str:
        """
        執行 Claude CLI 並取得回應
        
        Args:
            prompt: 使用者提示
            system_prompt: 系統提示（可選）
            
        Returns:
            Claude 的回應文字
        """
        if not self.claude_path:
            raise RuntimeError("Claude Code CLI 未安裝或未找到")
        
        import tempfile
        import os
        
        # 結合系統提示和使用者提示
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n---\n\n{prompt}"
        else:
            full_prompt = prompt
        
        # 使用臨時目錄作為工作目錄，避免讀取專案上下文
        temp_dir = tempfile.gettempdir()
        
        # 建立命令 - 使用 stdin 傳遞 prompt 避免命令列長度限制
        cmd = [
            self.claude_path,
            "-p", "-",  # 從 stdin 讀取 prompt
            "--model", self.model,
            "--dangerously-skip-permissions",  # 跳過權限檢查
            "--tools", "",  # 禁用所有工具
        ]
        
        logger.info(f"執行 Claude CLI (model={self.model})")
        
        try:
            result = subprocess.run(
                cmd,
                input=full_prompt,  # 透過 stdin 傳遞 prompt
                capture_output=True,
                text=True,
                timeout=120,  # 2 分鐘超時
                encoding="utf-8",
                cwd=temp_dir,  # 使用臨時目錄，避免讀取專案上下文
            )
            
            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error"
                logger.error(f"Claude CLI 執行失敗: {error_msg}")
                raise RuntimeError(f"Claude CLI 錯誤: {error_msg}")
            
            return result.stdout.strip()
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude CLI 執行超時（超過 2 分鐘）")
        except Exception as e:
            if "Claude CLI 錯誤" in str(e):
                raise
            raise RuntimeError(f"執行 Claude CLI 時發生錯誤: {e}")

    def _summarize_sync(self, transcript: str, visual_description: str = None) -> SummaryResult:
        """同步摘要方法"""
        try:
            # 根據是否有視覺描述選擇不同模板
            if visual_description:
                user_prompt = self.USER_PROMPT_WITH_VISUAL_TEMPLATE.format(
                    transcript=transcript,
                    visual_description=visual_description
                )
            else:
                user_prompt = self.USER_PROMPT_TEMPLATE.format(transcript=transcript)
            
            # 呼叫 Claude CLI
            content = self._run_claude_cli(user_prompt, self.SYSTEM_PROMPT)
            result = self._parse_response(content)

            if result.success:
                logger.info("摘要生成成功 (Claude Code)")

            return result

        except Exception as e:
            error_msg = str(e)
            logger.error(f"摘要生成失敗: {error_msg}")

            if "未安裝" in error_msg or "未找到" in error_msg:
                return SummaryResult(
                    success=False,
                    error_message="Claude Code CLI 未安裝，請執行 'npm install -g @anthropic-ai/claude-code'",
                )

            return SummaryResult(
                success=False,
                error_message=f"摘要生成失敗: {error_msg}",
            )

    async def summarize(self, transcript: str, visual_description: str = None) -> SummaryResult:
        """
        生成逐字稿的摘要

        Args:
            transcript: 影片逐字稿
            visual_description: 可選的視覺描述

        Returns:
            SummaryResult: 摘要結果
        """
        if not transcript or not transcript.strip():
            return SummaryResult(
                success=False,
                error_message="逐字稿內容為空",
            )

        # 在執行緒池中執行（避免阻塞）
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._summarize_sync, transcript, visual_description
        )

    def _parse_response(self, content: str) -> SummaryResult:
        """
        解析 Claude 的回應

        Args:
            content: Claude 的回應內容

        Returns:
            SummaryResult: 解析後的摘要結果
        """
        try:
            import re
            
            summary = ""
            bullet_points = []
            tools_and_skills = []
            visual_observations = []

            # 分割摘要和重點
            lines = content.strip().split("\n")
            current_section = None

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if "【摘要】" in line or ("摘要" in line and "】" in line):
                    current_section = "summary"
                    continue
                elif "【重點】" in line or ("重點" in line and "】" in line):
                    current_section = "bullet"
                    continue
                elif "【工具與技能】" in line or "【工具】" in line:
                    current_section = "tools"
                    continue
                elif "【畫面觀察】" in line or "【畫面】" in line:
                    current_section = "visual"
                    continue

                # 移除 markdown bold 格式
                clean_line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
                
                # 根據當前區塊處理內容
                if current_section == "summary":
                    summary += clean_line + " "
                elif current_section == "bullet":
                    if clean_line.startswith(("•", "-", "*", "·")):
                        point = clean_line.lstrip("•-*· ").strip()
                        # 移除開頭的數字編號如 "1. "
                        point = re.sub(r'^\d+\.\s*', '', point)
                        if point:
                            bullet_points.append(point)
                    elif clean_line[0].isdigit() and "." in clean_line[:3]:
                        point = clean_line.split(".", 1)[-1].strip()
                        if point:
                            bullet_points.append(point)
                elif current_section == "tools":
                    if clean_line.startswith(("•", "-", "*", "·")):
                        tool = clean_line.lstrip("•-*· ").strip()
                        if tool:
                            tools_and_skills.append(tool)
                elif current_section == "visual":
                    if clean_line.startswith(("•", "-", "*", "·")):
                        obs = clean_line.lstrip("•-*· ").strip()
                        if obs:
                            visual_observations.append(obs)

            summary = summary.strip()

            # 如果解析失敗，使用整個內容作為摘要
            if not summary:
                summary = content.strip()

            # 如果沒有重點，嘗試從摘要中提取
            if not bullet_points:
                sentences = summary.replace("。", "。|").replace("，", "，").split("|")
                bullet_points = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 10][:5]

            return SummaryResult(
                success=True,
                summary=summary,
                bullet_points=bullet_points if bullet_points else ["（無法提取重點）"],
                tools_and_skills=tools_and_skills if tools_and_skills else None,
                visual_observations=visual_observations if visual_observations else None,
            )

        except Exception as e:
            logger.warning(f"解析回應失敗，使用原始內容: {e}")
            return SummaryResult(
                success=True,
                summary=content.strip(),
                bullet_points=["（無法提取重點）"],
            )

    # ==================== 筆記生成功能 ====================

    def _generate_note_sync(
        self,
        url: str,
        title: str,
        transcript: str,
        visual_description: str = None,
        has_audio: bool = True,
        caption: str = None,
    ) -> NoteResult:
        """同步生成筆記方法"""
        try:
            from datetime import datetime
            processed_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            # 準備內容區塊
            content_parts = []
            
            if has_audio and transcript:
                content_parts.append(f"### 語音逐字稿\n> {transcript}")
            elif transcript:
                content_parts.append(f"### 畫面描述\n*此影片無語音內容，以下為畫面描述*\n\n{transcript}")
            
            if visual_description:
                content_parts.append(f"### 視覺分析\n{visual_description}")
            
            if caption:
                content_parts.append(f"### 原始說明\n{caption}")
            
            content = "\n\n".join(content_parts)
            
            # 載入自定義 prompt（如果有）
            note_system_prompt = self.prompt_loader.load_prompt(
                "note_system",
                fallback=self.NOTE_SYSTEM_PROMPT
            )
            
            # 建立使用者 prompt
            user_prompt = self.NOTE_PROMPT_TEMPLATE.format(
                url=url,
                title=title,
                processed_time=processed_time,
                content=content,
            )
            
            # 呼叫 Claude CLI
            markdown_content = self._run_claude_cli(user_prompt, note_system_prompt)
            
            # 提取摘要和重點用於 Telegram 回覆
            summary, bullet_points = self._extract_summary_for_telegram(markdown_content)
            
            logger.info("Markdown 筆記生成成功 (Claude Code)")
            
            return NoteResult(
                success=True,
                markdown_content=markdown_content,
                summary=summary,
                bullet_points=bullet_points,
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"筆記生成失敗: {error_msg}")

            if "未安裝" in error_msg or "未找到" in error_msg:
                return NoteResult(
                    success=False,
                    error_message="Claude Code CLI 未安裝",
                )

            return NoteResult(
                success=False,
                error_message=f"筆記生成失敗: {error_msg}",
            )

    def _extract_summary_for_telegram(self, markdown_content: str) -> tuple:
        """從 Markdown 內容中提取摘要和重點用於 Telegram 回覆"""
        summary = ""
        bullet_points = []
        
        lines = markdown_content.split("\n")
        current_section = None
        
        for line in lines:
            stripped = line.strip()
            
            # 檢測區塊標題
            if stripped.startswith("## "):
                section_name = stripped[3:].strip()
                if "摘要" in section_name:
                    current_section = "summary"
                elif "重點" in section_name:
                    current_section = "bullet"
                else:
                    current_section = None
                continue
            
            # 提取內容
            if current_section == "summary" and stripped and not stripped.startswith("#"):
                summary += stripped + " "
            elif current_section == "bullet" and stripped.startswith("-"):
                point = stripped[1:].strip()
                if point:
                    bullet_points.append(point)
        
        return summary.strip(), bullet_points

    async def generate_note(
        self,
        url: str,
        title: str,
        transcript: str,
        visual_description: str = None,
        has_audio: bool = True,
        caption: str = None,
    ) -> NoteResult:
        """
        生成 Markdown 筆記

        Args:
            url: 影片連結
            title: 影片標題
            transcript: 影片逐字稿
            visual_description: 可選的視覺描述
            has_audio: 是否有語音
            caption: 原始說明文字

        Returns:
            NoteResult: 筆記生成結果
        """
        if not transcript or not transcript.strip():
            return NoteResult(
                success=False,
                error_message="逐字稿內容為空",
            )

        # 在執行緒池中執行（避免阻塞）
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._generate_note_sync,
            url,
            title,
            transcript,
            visual_description,
            has_audio,
            caption,
        )

    # ==================== 貼文筆記生成功能 ====================

    POST_NOTE_PROMPT_TEMPLATE = """請根據以下 Instagram 貼文內容，生成一份結構清晰的 Markdown 筆記。

【語言要求】請務必使用繁體中文（台灣用語）撰寫所有內容。

## 貼文資訊
- 原始連結：{url}
- 貼文標題：{title}
- 處理時間：{processed_time}

## 貼文內容

### 貼文說明文字
{caption}

### 圖片內容分析
{visual_description}

## 輸出要求
請生成符合以下格式的 Markdown 筆記，直接輸出 Markdown 內容，不要加額外說明：

1. 必要區塊：
   - **來源資訊**：包含原始連結和處理時間
   - **摘要**：2-3 句話概述貼文主要內容
   - **重點整理**：3-5 個要點的列表
   - **工具與技術**：從圖片中整理出「實際出現」的工具、技術名詞等（若無則標註「無」）

2. 可選區塊（根據內容決定是否需要）：
   - **圖片觀察**：整合各張圖片的重點視覺資訊
   - **步驟說明**：如果是教學類內容，列出操作步驟

3. 格式規範：
   - 使用 - 作為列表符號
   - 連結使用 [文字](網址) 格式
   - 【重要】全部使用繁體中文，不要使用簡體中文
   - 【重要】「工具與技術」區塊只列出圖片中實際出現的項目"""

    def _generate_post_note_sync(
        self,
        url: str,
        title: str,
        caption: str,
        visual_description: str,
    ) -> NoteResult:
        """同步生成貼文筆記方法"""
        try:
            from datetime import datetime
            processed_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            # 建立使用者 prompt
            user_prompt = self.POST_NOTE_PROMPT_TEMPLATE.format(
                url=url,
                title=title,
                processed_time=processed_time,
                caption=caption or "（無說明文字）",
                visual_description=visual_description or "（無圖片分析）",
            )
            
            # 載入自定義 prompt（如果有）
            note_system_prompt = self.prompt_loader.load_prompt(
                "post_note_system",
                fallback=self.NOTE_SYSTEM_PROMPT
            )
            
            # 呼叫 Claude CLI
            markdown_content = self._run_claude_cli(user_prompt, note_system_prompt)
            
            # 提取摘要和重點用於 Telegram 回覆
            summary, bullet_points = self._extract_summary_for_telegram(markdown_content)
            
            logger.info("貼文 Markdown 筆記生成成功 (Claude Code)")
            
            return NoteResult(
                success=True,
                markdown_content=markdown_content,
                summary=summary,
                bullet_points=bullet_points,
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"貼文筆記生成失敗: {error_msg}")

            return NoteResult(
                success=False,
                error_message=f"貼文筆記生成失敗: {error_msg}",
            )

    async def generate_post_note(
        self,
        url: str,
        title: str,
        caption: str,
        visual_description: str,
    ) -> NoteResult:
        """
        生成貼文 Markdown 筆記

        Args:
            url: 貼文連結
            title: 貼文標題
            caption: 貼文說明文字
            visual_description: 圖片視覺描述

        Returns:
            NoteResult: 筆記生成結果
        """
        # 在執行緒池中執行（避免阻塞）
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._generate_post_note_sync,
            url,
            title,
            caption,
            visual_description,
        )


def check_claude_cli_available() -> bool:
    """檢查 Claude Code CLI 是否可用"""
    try:
        summarizer = ClaudeCodeSummarizer()
        return summarizer.claude_path is not None
    except Exception:
        return False
