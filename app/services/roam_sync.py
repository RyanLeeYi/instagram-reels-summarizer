"""Roam Research 同步服務"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from app.config import settings


logger = logging.getLogger(__name__)


@dataclass
class RoamSyncResult:
    """Roam 同步結果"""

    success: bool
    page_title: Optional[str] = None
    page_url: Optional[str] = None
    error_message: Optional[str] = None


class RoamSyncService:
    """
    Roam Research 同步服務

    目前使用本地 Markdown 檔案儲存，供使用者手動匯入 Roam Research。
    未來可擴展支援 Roam Research API。
    """

    def __init__(self):
        self.graph_name = settings.roam_graph_name

    def _generate_page_title(self, video_title: str, prefix: str = "IG Reels") -> str:
        """
        生成 Roam 頁面標題

        Args:
            video_title: 影片/貼文標題
            prefix: 標題前綴（預設為 "IG Reels"）

        Returns:
            頁面標題
        """
        now = datetime.now().strftime("%Y-%m-%d %H%M%S")

        # 清理標題中的特殊字符
        clean_title = video_title.replace("[", "").replace("]", "")
        clean_title = clean_title[:50] if len(clean_title) > 50 else clean_title

        return f"{prefix} - {now} - {clean_title}"

    def _format_roam_content(
        self,
        instagram_url: str,
        video_title: str,
        summary: str,
        bullet_points: List[str],
        transcript: str,
        tools_and_skills: Optional[List[str]] = None,
        visual_observations: Optional[List[str]] = None,
        visual_analysis: Optional[str] = None,
    ) -> str:
        """
        格式化 Roam Research 頁面內容（使用標準 Markdown 格式）

        Args:
            instagram_url: Instagram 連結
            video_title: 影片標題
            summary: 摘要
            bullet_points: 重點列表
            transcript: 逐字稿
            tools_and_skills: 可選的工具與技能列表
            visual_observations: 可選的畫面觀察列表
            visual_analysis: 可選的完整影像分析內容

        Returns:
            格式化後的內容
        """
        processed_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 構建重點列表
        bullet_text = "\n".join([f"- {point}" for point in bullet_points])

        content = f"""{{{{[[TODO]]}}}} #[[Instagram摘要]]

## 來源資訊

- **原始連結**: [{video_title}]({instagram_url})
- **處理時間**: {processed_time}

## 摘要

{summary}

## 重點整理

{bullet_text}
"""

        # 如果有工具與技能，添加到內容中
        if tools_and_skills:
            tools_text = "\n".join([f"- {tool}" for tool in tools_and_skills])
            content += f"""
## 工具與技能

{tools_text}
"""

        # 如果有視覺觀察，添加到內容中
        if visual_observations:
            visual_text = "\n".join([f"- {obs}" for obs in visual_observations])
            content += f"""
## 畫面觀察

{visual_text}
"""

        # 如果有完整影像分析，添加到內容中
        if visual_analysis:
            content += f"""
## 影像分析

{visual_analysis}
"""

        # 處理逐字稿
        if transcript.startswith("[此影片無語音內容，以下為畫面描述]"):
            # 分離提示文字和實際內容
            parts = transcript.split("\n", 1)
            notice = parts[0].strip("[]")  # 移除方括號
            actual_content = parts[1] if len(parts) > 1 else ""
            content += f"""
## 逐字稿

*{notice}*

{actual_content}
"""
        else:
            content += f"""
## 逐字稿

