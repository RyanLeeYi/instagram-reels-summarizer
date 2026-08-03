"""處理流程的結果物件（F16）。

主 pipeline 與重試排程共用同一組 handler，需要一個共通的回傳型別：
handler 只回報「成功與否、失敗屬於哪一階段、最終回覆文字」，
由呼叫端決定要不要記失敗任務、要不要發 Telegram 訊息。
"""

from dataclasses import dataclass
from typing import Optional

from app.database.models import ErrorType


@dataclass(frozen=True)
class ProcessResult:
    """單一連結的處理結果。"""

    success: bool
    error_type: Optional[ErrorType] = None
    error_message: Optional[str] = None
    reply_text: Optional[str] = None  # 成功時的完整回覆內容（重試流程用它通知使用者）
    title: Optional[str] = None

    @classmethod
    def ok(cls, reply_text: str, title: Optional[str] = None) -> "ProcessResult":
        return cls(success=True, reply_text=reply_text, title=title)

    @classmethod
    def fail(cls, error_type: ErrorType, error_message: Optional[str]) -> "ProcessResult":
        return cls(success=False, error_type=error_type, error_message=error_message)
