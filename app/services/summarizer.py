"""Ollama 本地 AI 摘要生成服務（使用 Qwen2.5）"""

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

import ollama

from app.config import settings


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


class OllamaSummarizer:
    """Ollama 本地 AI 摘要生成服務"""

    SYSTEM_PROMPT = """你是一個專業的內容摘要助手。你的任務是將影片逐字稿整理成清晰、有條理的摘要。

請遵循以下規則：
1. 摘要應以繁體中文撰寫
2. 摘要應簡潔明瞭，約 100-200 字
3. 條列重點應提取 3-5 個最重要的要點
4. 保持客觀，不要加入個人意見
5. 如果內容涉及步驟或流程，請保持順序
6. 如果逐字稿內容不清楚或雜亂，盡力整理出有意義的內容
7. 特別注意擷取：工具名稱、技能清單、軟體、程式語言、框架等專業術語
8. 如果有列表或清單，請完整保留並條列呈現"""

    USER_PROMPT_TEMPLATE = """請根據以下影片逐字稿，生成摘要和條列重點。

逐字稿內容：
{transcript}

請以以下格式回覆（不要包含 JSON 格式，直接用文字）：

【摘要】
（一段話的摘要）

【重點】
• 重點一
• 重點二
• 重點三
（視內容而定，3-5 點）"""

    USER_PROMPT_WITH_VISUAL_TEMPLATE = """請根據以下影片的「語音逐字稿」和「畫面描述」，生成完整的摘要和條列重點。

【語音逐字稿】
{transcript}

【畫面描述】
{visual_description}

請綜合語音和畫面內容，以以下格式回覆（不要包含 JSON 格式，直接用文字）：

【摘要】
（一段話的摘要，結合語音內容和畫面資訊）

【重點】
• 重點一
• 重點二
• 重點三
（視內容而定，3-5 點）

【工具與技能】
• 工具/技能一
• 工具/技能二
（如果內容有提到任何工具、技能、軟體、程式語言、框架等，請完整列出。若無則省略此區塊）

【畫面觀察】
• 觀察一
• 觀察二
（從畫面中觀察到的重要視覺資訊，1-3 點）"""

    def __init__(self):
        self.model = settings.ollama_model
        self.client = ollama.AsyncClient(host=settings.ollama_host)

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
            
            # 使用同步 client
            response = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                options={
                    "temperature": 0.7,
                    "num_predict": 1024,
                }
            )

            content = response["message"]["content"]
            result = self._parse_response(content)

            if result.success:
                logger.info("摘要生成成功")

            return result

        except Exception as e:
            error_msg = str(e)
            logger.error(f"摘要生成失敗: {error_msg}")

            if "connection refused" in error_msg.lower():
                return SummaryResult(
                    success=False,
                    error_message="Ollama 服務未啟動，請執行 'ollama serve'",
                )
            elif "model" in error_msg.lower() and "not found" in error_msg.lower():
                return SummaryResult(
                    success=False,
                    error_message=f"模型 {self.model} 未安裝，請執行 'ollama pull {self.model}'",
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
                elif "【工具與技能】" in line or ("工具" in line and "技能" in line and "】" in line):
                    current_section = "tools"
                    continue
                elif "【畫面觀察】" in line or ("畫面觀察" in line and "】" in line):
                    current_section = "visual"
                    continue

                if current_section == "summary":
                    if not line.startswith("•") and not line.startswith("-") and not line.startswith("*"):
                        summary += line + " "
                elif current_section == "bullet":
                    # 移除項目符號
                    if line.startswith("•"):
                        line = line[1:].strip()
                    elif line.startswith("-"):
                        line = line[1:].strip()
                    elif line.startswith("*"):
                        line = line[1:].strip()
                    elif line[0].isdigit() and "." in line[:3]:
                        line = line.split(".", 1)[1].strip()

                    if line:
                        bullet_points.append(line)
                elif current_section == "tools":
                    # 移除項目符號
                    if line.startswith("•"):
                        line = line[1:].strip()
                    elif line.startswith("-"):
                        line = line[1:].strip()
                    elif line.startswith("*"):
                        line = line[1:].strip()
                    elif line[0].isdigit() and "." in line[:3]:
                        line = line.split(".", 1)[1].strip()

                    if line:
                        tools_and_skills.append(line)
                elif current_section == "visual":
                    # 移除項目符號
                    if line.startswith("•"):
                        line = line[1:].strip()
                    elif line.startswith("-"):
                        line = line[1:].strip()
                    elif line.startswith("*"):
                        line = line[1:].strip()
                    elif line[0].isdigit() and "." in line[:3]:
                        line = line.split(".", 1)[1].strip()

                    if line:
                        visual_observations.append(line)

            summary = summary.strip()

            # 如果解析失敗，使用整個內容作為摘要
            if not summary:
                summary = content.strip()

            # 如果沒有重點，嘗試從摘要中提取
            if not bullet_points:
                # 簡單切分為多個句子作為重點
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

    # ==================== 新功能：LLM 直接生成 Markdown 筆記 ====================

    NOTE_SYSTEM_PROMPT = """你是一個專業的筆記整理助手。你的任務是將影片內容整理成結構清晰的 Markdown 筆記。

請遵循以下規則：
1. 【重要】所有內容必須使用繁體中文撰寫（台灣用語）
2. 將簡體中文轉換為繁體中文（例：软件→軟體、视频→影片、数据→資料）
3. 使用標準 Markdown 格式
4. 使用 ## 二級標題分隔各區塊
5. 列表使用 - 符號
6. 保持客觀，不要加入個人意見
7. 根據內容類型靈活調整結構"""

    NOTE_PROMPT_TEMPLATE = """請根據以下影片內容，生成一份結構清晰的 Markdown 筆記。

【語言要求】請務必使用繁體中文（台灣用語）撰寫所有內容。

## 影片資訊
- 原始連結：{url}
- 影片標題：{title}
- 處理時間：{processed_time}

## 影片內容
{content}

## 輸出要求
請生成符合以下格式的 Markdown 筆記，直接輸出 Markdown 內容，不要加額外說明：

1. 必須以 `#Instagram摘要` 標籤開頭
2. 必須包含以下區塊（使用 ## 標題）：
   - **來源資訊**：包含原始連結和處理時間
   - **摘要**：2-3 句話概述影片主要內容
   - **重點整理**：3-5 個要點的列表
   - **工具與技能**：列出影片中提到的所有工具、軟體、程式語言、技能、平台、服務等（若無則標註「無」）
   - **逐字稿**：原始內容（如果無語音則標註並放入畫面描述）

3. 可選區塊（根據內容決定是否需要）：
   - **畫面觀察**：從畫面中觀察到的重要視覺資訊
   - **步驟說明**：如果是教學類內容，列出操作步驟
   - **優缺點分析**：如果是評測/比較類內容

4. 格式規範：
   - 使用 - 作為列表符號
   - 連結使用 [文字](網址) 格式
   - 無語音時，逐字稿區塊開頭用斜體 *此影片無語音內容，以下為畫面描述*
   - 有語音時，逐字稿使用 > 引用區塊格式
   - 【重要】全部使用繁體中文，不要使用簡體中文"""

    def _generate_note_sync(
        self,
        url: str,
        title: str,
        transcript: str,
        visual_description: str = None,
        has_audio: bool = True
    ) -> NoteResult:
        """同步生成筆記方法"""
        try:
            from datetime import datetime
            processed_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 組合內容
            if has_audio and transcript:
                if visual_description:
                    content = f"【語音逐字稿】\n{transcript}\n\n【畫面描述】\n{visual_description}"
                else:
                    content = f"【語音逐字稿】\n{transcript}"
            else:
                content = f"【此影片無語音，以下為畫面分析】\n{visual_description or transcript}"
            
            user_prompt = self.NOTE_PROMPT_TEMPLATE.format(
                url=url,
                title=title,
                processed_time=processed_time,
                content=content
            )
            
            # 呼叫 Ollama
            response = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.NOTE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                options={
                    "temperature": 0.7,
                    "num_predict": 4096,  # 筆記內容較長
                }
            )

            markdown_content = response["message"]["content"]
            
            # 提取摘要和重點用於 Telegram 回覆
            summary, bullet_points = self._extract_summary_for_telegram(markdown_content)
            
            logger.info("Markdown 筆記生成成功")
            
            return NoteResult(
                success=True,
                markdown_content=markdown_content,
                summary=summary,
                bullet_points=bullet_points,
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"筆記生成失敗: {error_msg}")

            if "connection refused" in error_msg.lower():
                return NoteResult(
                    success=False,
                    error_message="Ollama 服務未啟動，請執行 'ollama serve'",
                )
            elif "model" in error_msg.lower() and "not found" in error_msg.lower():
                return NoteResult(
                    success=False,
                    error_message=f"模型 {self.model} 未安裝，請執行 'ollama pull {self.model}'",
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
        
        summary = summary.strip()
        
        # 如果提取失敗，使用預設值
        if not summary:
            summary = "（摘要生成中...）"
        if not bullet_points:
            bullet_points = ["（請查看完整筆記）"]
        
        return summary, bullet_points

    async def generate_note(
        self,
        url: str,
        title: str,
        transcript: str,
        visual_description: str = None,
        has_audio: bool = True
    ) -> NoteResult:
        """
        生成完整的 Markdown 筆記

        Args:
            url: Instagram 原始連結
            title: 影片標題
            transcript: 影片逐字稿
            visual_description: 可選的視覺描述
            has_audio: 是否有語音內容

        Returns:
            NoteResult: 筆記生成結果
        """
        if not transcript and not visual_description:
            return NoteResult(
                success=False,
                error_message="沒有可用的內容（無逐字稿也無視覺描述）",
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
            has_audio
        )
