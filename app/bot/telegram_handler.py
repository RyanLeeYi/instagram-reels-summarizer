"""Telegram Bot 處理器"""

import logging
import re
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from app.config import settings
from app.services.downloader import InstagramDownloader
from app.services.transcriber import WhisperTranscriber
from app.services.summarizer import OllamaSummarizer
from app.services.roam_sync import RoamSyncService
from app.database.models import (
    FailedTask,
    ErrorType,
    TaskStatus,
    AsyncSessionLocal,
)


logger = logging.getLogger(__name__)


class TelegramBotHandler:
    """Telegram Bot 訊息處理器"""

    # Instagram URL 正則表達式
    INSTAGRAM_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?instagram\.com/(?:reel|p|reels)/([A-Za-z0-9_-]+)"
    )

    def __init__(self):
        self.downloader = InstagramDownloader()
        self.transcriber = WhisperTranscriber()
        self.summarizer = OllamaSummarizer()
        self.roam_sync = RoamSyncService()
        self.application: Optional[Application] = None

    def _is_authorized(self, chat_id: str) -> bool:
        """檢查使用者是否有權限使用 Bot"""
        allowed_ids = settings.allowed_chat_ids
        if not allowed_ids:
            # 如果沒有設定，允許所有使用者
            return True
        return str(chat_id) in allowed_ids

    def _extract_instagram_url(self, text: str) -> Optional[str]:
        """從訊息中提取 Instagram URL"""
        match = self.INSTAGRAM_URL_PATTERN.search(text)
        if match:
            return match.group(0)
        return None

    async def _save_failed_task(
        self,
        instagram_url: str,
        chat_id: str,
        error_type: ErrorType,
        error_message: str,
    ) -> None:
        """儲存失敗的任務到資料庫"""
        async with AsyncSessionLocal() as session:
            task = FailedTask(
                instagram_url=instagram_url,
                telegram_chat_id=chat_id,
                error_type=error_type.value,
                error_message=error_message,
                status=TaskStatus.PENDING.value,
            )
            session.add(task)
            await session.commit()
            logger.info(f"已記錄失敗任務: {instagram_url}")

    async def start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """處理 /start 指令"""
        chat_id = str(update.effective_chat.id)

        if not self._is_authorized(chat_id):
            await update.message.reply_text("⛔ 您沒有使用此 Bot 的權限。")
            return

        welcome_message = """👋 歡迎使用 Instagram Reels 摘要 Bot！

📱 使用方式：
直接分享 Instagram Reels 連結給我，我會自動幫你：
1. 下載影片
2. 轉錄語音內容
3. 生成摘要與重點
4. 同步到 Roam Research

⚡ 指令：
/start - 顯示此說明
/status - 查看系統狀態

🔗 支援的連結格式：
• instagram.com/reel/xxx
• instagram.com/p/xxx
• instagram.com/reels/xxx

開始使用吧！✨"""

        await update.message.reply_text(welcome_message)

    async def status_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """處理 /status 指令"""
        chat_id = str(update.effective_chat.id)

        if not self._is_authorized(chat_id):
            await update.message.reply_text("⛔ 您沒有使用此 Bot 的權限。")
            return

        # 查詢待處理的失敗任務數量
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select, func

            result = await session.execute(
                select(func.count(FailedTask.id)).where(
                    FailedTask.status == TaskStatus.PENDING.value
                )
            )
            pending_count = result.scalar() or 0

        status_message = f"""📊 系統狀態

✅ Bot 運作正常
⏳ 待重試任務：{pending_count} 個
⏰ 重試間隔：每 {settings.retry_interval_hours} 小時
🔄 最大重試次數：{settings.max_retry_count} 次"""

        await update.message.reply_text(status_message)

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """處理一般訊息（Instagram 連結）"""
        chat_id = str(update.effective_chat.id)
        message_text = update.message.text or ""

        if not self._is_authorized(chat_id):
            await update.message.reply_text("⛔ 您沒有使用此 Bot 的權限。")
            return

        # 提取 Instagram URL
        instagram_url = self._extract_instagram_url(message_text)

        if not instagram_url:
            await update.message.reply_text(
                "❓ 請分享有效的 Instagram Reels 連結。\n"
                "支援格式：instagram.com/reel/xxx 或 instagram.com/p/xxx"
            )
            return

        # 發送處理中訊息
        processing_message = await update.message.reply_text("⏳ 處理中，請稍候...")

        try:
            # 步驟 1: 下載影片
            logger.info(f"開始處理: {instagram_url}")
            download_result = await self.downloader.download(instagram_url)

            if not download_result.success:
                await self._save_failed_task(
                    instagram_url, chat_id, ErrorType.DOWNLOAD, download_result.error_message
                )
                await processing_message.edit_text(
                    f"❌ 下載失敗\n\n{download_result.error_message}\n\n已排入重試佇列。"
                )
                return

            audio_path = download_result.audio_path
            video_title = download_result.title or "未知標題"

            try:
                # 步驟 2: 轉錄語音
                transcribe_result = await self.transcriber.transcribe(audio_path)

                if not transcribe_result.success:
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.TRANSCRIBE, transcribe_result.error_message
                    )
                    await processing_message.edit_text(
                        f"❌ 轉錄失敗\n\n{transcribe_result.error_message}"
                    )
                    return

                transcript = transcribe_result.transcript
                language = transcribe_result.language

                # 步驟 3: 生成摘要
                summary_result = await self.summarizer.summarize(transcript)

                if not summary_result.success:
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.SUMMARIZE, summary_result.error_message
                    )
                    await processing_message.edit_text(
                        f"❌ 摘要生成失敗\n\n{summary_result.error_message}\n\n已排入重試佇列。"
                    )
                    return

                summary = summary_result.summary
                bullet_points = summary_result.bullet_points

                # 步驟 4: 同步到 Roam Research
                roam_result = await self.roam_sync.sync_to_roam(
                    instagram_url, video_title, summary, bullet_points, transcript
                )

                if not roam_result.success:
                    # Roam 同步失敗，但仍然回傳摘要
                    logger.warning(f"Roam 同步失敗: {roam_result.error_message}")
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.SYNC, roam_result.error_message
                    )

                # 構建回覆訊息
                reply_message = self._format_reply(
                    summary, bullet_points, roam_result, instagram_url
                )

                await processing_message.edit_text(reply_message)
                logger.info(f"處理完成: {instagram_url}")

            finally:
                # 清理暫存檔案
                if audio_path:
                    await self.downloader.cleanup(audio_path)

        except Exception as e:
            logger.error(f"處理過程發生錯誤: {e}")
            await processing_message.edit_text(
                f"❌ 處理過程發生錯誤\n\n{str(e)}\n\n請稍後再試。"
            )

    def _format_reply(
        self,
        summary: str,
        bullet_points: list,
        roam_result,
        instagram_url: str,
    ) -> str:
        """格式化回覆訊息"""
        # 重點列表
        bullets_text = "\n".join([f"• {point}" for point in bullet_points])

        # Roam 連結部分
        if roam_result.success and roam_result.page_url:
            roam_section = f"📎 Roam Research\n{roam_result.page_url}"
        else:
            roam_section = "📎 Roam Research\n⚠️ 同步失敗，已排入重試佇列"

        return f"""✅ 摘要完成！

📝 摘要
{summary}

📌 重點
{bullets_text}

{roam_section}

🔗 原始連結
{instagram_url}"""

    def build_application(self) -> Application:
        """建立並設定 Telegram Application"""
        self.application = (
            Application.builder().token(settings.telegram_bot_token).build()
        )

        # 註冊指令處理器
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("status", self.status_command))

        # 註冊訊息處理器
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        return self.application

    async def setup_webhook(self, webhook_url: str) -> None:
        """設定 Webhook"""
        if self.application is None:
            self.build_application()

        await self.application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook 已設定: {webhook_url}")

    async def process_update(self, update_data: dict) -> None:
        """處理來自 Webhook 的更新"""
        if self.application is None:
            self.build_application()

        update = Update.de_json(update_data, self.application.bot)
        await self.application.process_update(update)
