"""資料庫模型定義"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings


# 建立資料庫引擎
async_engine = create_async_engine(settings.database_url, echo=False)

# 建立非同步 Session 工廠
AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# 宣告式基礎類別
Base = declarative_base()


class ErrorType(str, Enum):
    """錯誤類型枚舉"""

    DOWNLOAD = "download"
    TRANSCRIBE = "transcribe"
    SUMMARIZE = "summarize"
    SYNC = "sync"


class TaskStatus(str, Enum):
    """任務狀態枚舉"""

    PENDING = "pending"
    SUCCESS = "success"
    ABANDONED = "abandoned"


class FailedTask(Base):
    """失敗記錄資料表"""

    __tablename__ = "failed_tasks"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    instagram_url: str = Column(Text, nullable=False)
    telegram_chat_id: str = Column(String(50), nullable=False)
    error_type: str = Column(String(20), nullable=False)
    error_message: Optional[str] = Column(Text, nullable=True)
    retry_count: int = Column(Integer, default=0)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    last_retry_at: Optional[datetime] = Column(DateTime, nullable=True)
    status: str = Column(String(20), default=TaskStatus.PENDING.value)

    def __repr__(self) -> str:
        return f"<FailedTask(id={self.id}, url={self.instagram_url[:30]}..., status={self.status})>"

    def increment_retry(self) -> None:
        """增加重試次數並更新時間"""
        self.retry_count += 1
        self.last_retry_at = datetime.utcnow()

    def mark_success(self) -> None:
        """標記為成功"""
        self.status = TaskStatus.SUCCESS.value
        self.last_retry_at = datetime.utcnow()

    def mark_abandoned(self) -> None:
        """標記為放棄"""
        self.status = TaskStatus.ABANDONED.value
        self.last_retry_at = datetime.utcnow()


class ProcessedURL(Base):
    """已處理 URL 記錄資料表"""

    __tablename__ = "processed_urls"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    url: str = Column(Text, nullable=False, unique=True, index=True)
    url_type: str = Column(String(20), nullable=False)  # instagram_reel, instagram_post, threads
    title: Optional[str] = Column(Text, nullable=True)
    telegram_chat_id: str = Column(String(50), nullable=False)
    note_path: Optional[str] = Column(Text, nullable=True)  # 筆記檔案路徑
    processed_at: datetime = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<ProcessedURL(id={self.id}, url={self.url[:40]}..., type={self.url_type})>"


async def init_db() -> None:
    """初始化資料庫，建立所有表格"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session() -> AsyncSession:
    """取得資料庫 Session"""
    async with AsyncSessionLocal() as session:
        yield session


# ==================== ProcessedURL 操作函數 ====================

async def check_url_processed(url: str) -> Optional[ProcessedURL]:
    """檢查 URL 是否已處理過
    
    Args:
        url: 要檢查的 URL
        
    Returns:
        ProcessedURL 物件（如果存在），否則 None
    """
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ProcessedURL).where(ProcessedURL.url == url)
        )
        return result.scalar_one_or_none()


async def save_processed_url(
    url: str,
    url_type: str,
    chat_id: str,
    title: Optional[str] = None,
    note_path: Optional[str] = None,
) -> ProcessedURL:
    """儲存已處理的 URL
    
    Args:
        url: 已處理的 URL
        url_type: URL 類型 (instagram_reel, instagram_post, threads)
        chat_id: Telegram chat ID
        title: 標題（可選）
        note_path: 筆記檔案路徑（可選）
        
    Returns:
        新建立的 ProcessedURL 物件
    """
    async with AsyncSessionLocal() as session:
        processed = ProcessedURL(
            url=url,
            url_type=url_type,
            telegram_chat_id=chat_id,
            title=title,
            note_path=note_path,
        )
        session.add(processed)
        await session.commit()
        await session.refresh(processed)
        return processed
