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
from app.services.downloader import InstagramDownloader
from app.services.transcriber import WhisperTranscriber
from app.services.summarizer import OllamaSummarizer
from app.services.roam_sync import RoamSyncService


logger = logging.getLogger(__name__)


class RetryScheduler:
    """失敗任務重試排程器"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.downloader = InstagramDownloader()
        self.transcriber = WhisperTranscriber()
        self.summarizer = OllamaSummarizer()
        self.roam_sync = RoamSyncService()
        self.bot: Optional[Bot] = None

    def set_bot(self, bot: Bot) -> None:
        """設定 Telegram Bot 實例"""
        self.bot = bot

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
        """完整重試整個處理流程"""
        # 步驟 1: 下載
        download_result = await self.downloader.download(task.instagram_url)
        if not download_result.success:
            task.error_message = download_result.error_message
            task.error_type = ErrorType.DOWNLOAD.value
            return False

        audio_path = download_result.audio_path
        video_title = download_result.title or "未知標題"

        try:
            # 步驟 2: 轉錄
            transcribe_result = await self.transcriber.transcribe(audio_path)
            if not transcribe_result.success:
                task.error_message = transcribe_result.error_message
                task.error_type = ErrorType.TRANSCRIBE.value
                return False

            transcript = transcribe_result.transcript

            # 步驟 3: 摘要
            summary_result = await self.summarizer.summarize(transcript)
            if not summary_result.success:
                task.error_message = summary_result.error_message
                task.error_type = ErrorType.SUMMARIZE.value
                return False

            summary = summary_result.summary
            bullet_points = summary_result.bullet_points

            # 步驟 4: 同步到 Roam
            roam_result = await self.roam_sync.sync_to_roam(
                task.instagram_url, video_title, summary, bullet_points, transcript
            )

            if not roam_result.success:
                task.error_message = roam_result.error_message
                task.error_type = ErrorType.SYNC.value
                # 即使 Roam 同步失敗，也通知使用者摘要結果
                await self._notify_success(
                    task, summary, bullet_points, roam_result
                )
                return False

            # 通知使用者
            await self._notify_success(task, summary, bullet_points, roam_result)
            return True

        finally:
            # 清理暫存檔案
            if audio_path:
                await self.downloader.cleanup(audio_path)

    async def _retry_from_download(self, task: FailedTask) -> bool:
        """從下載步驟開始重試"""
        return await self._retry_full_process(task)

    async def _retry_sync_only(self, task: FailedTask) -> bool:
        """只重試 Roam 同步"""
        # 由於我們沒有儲存之前的摘要結果，需要重新處理
        return await self._retry_full_process(task)

    async def _notify_success(
        self,
        task: FailedTask,
        summary: str,
        bullet_points: list,
        roam_result,
    ) -> None:
        """通知使用者任務成功"""
        if self.bot is None:
            logger.warning("Bot 未設定，無法發送通知")
            return

        try:
            bullets_text = "\n".join([f"• {point}" for point in bullet_points])

            if roam_result.success and roam_result.page_url:
                roam_section = f"📎 Roam Research\n{roam_result.page_url}"
            else:
                roam_section = "📎 Roam Research\n⚠️ 同步失敗"

            message = f"""✅ 重試成功！

📝 摘要
{summary}

📌 重點
{bullets_text}

{roam_section}

🔗 原始連結
{task.instagram_url}"""

            await self.bot.send_message(
                chat_id=task.telegram_chat_id,
                text=message,
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
