"""應用程式設定模組"""

from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """應用程式設定"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Telegram
    telegram_bot_token: str
    telegram_allowed_chat_ids: str = Field(default="")

    # Whisper 本地模型設定
    whisper_model_size: str = Field(default="base")
    whisper_device: str = Field(default="cpu")

    # Ollama 本地 LLM 設定
    ollama_host: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="qwen3:8b")
    ollama_vision_model: str = Field(default="gemma3:4b")

    # 影片視覺分析 backend（ollama / antigravity）
    visual_analyzer_backend: str = Field(default="ollama")
    antigravity_cli_path: str = Field(default="agy")
    antigravity_vision_agent: str = Field(default="reels-vision")
    antigravity_vision_model: str = Field(default="gemini-3.6-flash-high")
    antigravity_vision_timeout_seconds: int = Field(default=120)

    # 摘要服務設定 (ollama, claude, copilot)
    summarizer_backend: str = Field(default="ollama")
    claude_model: str = Field(default="sonnet")  # sonnet, opus, haiku
    copilot_model: str = Field(default="claude-sonnet-4.5")  # claude-sonnet-4.5, gpt-5, etc.

    # Roam Research
    roam_graph_name: str

    # Webhook 設定
    webhook_url: str = Field(default="")

    # Claude Code 同步設定
    claude_code_sync_enabled: bool = Field(default=False)

    # 系統設定
    retry_enabled: bool = Field(default=True)
    retry_interval_hours: int = Field(default=1)
    max_retry_count: int = Field(default=3)
    temp_video_dir: str = Field(default="./temp_videos")
    database_url: str = Field(default="sqlite+aiosqlite:///./app.db")

    # Prompt 模板設定
    prompts_path: str = Field(default="./app/prompts")

    # Instaloader Session 設定
    instaloader_session_path: str = Field(default="./temp_videos")

    # Threads 設定
    threads_username: str = Field(default="")
    threads_password: str = Field(default="")
    threads_enabled: bool = Field(default=True)
    threads_fetch_replies: bool = Field(default=True)
    threads_max_replies: int = Field(default=50)

    # 知識庫（Obsidian vault）整併設定 — 取代 NotebookLM（docs/prd/vault-sync.md）
    vault_sync_enabled: bool = Field(default=True)
    vault_path: str = Field(default=r"C:\Users\user\OneDrive\Desktop\Obsidian")
    vault_link_enrich: bool = Field(default=True)

    # NotebookLM 設定 (Chrome CDP 連線)——已被 vault sync 取代，保留程式碼備用
    notebooklm_enabled: bool = Field(default=False)
    notebooklm_cdp_url: str = Field(default="http://localhost:9222")
    notebooklm_upload_video: bool = Field(default=True)
    notebooklm_chrome_profile: str = Field(
        default="",
        description="Chrome CDP 專用 user-data-dir，空字串時使用 ~/.chrome-cdp-notebooklm",
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

    @property
    def instaloader_session_dir(self) -> Path:
        """取得 Instaloader session 存放目錄"""
        path = Path(self.instaloader_session_path)
        path.mkdir(parents=True, exist_ok=True)
        return path


# 建立全域設定實例
settings = Settings()
