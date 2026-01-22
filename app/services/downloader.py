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
    
    # 嘗試的瀏覽器順序
    BROWSERS_TO_TRY = ["chrome", "edge", "firefox", "brave", "opera", "chromium"]
    
    # cookies 檔案路徑
    COOKIES_FILE = Path("cookies.txt")

    def __init__(self):
        self.temp_dir = settings.temp_video_path
        self._working_browser: Optional[str] = None
        self._cookies_file: Optional[Path] = self._find_cookies_file()
    
    def _find_cookies_file(self) -> Optional[Path]:
        """尋找 cookies.txt 檔案"""
        if self.COOKIES_FILE.exists():
            logger.info(f"✅ 找到 cookies 檔案: {self.COOKIES_FILE.absolute()}")
            return self.COOKIES_FILE
        return None

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

        # 先下載影片（供視覺分析用）
        video_ydl_opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": output_template + "_video.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        # 下載音訊
        audio_ydl_opts = {
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
        
        # 優先使用 cookies.txt 檔案
        if self._cookies_file:
            video_ydl_opts["cookiefile"] = str(self._cookies_file)
            audio_ydl_opts["cookiefile"] = str(self._cookies_file)
            logger.info("使用 cookies.txt 進行下載")
        elif self._working_browser:
            # 備用：使用瀏覽器 cookies
            video_ydl_opts["cookiesfrombrowser"] = (self._working_browser,)
            audio_ydl_opts["cookiesfrombrowser"] = (self._working_browser,)
            logger.info(f"使用 {self._working_browser} 的 cookies 進行下載")

        try:
            # 在執行緒池中執行下載（yt-dlp 是同步的）
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._download_sync, url, audio_ydl_opts, video_ydl_opts
            )
            return result

        except Exception as e:
            logger.error(f"下載影片失敗: {e}")
            return DownloadResult(
                success=False,
                error_message=f"下載失敗: {str(e)}",
            )

    def _download_sync(self, url: str, audio_ydl_opts: dict, video_ydl_opts: dict = None) -> DownloadResult:
        """同步下載方法"""
        
        # 如果沒有 cookies 檔案且還沒找到可用的瀏覽器，嘗試各個瀏覽器
        if not self._cookies_file and not self._working_browser:
            for browser in self.BROWSERS_TO_TRY:
                try:
                    test_opts = {
                        "quiet": True,
                        "no_warnings": True,
                        "extract_flat": True,
                        "cookiesfrombrowser": (browser,),
                    }
                    with yt_dlp.YoutubeDL(test_opts) as ydl:
                        # 測試是否能取得影片資訊
                        info = ydl.extract_info(url, download=False)
                        if info:
                            self._working_browser = browser
                            logger.info(f"✅ 使用 {browser} 的 cookies 成功")
                            # 更新下載選項
                            video_ydl_opts["cookiesfrombrowser"] = (browser,)
                            audio_ydl_opts["cookiesfrombrowser"] = (browser,)
                            break
                except Exception as e:
                    logger.debug(f"{browser} 無法使用: {e}")
                    continue
            
            if not self._working_browser:
                logger.warning("⚠️ 無法從任何瀏覽器取得 cookies，請提供 cookies.txt 檔案")
        
        try:
            video_path = None
            
            # 先下載影片（如果提供了 video_ydl_opts）
            if video_ydl_opts:
                try:
                    with yt_dlp.YoutubeDL(video_ydl_opts) as ydl:
                        ydl.download([url])
                        
                    # 找到下載的影片檔案
                    video_template = video_ydl_opts["outtmpl"]
                    if isinstance(video_template, dict):
                        video_template = video_template.get("default", "")
                    video_base = video_template.rsplit(".", 1)[0] if "." in video_template else video_template
                    
                    for ext in ["mp4", "webm", "mkv"]:
                        vpath = Path(f"{video_base}.{ext}")
                        if vpath.exists():
                            video_path = vpath
                            logger.info(f"成功下載影片: {video_path}")
                            break
                except Exception as e:
                    logger.warning(f"影片下載失敗，將只進行音訊分析: {e}")
            
            # 下載音訊
            with yt_dlp.YoutubeDL(audio_ydl_opts) as ydl:
                # 取得影片資訊
                info = ydl.extract_info(url, download=True)

                if info is None:
                    return DownloadResult(
                        success=False,
                        error_message="無法取得影片資訊",
                    )

                title = info.get("title", "未知標題")

                # 找到下載的音訊檔案
                output_template = audio_ydl_opts["outtmpl"]
                # 處理 outtmpl 可能是字典或字串的情況
                if isinstance(output_template, dict):
                    output_template = output_template.get("default", "")
                base_path = output_template.rsplit(".", 1)[0] if "." in output_template else output_template
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
                    video_path=video_path,
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
