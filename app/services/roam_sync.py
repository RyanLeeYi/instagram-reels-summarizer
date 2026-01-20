"""Roam Research 同步服務"""

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

    def _generate_page_title(self, video_title: str) -> str:
        """
        生成 Roam 頁面標題

        Args:
            video_title: 影片標題

        Returns:
            頁面標題
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # 清理標題中的特殊字符
        clean_title = video_title.replace("[", "").replace("]", "")
        clean_title = clean_title[:50] if len(clean_title) > 50 else clean_title

        return f"IG Reels - {today} - {clean_title}"

    def _format_roam_content(
        self,
        instagram_url: str,
        video_title: str,
        summary: str,
        bullet_points: List[str],
        transcript: str,
    ) -> str:
        """
        格式化 Roam Research 頁面內容

        Args:
            instagram_url: Instagram 連結
            video_title: 影片標題
            summary: 摘要
            bullet_points: 重點列表
            transcript: 逐字稿

        Returns:
            格式化後的內容
        """
        processed_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 構建重點列表
        bullet_text = "\n".join([f"    - {point}" for point in bullet_points])

        content = f"""#Instagram摘要

- **來源資訊**
    - **原始連結**: [{video_title}]({instagram_url})
    - **處理時間**: {processed_time}

- **摘要**
    - {summary}

- **重點整理**
{bullet_text}

- **逐字稿**
    - > {transcript}
"""
        return content

    async def sync_to_roam(
        self,
        instagram_url: str,
        video_title: str,
        summary: str,
        bullet_points: List[str],
        transcript: str,
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

        Returns:
            RoamSyncResult: 同步結果
        """
        try:
            page_title = self._generate_page_title(video_title)
            content = self._format_roam_content(
                instagram_url, video_title, summary, bullet_points, transcript
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
