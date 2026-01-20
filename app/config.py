"""應用程式設定模組"""

import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """應用程式設定"""

    # Telegram
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    telegram_allowed_chat_ids: str = Field(default="", env="TELEGRAM_ALLOWED_CHAT_IDS")

    # Whisper 本地模型設定
    whisper_model_size: str = Field(default="base", env="WHISPER_MODEL_SIZE")
    whisper_device: str = Field(default="cpu", env="WHISPER_DEVICE")

    # Ollama 本地 LLM 設定
    ollama_host: str = Field(default="http://localhost:11434", env="OLLAMA_HOST")
    ollama_model: str = Field(default="qwen2.5:7b", env="OLLAMA_MODEL")

    # Roam Research
    roam_graph_name: str = Field(..., env="ROAM_GRAPH_NAME")

    # 系統設定
    retry_interval_hours: int = Field(default=1, env="RETRY_INTERVAL_HOURS")
    max_retry_count: int = Field(default=3, env="MAX_RETRY_COUNT")
    temp_video_dir: str = Field(default="./temp_videos", env="TEMP_VIDEO_DIR")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./app.db", env="DATABASE_URL"
    )

    @property
    def allowed_chat_ids(self) -> List[str]:
        """解析允許的 chat_id 列表"""
        if not self.telegram_allowed_chat_ids:
            return []
        return [
            chat_id.strip()
            for chat_id in self.telegram_allowed_chat_ids.split(",")
            if chat_id.strip()
        ]

    @property
    def temp_video_path(self) -> Path:
        """取得暫存影片目錄路徑"""
        path = Path(self.temp_video_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# 建立全域設定實例
settings = Settings()
