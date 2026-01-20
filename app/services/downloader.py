"""Instagram Reels 下載服務"""

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yt_dlp

from app.config import settings


logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """下載結果"""

    success: bool
    video_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    title: Optional[str] = None
    error_message: Optional[str] = None


class InstagramDownloader:
    """Instagram Reels 下載器"""

    # 支援的 Instagram URL 格式
    INSTAGRAM_URL_PATTERNS = [
        r"https?://(?:www\.)?instagram\.com/reel/([A-Za-z0-9_-]+)",
        r"https?://(?:www\.)?instagram\.com/p/([A-Za-z0-9_-]+)",
        r"https?://(?:www\.)?instagram\.com/reels/([A-Za-z0-9_-]+)",
    ]

    def __init__(self):
        self.temp_dir = settings.temp_video_path

    def validate_url(self, url: str) -> bool:
        """驗證是否為有效的 Instagram Reels 連結"""
        for pattern in self.INSTAGRAM_URL_PATTERNS:
            if re.match(pattern, url):
                return True
        return False

    def extract_post_id(self, url: str) -> Optional[str]:
        """從 URL 提取貼文 ID"""
        for pattern in self.INSTAGRAM_URL_PATTERNS:
            match = re.match(pattern, url)
            if match:
                return match.group(1)
        return None

    async def download(self, url: str) -> DownloadResult:
        """
        下載 Instagram Reels 影片

        Args:
            url: Instagram Reels 連結

        Returns:
            DownloadResult: 下載結果
        """
        if not self.validate_url(url):
            return DownloadResult(
                success=False,
                error_message="無法解析此連結，請確認是否為有效的 Instagram Reels 連結",
            )

        # 生成唯一檔名
        file_id = str(uuid.uuid4())[:8]
        output_template = str(self.temp_dir / f"{file_id}")

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
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        try:
            # 在執行緒池中執行下載（yt-dlp 是同步的）
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._download_sync, url, ydl_opts
            )
            return result

        except Exception as e:
            logger.error(f"下載影片失敗: {e}")
            return DownloadResult(
                success=False,
                error_message=f"下載失敗: {str(e)}",
            )

    def _download_sync(self, url: str, ydl_opts: dict) -> DownloadResult:
        """同步下載方法"""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 取得影片資訊
                info = ydl.extract_info(url, download=True)

                if info is None:
                    return DownloadResult(
                        success=False,
                        error_message="無法取得影片資訊",
                    )

                title = info.get("title", "未知標題")

                # 找到下載的音訊檔案
                output_template = ydl_opts["outtmpl"]
                base_path = output_template.rsplit(".", 1)[0]
                audio_path = Path(f"{base_path}.mp3")

                if not audio_path.exists():
                    # 嘗試其他可能的副檔名
                    for ext in ["m4a", "webm", "opus"]:
                        alt_path = Path(f"{base_path}.{ext}")
                        if alt_path.exists():
                            audio_path = alt_path
                            break

                if not audio_path.exists():
                    return DownloadResult(
                        success=False,
                        error_message="無法找到下載的音訊檔案",
                    )

                logger.info(f"成功下載影片: {title}")
                return DownloadResult(
                    success=True,
                    audio_path=audio_path,
                    title=title,
                )

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "Private" in error_msg or "private" in error_msg:
                return DownloadResult(
                    success=False,
                    error_message="此影片為私人影片，無法下載",
                )
            elif "not available" in error_msg.lower():
                return DownloadResult(
                    success=False,
                    error_message="此影片已不存在或無法存取",
                )
            else:
                return DownloadResult(
                    success=False,
                    error_message=f"下載失敗: {error_msg}",
                )

        except Exception as e:
            return DownloadResult(
                success=False,
                error_message=f"下載時發生錯誤: {str(e)}",
            )

    async def cleanup(self, file_path: Path) -> None:
        """清理暫存檔案"""
        try:
            if file_path and file_path.exists():
                file_path.unlink()
                logger.info(f"已刪除暫存檔案: {file_path}")
        except Exception as e:
            logger.warning(f"刪除暫存檔案失敗: {e}")
