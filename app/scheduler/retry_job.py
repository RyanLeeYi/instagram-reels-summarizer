"""失敗任務重試排程"""

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from telegram import Bot

from app.config import settings
from app.database.models import (
    FailedTask,
    ErrorType,
    TaskStatus,
    AsyncSessionLocal,
)
from app.bot.process_result import ProcessResult


logger = logging.getLogger(__name__)

RETRY_SUCCESS_PREFIX = "✅ 重試成功！\n\n"


class RetryScheduler:
    """失敗任務重試排程器"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.bot: Optional[Bot] = None
        # 主 pipeline 入口（TelegramBotHandler），由 main.py 注入。
        # 重試不自己走一條流程——那正是 F16 之前漂移的來源。
        self.handler = None

    def set_bot(self, bot: Bot) -> None:
        """設定 Telegram Bot 實例"""
        self.bot = bot

    def set_handler(self, handler) -> None:
        """注入主 pipeline 入口（需具備 process_url）"""
        self.handler = handler

    def start(self) -> None:
        """啟動排程器"""
        # 新增重試任務，每小時執行一次
        self.scheduler.add_job(
            self.retry_failed_tasks,
            trigger=IntervalTrigger(hours=settings.retry_interval_hours),
            id="retry_failed_tasks",
            name="重試失敗任務",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info(
            f"排程器已啟動，重試間隔: 每 {settings.retry_interval_hours} 小時"
        )

    def stop(self) -> None:
        """停止排程器"""
        self.scheduler.shutdown()
        logger.info("排程器已停止")

    async def retry_failed_tasks(self) -> None:
        """重試所有待處理的失敗任務"""
        logger.info("開始執行失敗任務重試...")

        async with AsyncSessionLocal() as session:
            # 查詢所有待處理的任務
            result = await session.execute(
                select(FailedTask).where(
                    FailedTask.status == TaskStatus.PENDING.value,
                    FailedTask.retry_count < settings.max_retry_count,
                )
            )
            tasks = result.scalars().all()

            logger.info(f"找到 {len(tasks)} 個待重試任務")

            for task in tasks:
                await self._retry_single_task(session, task)

            await session.commit()

        logger.info("失敗任務重試完成")

    async def _retry_single_task(self, session, task: FailedTask) -> None:
        """重試單一任務"""
        logger.info(f"重試任務: {task.instagram_url} (第 {task.retry_count + 1} 次)")

        task.increment_retry()

        try:
            # 根據錯誤類型決定從哪裡開始重試
            error_type = ErrorType(task.error_type)

            if error_type == ErrorType.DOWNLOAD:
                success = await self._retry_full_process(task)
            elif error_type == ErrorType.TRANSCRIBE:
                success = await self._retry_from_download(task)
            elif error_type == ErrorType.SUMMARIZE:
                # 需要重新下載和轉錄
                success = await self._retry_full_process(task)
            elif error_type == ErrorType.SYNC:
                # 只需要重新同步（需要有之前的資料）
                success = await self._retry_sync_only(task)
            else:
                success = await self._retry_full_process(task)

            if success:
                task.mark_success()
                logger.info(f"任務重試成功: {task.instagram_url}")
            else:
                if task.retry_count >= settings.max_retry_count:
                    task.mark_abandoned()
                    await self._notify_abandoned(task)
                    logger.warning(
                        f"任務已達最大重試次數，標記為放棄: {task.instagram_url}"
                    )

        except Exception as e:
            logger.error(f"重試任務時發生錯誤: {e}")
            if task.retry_count >= settings.max_retry_count:
                task.mark_abandoned()
                await self._notify_abandoned(task)

    async def _retry_full_process(self, task: FailedTask) -> bool:
        """委派給主 pipeline 的統一入口重跑（F16）。

        重試與使用者手動傳連結走完全相同的流程：型別分流、視覺分析、
        vault 知識庫寫入一應俱全，不再是這裡自己維護的簡化版。
        """
        if self.handler is None:
            # 寧可失敗也不要偷偷跑一條會漂移的舊路徑
            task.error_message = "重試流程未注入主 pipeline handler，無法重試"
            logger.error(task.error_message)
            return False

        result: ProcessResult = await self.handler.process_url(
            task.instagram_url,
            task.telegram_chat_id,
            None,  # 無進度訊息可編輯；成功後另發通知
            retry_mode=True,
        )

        if not result.success:
            if result.error_type is not None:
                task.error_type = result.error_type.value
            task.error_message = result.error_message
            return False

        await self._notify_retry_success(task, result)
        return True

    async def _retry_from_download(self, task: FailedTask) -> bool:
        """從下載步驟開始重試"""
        return await self._retry_full_process(task)

    async def _retry_sync_only(self, task: FailedTask) -> bool:
        """只重試 Roam 同步"""
        # 由於我們沒有儲存之前的摘要結果，需要重新處理
        return await self._retry_full_process(task)

    async def _notify_retry_success(self, task: FailedTask, result: ProcessResult) -> None:
        """通知使用者重試成功——內容沿用主 pipeline 產出的回覆，兩條路徑一致。"""
        if self.bot is None:
            logger.warning("Bot 未設定，無法發送通知")
            return

        try:
            body = result.reply_text or f"🔗 {task.instagram_url}"
            await self.bot.send_message(
                chat_id=task.telegram_chat_id,
                text=RETRY_SUCCESS_PREFIX + body,
            )
        except Exception as e:
            logger.error(f"發送通知失敗: {e}")

    async def _notify_abandoned(self, task: FailedTask) -> None:
        """通知使用者任務已放棄"""
        if self.bot is None:
            logger.warning("Bot 未設定，無法發送通知")
            return

        try:
            message = f"""❌ 處理失敗

重試已達上限（{settings.max_retry_count} 次），任務已放棄。

🔗 連結：{task.instagram_url}
📝 錯誤：{task.error_message}

請手動重新分享此連結再試一次。"""

            await self.bot.send_message(
                chat_id=task.telegram_chat_id,
                text=message,
            )

        except Exception as e:
            logger.error(f"發送通知失敗: {e}")


# 建立全域排程器實例
retry_scheduler = RetryScheduler()