> {transcript.replace(chr(10), chr(10) + "> ")}
"""
        return content

    async def sync_to_roam(
        self,
        instagram_url: str,
        video_title: str,
        summary: str,
        bullet_points: List[str],
        transcript: str,
        tools_and_skills: Optional[List[str]] = None,
        visual_observations: Optional[List[str]] = None,
        visual_analysis: Optional[str] = None,
    ) -> RoamSyncResult:
        """
        同步內容到 Roam Research

        目前使用本地 Markdown 檔案儲存，供使用者手動匯入。

        Args:
            instagram_url: Instagram 連結
            video_title: 影片標題
            summary: 摘要
            bullet_points: 重點列表
            transcript: 逐字稿
            tools_and_skills: 可選的工具與技能列表
            visual_observations: 可選的視覺觀察列表
            visual_analysis: 可選的完整影像分析內容

        Returns:
            RoamSyncResult: 同步結果
        """
        try:
            page_title = self._generate_page_title(video_title)
            content = self._format_roam_content(
                instagram_url, video_title, summary, bullet_points, transcript,
                tools_and_skills, visual_observations, visual_analysis
            )

            # 儲存到本地 Markdown 檔案
            return await self._save_to_local(page_title, content)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Roam 同步失敗: {error_msg}")
            return RoamSyncResult(
                success=False,
                error_message=f"同步失敗: {error_msg}",
            )

    async def save_markdown_note(
        self,
        video_title: str,
        markdown_content: str,
    ) -> RoamSyncResult:
        """
        直接儲存 LLM 生成的 Markdown 筆記

        Args:
            video_title: 影片標題（用於生成檔名）
            markdown_content: LLM 生成的完整 Markdown 內容

        Returns:
            RoamSyncResult: 同步結果
        """
        try:
            page_title = self._generate_page_title(video_title)
            
            # 直接使用 LLM 生成的內容，只加上標題
            return await self._save_to_local(page_title, markdown_content)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"儲存筆記失敗: {error_msg}")
            return RoamSyncResult(
                success=False,
                error_message=f"儲存失敗: {error_msg}",
            )

    async def save_post_note(
        self,
        post_title: str,
        markdown_content: str,
        caption: str,
    ) -> RoamSyncResult:
        """
        儲存 Instagram 貼文筆記（包含原始貼文文字）

        Args:
            post_title: 貼文標題（用於生成檔名）
            markdown_content: LLM 生成的完整 Markdown 內容
            caption: 原始貼文說明文字

        Returns:
            RoamSyncResult: 同步結果
        """
        try:
            page_title = self._generate_page_title(post_title)
            
            # 在 Markdown 內容末尾附加原始貼文
            appendix = self._format_post_appendix(caption)
            full_content = markdown_content + appendix
            
            # 儲存筆記
            return await self._save_to_local(page_title, full_content)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"儲存貼文筆記失敗: {error_msg}")
            return RoamSyncResult(
                success=False,
                error_message=f"儲存失敗: {error_msg}",
            )

    def _format_post_appendix(
        self,
        caption: str,
    ) -> str:
        """
        格式化貼文附錄（原始貼文文字）

        Args:
            caption: 原始貼文說明文字

        Returns:
            str: 格式化後的 Markdown 附錄
        """
        if not caption or not caption.strip():
            return ""

        appendix = "\n\n---\n\n## 附錄\n\n"
        appendix += "### 原始貼文\n\n"
        appendix += f"> {caption.replace(chr(10), chr(10) + '> ')}\n\n"

        return appendix

    async def save_threads_note(
        self,
        author: str,
        markdown_content: str,
        original_url: str,
    ) -> RoamSyncResult:
        """
        儲存 Threads 串文筆記（包含原始連結附錄）

        Args:
            author: Threads 作者名稱
            markdown_content: LLM 生成的完整 Markdown 內容
            original_url: Threads 原始連結

        Returns:
            RoamSyncResult: 同步結果
        """
        try:
            # 使用作者名稱作為標題的一部分
            page_title = self._generate_page_title(f"@{author}", prefix="Threads")

            # 在 Markdown 內容末尾附加原始連結
            appendix = self._format_threads_appendix(original_url)
            full_content = markdown_content + appendix

            return await self._save_to_local(page_title, full_content)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"儲存 Threads 筆記失敗: {error_msg}")
            return RoamSyncResult(
                success=False,
                error_message=f"儲存失敗: {error_msg}",
            )

    @staticmethod
    def _format_threads_appendix(original_url: str) -> str:
        """
        格式化 Threads 附錄（原始連結）

        Args:
            original_url: Threads 原始連結

        Returns:
            str: 格式化後的 Markdown 附錄
        """
        if not original_url or not original_url.strip():
            return ""

        appendix = "\n\n---\n\n## 附錄\n\n"
        appendix += "### 原始連結\n\n"
        appendix += f"- 🧵 [{original_url}]({original_url})\n\n"

        return appendix

    async def _sync_via_claude_code(self, file_path: Path, page_title: str) -> bool:
        """
        使用 Claude Code CLI 同步 Markdown 到 Roam Research

        透過 claude -p 非互動模式，讓 Claude Code 使用 Roam MCP 工具同步

        Args:
            file_path: Markdown 檔案路徑
            page_title: Roam 頁面標題

        Returns:
            是否同步成功
        """
        import shutil
        import platform
        
        try:
            # 讀取檔案內容
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 構建 prompt 讓 Claude Code 使用 Roam MCP 同步
            prompt = f'''請使用 roam_create_page 工具將以下 Markdown 內容建立為 Roam Research 頁面。

頁面標題: {page_title}

【重要格式說明】
1. 第一行的 `#Instagram摘要` 是 Roam 標籤，必須保留為 `#[[Instagram摘要]]` 格式以正確建立連結
2. 所有以 `#` 開頭但不是 Markdown 標題（## 或 ###）的內容都是 Roam 標籤，需轉換為 `#[[標籤名]]` 格式
3. Markdown 標題（## 來源資訊、## 摘要 等）保持原樣

內容:
{content}'''

            # 找到 claude 可執行檔
            claude_path = shutil.which("claude")
            if not claude_path:
                # Windows 特殊處理：嘗試找 .cmd 或 npm 路徑
                if platform.system() == "Windows":
                    npm_path = Path.home() / "AppData" / "Roaming" / "npm"
                    for ext in [".cmd", ".ps1", ""]:
                        candidate = npm_path / f"claude{ext}"
                        if candidate.exists():
                            claude_path = str(candidate)
                            break
            
            if not claude_path:
                logger.warning("找不到 claude CLI，跳過 Roam 同步")
                return False

            # 允許所有 roam-research MCP 工具
            allowed_tools = "mcp__roam-research__*"

            # 使用 stdin 傳遞 prompt（避免命令列參數長度限制和特殊字符問題）
            if platform.system() == "Windows":
                process = await asyncio.create_subprocess_shell(
                    f'"{claude_path}" -p --allowedTools "{allowed_tools}"',
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(file_path.parent.parent),
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    claude_path,
                    "-p",
                    "--allowedTools", allowed_tools,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(file_path.parent.parent),
                )

            # 透過 stdin 傳遞 prompt
            stdout, stderr = await process.communicate(input=prompt.encode('utf-8'))

            if process.returncode == 0:
                logger.info(f"Claude Code 同步成功: {page_title}")
                logger.debug(f"Claude 輸出: {stdout.decode('utf-8', errors='ignore')}")
                return True
            else:
                logger.warning(f"Claude Code 同步失敗 (exit {process.returncode}): {stderr.decode('utf-8', errors='ignore')}")
                return False

        except FileNotFoundError:
            logger.warning("claude CLI 未安裝或不在 PATH 中，跳過 Roam 同步")
            return False
        except Exception as e:
            logger.error(f"Claude Code 同步發生錯誤: {e}")
            return False

    async def _save_to_local(self, page_title: str, content: str) -> RoamSyncResult:
        """
        儲存內容到本地 Markdown 檔案

        Args:
            page_title: 頁面標題
            content: 頁面內容

        Returns:
            RoamSyncResult: 同步結果
        """
        try:
            # 建立本地備份目錄
            backup_dir = Path(settings.temp_video_dir).parent / "roam_backup"
            backup_dir.mkdir(parents=True, exist_ok=True)

            # 清理檔名
            safe_title = "".join(
                c for c in page_title if c.isalnum() or c in (" ", "-", "_")
            ).strip()
            filename = f"{safe_title}.md"

            # 寫入檔案
            file_path = backup_dir / filename
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# {page_title}\n\n")
                f.write(content)

            logger.info(f"內容已儲存到本地: {file_path}")

            # 如果啟用 Claude Code 同步，嘗試同步到 Roam
            if settings.claude_code_sync_enabled:
                logger.info("正在透過 Claude Code 同步到 Roam Research...")
                sync_success = await self._sync_via_claude_code(file_path, page_title)
                if sync_success:
                    logger.info(f"已透過 Claude Code 同步到 Roam: {page_title}")
                else:
                    logger.warning("Claude Code 同步失敗，內容已保留在本地")

            # 生成 Roam URL（供使用者參考）
            encoded_title = quote(page_title)
            estimated_url = f"https://roamresearch.com/#/app/{self.graph_name}/page/{encoded_title}"

            return RoamSyncResult(
                success=True,
                page_title=page_title,
                page_url=estimated_url,
            )

        except Exception as e:
            return RoamSyncResult(
                success=False,
                error_message=f"儲存失敗: {str(e)}",
            )
