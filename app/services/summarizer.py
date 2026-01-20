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
6. 如果逐字稿內容不清楚或雜亂，盡力整理出有意義的內容"""

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

    def __init__(self):
        self.model = settings.ollama_model
        self.client = ollama.AsyncClient(host=settings.ollama_host)

    def _summarize_sync(self, transcript: str) -> SummaryResult:
        """同步摘要方法"""
        try:
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

    async def summarize(self, transcript: str) -> SummaryResult:
        """
        生成逐字稿的摘要

        Args:
            transcript: 影片逐字稿

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
        return await loop.run_in_executor(None, self._summarize_sync, transcript)

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

            # 分割摘要和重點
            lines = content.strip().split("\n")
            current_section = None

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if "【摘要】" in line or "摘要" in line and "】" in line:
                    current_section = "summary"
                    continue
                elif "【重點】" in line or "重點" in line and "】" in line:
                    current_section = "bullet"
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
            )

        except Exception as e:
            logger.warning(f"解析回應失敗，使用原始內容: {e}")
            return SummaryResult(
                success=True,
                summary=content.strip(),
                bullet_points=["（無法提取重點）"],
            )
