"""下載記錄服務 - 記錄影片/圖片大小與連結"""

import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.config import settings


logger = logging.getLogger(__name__)


@dataclass
class DownloadLogEntry:
    """下載記錄條目"""
    
    timestamp: str  # ISO 格式時間戳記
    instagram_url: str  # Instagram 連結
    content_type: str  # "reel", "post_image", "post_carousel"
    title: Optional[str] = None  # 標題
    video_size_bytes: Optional[int] = None  # 影片大小（位元組）
    audio_size_bytes: Optional[int] = None  # 音訊大小（位元組）
    image_sizes_bytes: Optional[List[int]] = None  # 圖片大小列表（位元組）
    total_size_bytes: Optional[int] = None  # 總大小（位元組）
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return asdict(self)


class DownloadLogger:
    """下載記錄器"""
    
    def __init__(self, log_dir: Optional[Path] = None):
        """
        初始化下載記錄器
        
        Args:
            log_dir: 記錄檔案目錄，預設為專案根目錄下的 logs 資料夾
        """
        if log_dir:
            self.log_dir = Path(log_dir)
        else:
            # 使用 temp_video_dir 的父目錄下的 logs 資料夾
            self.log_dir = Path(settings.temp_video_dir).parent / "logs"
        
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.json_log_path = self.log_dir / "download_log.json"
        self.csv_log_path = self.log_dir / "download_log.csv"
        
        # 確保 JSON 檔案存在
        if not self.json_log_path.exists():
            self._init_json_log()
        
        # 確保 CSV 檔案存在且有標題
        if not self.csv_log_path.exists():
            self._init_csv_log()
    
    def _init_json_log(self) -> None:
        """初始化 JSON 記錄檔"""
        with open(self.json_log_path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        logger.info(f"已建立下載記錄檔: {self.json_log_path}")
    
    def _init_csv_log(self) -> None:
        """初始化 CSV 記錄檔"""
        headers = [
            "timestamp",
            "instagram_url",
            "content_type",
            "title",
            "video_size_bytes",
            "audio_size_bytes",
            "image_sizes_bytes",
            "total_size_bytes",
            "total_size_readable",
        ]
        with open(self.csv_log_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
        logger.info(f"已建立 CSV 記錄檔: {self.csv_log_path}")
    
    @staticmethod
    def format_size(size_bytes: Optional[int]) -> str:
        """格式化檔案大小為可讀格式"""
        if size_bytes is None:
            return "N/A"
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
    
    def log_reel_download(
        self,
        instagram_url: str,
        title: Optional[str] = None,
        video_size_bytes: Optional[int] = None,
        audio_size_bytes: Optional[int] = None,
    ) -> DownloadLogEntry:
        """
        記錄 Reel（影片）下載
        
        Args:
            instagram_url: Instagram 連結
            title: 影片標題
            video_size_bytes: 影片檔案大小（位元組）
            audio_size_bytes: 音訊檔案大小（位元組）
            
        Returns:
            DownloadLogEntry: 記錄條目
        """
        total_size = 0
        if video_size_bytes:
            total_size += video_size_bytes
        if audio_size_bytes:
            total_size += audio_size_bytes
        
        entry = DownloadLogEntry(
            timestamp=datetime.now().isoformat(),
            instagram_url=instagram_url,
            content_type="reel",
            title=title,
            video_size_bytes=video_size_bytes,
            audio_size_bytes=audio_size_bytes,
            total_size_bytes=total_size if total_size > 0 else None,
        )
        
        self._save_entry(entry)
        logger.info(
            f"已記錄 Reel 下載: {instagram_url} | "
            f"總大小: {self.format_size(entry.total_size_bytes)}"
        )
        return entry
    
    def log_post_download(
        self,
        instagram_url: str,
        title: Optional[str] = None,
        image_paths: Optional[List[Path]] = None,
        content_type: str = "post_image",
    ) -> DownloadLogEntry:
        """
        記錄貼文（圖片）下載
        
        Args:
            instagram_url: Instagram 連結
            title: 貼文標題
            image_paths: 圖片路徑列表
            content_type: 內容類型（post_image 或 post_carousel）
            
        Returns:
            DownloadLogEntry: 記錄條目
        """
        image_sizes = []
        total_size = 0
        
        if image_paths:
            for path in image_paths:
                if path.exists():
                    size = path.stat().st_size
                    image_sizes.append(size)
                    total_size += size
        
        entry = DownloadLogEntry(
            timestamp=datetime.now().isoformat(),
            instagram_url=instagram_url,
            content_type=content_type,
            title=title,
            image_sizes_bytes=image_sizes if image_sizes else None,
            total_size_bytes=total_size if total_size > 0 else None,
        )
        
        self._save_entry(entry)
        logger.info(
            f"已記錄貼文下載: {instagram_url} | "
            f"圖片數: {len(image_sizes)} | "
            f"總大小: {self.format_size(entry.total_size_bytes)}"
        )
        return entry
    
    def log_threads_download(
        self,
        threads_url: str,
        title: Optional[str] = None,
        image_paths: Optional[List[Path]] = None,
        video_paths: Optional[List[Path]] = None,
        audio_paths: Optional[List[Path]] = None,
        content_type: str = "threads",
    ) -> DownloadLogEntry:
        """
        記錄 Threads 貼文下載
        
        Args:
            threads_url: Threads 連結
            title: 貼文標題（通常為 @author）
            image_paths: 圖片路徑列表
            video_paths: 影片路徑列表
            audio_paths: 音訊路徑列表
            content_type: 內容類型（threads 或 threads_conversation）
            
        Returns:
            DownloadLogEntry: 記錄條目
        """
        image_sizes = []
        video_size = 0
        audio_size = 0
        total_size = 0
        
        if image_paths:
            for path in image_paths:
                if path.exists():
                    size = path.stat().st_size
                    image_sizes.append(size)
                    total_size += size
        
        if video_paths:
            for path in video_paths:
                if path.exists():
                    size = path.stat().st_size
                    video_size += size
                    total_size += size
        
        if audio_paths:
            for path in audio_paths:
                if path.exists():
                    size = path.stat().st_size
                    audio_size += size
                    total_size += size
        
        entry = DownloadLogEntry(
            timestamp=datetime.now().isoformat(),
            instagram_url=threads_url,
            content_type=content_type,
            title=title,
            video_size_bytes=video_size if video_size > 0 else None,
            audio_size_bytes=audio_size if audio_size > 0 else None,
            image_sizes_bytes=image_sizes if image_sizes else None,
            total_size_bytes=total_size if total_size > 0 else None,
        )
        
        self._save_entry(entry)
        media_counts = []
        if image_paths:
            media_counts.append(f"{len(image_paths)} 張圖片")
        if video_paths:
            media_counts.append(f"{len(video_paths)} 個影片")
        if audio_paths:
            media_counts.append(f"{len(audio_paths)} 個音訊")
        media_info = ", ".join(media_counts) if media_counts else "純文字"
        logger.info(
            f"已記錄 Threads 下載: {threads_url} | "
            f"媒體: {media_info} | "
            f"總大小: {self.format_size(entry.total_size_bytes)}"
        )
        return entry

    def _save_entry(self, entry: DownloadLogEntry) -> None:
        """儲存記錄條目到 JSON 和 CSV"""
        # 儲存到 JSON
        self._append_to_json(entry)
        # 儲存到 CSV
        self._append_to_csv(entry)
    
    def _append_to_json(self, entry: DownloadLogEntry) -> None:
        """追加記錄到 JSON 檔案"""
        try:
            # 讀取現有記錄
            with open(self.json_log_path, "r", encoding="utf-8") as f:
                logs = json.load(f)
            
            # 追加新記錄
            logs.append(entry.to_dict())
            
            # 寫回檔案
            with open(self.json_log_path, "w", encoding="utf-8") as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"寫入 JSON 記錄失敗: {e}")
    
    def _append_to_csv(self, entry: DownloadLogEntry) -> None:
        """追加記錄到 CSV 檔案"""
        try:
            with open(self.csv_log_path, "a", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    entry.timestamp,
                    entry.instagram_url,
                    entry.content_type,
                    entry.title or "",
                    entry.video_size_bytes or "",
                    entry.audio_size_bytes or "",
                    json.dumps(entry.image_sizes_bytes) if entry.image_sizes_bytes else "",
                    entry.total_size_bytes or "",
                    self.format_size(entry.total_size_bytes),
                ])
        except Exception as e:
            logger.error(f"寫入 CSV 記錄失敗: {e}")
    
    def get_all_logs(self) -> List[dict]:
        """取得所有記錄"""
        try:
            with open(self.json_log_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"讀取記錄失敗: {e}")
            return []
    
    def get_statistics(self) -> dict:
        """取得下載統計"""
        logs = self.get_all_logs()
        
        total_reels = 0
        total_posts = 0
        total_threads = 0
        total_size = 0
        
        for log in logs:
            content_type = log.get("content_type", "")
            if content_type == "reel":
                total_reels += 1
            elif content_type.startswith("threads"):
                total_threads += 1
            else:
                total_posts += 1
            
            if log.get("total_size_bytes"):
                total_size += log["total_size_bytes"]
        
        return {
            "total_downloads": len(logs),
            "total_reels": total_reels,
            "total_posts": total_posts,
            "total_threads": total_threads,
            "total_size_bytes": total_size,
            "total_size_readable": self.format_size(total_size),
        }
