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
from app.services.downloader import InstagramDownloader, PostDownloadResult
from app.services.transcriber import WhisperTranscriber
from app.services.summarizer_factory import get_summarizer
from app.services.roam_sync import RoamSyncService
from app.services.visual_analyzer import VideoVisualAnalyzer
from app.services.download_logger import DownloadLogger
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
        self.summarizer = get_summarizer()
        self.roam_sync = RoamSyncService()
        self.visual_analyzer = VideoVisualAnalyzer()
        self.download_logger = DownloadLogger()
        self.application: Optional[Application] = None
        # 用於防止重複處理同一訊息
        self._processed_message_ids: set[int] = set()

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

    def _is_reel_url(self, url: str) -> bool:
        """判斷 URL 是否為 Reel（影片）"""
        return self.downloader.is_reel_url(url)

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
直接分享 Instagram 連結給我，我會自動幫你：
1. 下載影片或貼文圖片
2. 轉錄語音內容（影片）/ 分析圖片內容（貼文）
3. 生成摘要與重點
4. 同步到 Roam Research

⚡ 指令：
/start - 顯示此說明
/status - 查看系統狀態

🔗 支援的連結格式：
• instagram.com/reel/xxx（影片 Reels）
• instagram.com/reels/xxx（影片 Reels）
• instagram.com/p/xxx（貼文/圖片/輪播圖）

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
        # 忽略非訊息更新
        if update.message is None:
            return
        
        # 詳細日誌：記錄收到的訊息資訊
        from_user = update.message.from_user
        logger.info(f"收到訊息 - ID: {update.message.message_id}, "
                    f"來自: {from_user.username if from_user else 'Unknown'} "
                    f"(ID: {from_user.id if from_user else 'N/A'}, "
                    f"is_bot: {from_user.is_bot if from_user else 'N/A'})")

        # 忽略 Bot 自己的訊息
        if update.message.from_user and update.message.from_user.is_bot:
            logger.debug("忽略來自 Bot 的訊息")
            return
        
        # 忽略回覆給其他訊息的訊息（Bot 的回覆會有 reply_to_message）
        # 這可以防止 Bot 回覆中的連結被誤認為新連結
        if update.message.reply_to_message:
            logger.debug("忽略回覆訊息")
            return
        
        # 忽略編輯過的訊息（edited_message 會觸發另一個更新）
        if update.edited_message:
            return
        
        # 取得訊息 ID 用於防重複處理
        message_id = update.message.message_id
        
        # 檢查是否已處理過此訊息
        if message_id in self._processed_message_ids:
            logger.debug(f"訊息 ID {message_id} 已處理過，跳過")
            return
        
        # 標記為已處理（在處理開始前就標記，防止重試）
        self._processed_message_ids.add(message_id)
        
        # 限制記憶體中的 ID 數量（保留最近 1000 個）
        if len(self._processed_message_ids) > 1000:
            # 移除一半舊的 ID
            ids_list = sorted(self._processed_message_ids)
            self._processed_message_ids = set(ids_list[500:])

        chat_id = str(update.effective_chat.id)
        message_text = update.message.text or ""
        
        # 忽略空訊息
        if not message_text.strip():
            return

        if not self._is_authorized(chat_id):
            await update.message.reply_text("⛔ 您沒有使用此 Bot 的權限。")
            return

        # 提取 Instagram URL
        instagram_url = self._extract_instagram_url(message_text)

        if not instagram_url:
            # 只有當訊息看起來像是想分享連結時才回覆
            if "instagram" in message_text.lower() or "http" in message_text.lower():
                await update.message.reply_text(
                    "❓ 請分享有效的 Instagram Reels 連結。\n"
                    "支援格式：instagram.com/reel/xxx 或 instagram.com/p/xxx"
                )
            # 否則忽略訊息，不回覆
            return

        logger.info(f"收到訊息 ID {message_id}: {instagram_url}")

        # 發送處理中訊息
        processing_message = await update.message.reply_text("⏳ 處理中，請稍候...")

        # 判斷內容類型：Reel（影片） vs Post（貼文/圖片）
        is_reel = self._is_reel_url(instagram_url)
        
        if is_reel:
            # Reel（影片）處理流程
            await self._handle_reel(
                instagram_url, chat_id, processing_message
            )
        else:
            # 貼文（圖片）處理流程 - 嘗試使用 instaloader
            await self._handle_post(
                instagram_url, chat_id, processing_message
            )

    async def _handle_reel(
        self,
        instagram_url: str,
        chat_id: str,
        processing_message,
    ) -> None:
        """處理 Instagram Reel（影片）"""
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
            video_path = download_result.video_path
            video_title = download_result.title or "未知標題"
            video_caption = download_result.caption  # 影片說明文
            
            # 記錄下載資訊
            self.download_logger.log_reel_download(
                instagram_url=instagram_url,
                title=video_title,
                video_size_bytes=download_result.video_size_bytes,
                audio_size_bytes=download_result.audio_size_bytes,
            )

            try:
                # 步驟 2: 轉錄語音
                transcript = ""
                language = None
                transcribe_failed = False
                
                if audio_path and audio_path.exists():
                    transcribe_result = await self.transcriber.transcribe(audio_path)
                    if transcribe_result.success and transcribe_result.transcript.strip():
                        transcript = transcribe_result.transcript
                        language = transcribe_result.language
                    else:
                        transcribe_failed = True
                        logger.info("語音轉錄失敗或無語音內容，將只使用視覺分析")
                else:
                    transcribe_failed = True
                    logger.info("無音訊檔案，將只使用視覺分析")

                # 步驟 2.5: 視覺分析
                visual_description = None
                if video_path and video_path.exists():
                    await processing_message.edit_text("⏳ 分析畫面中...")
                    visual_result = await self.visual_analyzer.analyze(video_path)
                    if visual_result.success:
                        visual_description = visual_result.overall_visual_summary
                        logger.info(f"視覺分析完成，包含 {len(visual_result.frame_descriptions)} 幀描述")
                    else:
                        logger.warning(f"視覺分析失敗: {visual_result.error_message}")

                # 檢查：如果語音和視覺分析都失敗，回報錯誤
                if not transcript and not visual_description:
                    error_msg = "此影片無可辨識的語音內容，且視覺分析也失敗"
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.TRANSCRIBE, error_msg
                    )
                    await processing_message.edit_text(f"❌ 處理失敗\n\n{error_msg}")
                    return

                # 步驟 3: 使用 LLM 生成完整 Markdown 筆記
                await processing_message.edit_text("⏳ 生成筆記中...")
                
                # 判斷是否有語音內容
                has_audio = bool(transcript and transcript.strip())
                
                # 記錄是否有說明文
                if video_caption:
                    logger.info(f"影片說明文長度: {len(video_caption)} 字元")
                
                note_result = await self.summarizer.generate_note(
                    url=instagram_url,
                    title=video_title,
                    transcript=transcript if transcript else "",
                    visual_description=visual_description,
                    has_audio=has_audio,
                    caption=video_caption,
                )

                if not note_result.success:
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.SUMMARIZE, note_result.error_message
                    )
                    await processing_message.edit_text(
                        f"❌ 筆記生成失敗\n\n{note_result.error_message}\n\n已排入重試佇列。"
                    )
                    return

                # 步驟 4: 儲存 LLM 生成的 Markdown 筆記
                roam_result = await self.roam_sync.save_markdown_note(
                    video_title=video_title,
                    markdown_content=note_result.markdown_content
                )

                if not roam_result.success:
                    # Roam 同步失敗，但仍然回傳摘要
                    logger.warning(f"筆記儲存失敗: {roam_result.error_message}")
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.SYNC, roam_result.error_message
                    )

                # 構建回覆訊息（使用從筆記中提取的摘要和重點）
                reply_message = self._format_reply_simple(
                    summary=note_result.summary,
                    bullet_points=note_result.bullet_points,
                    roam_result=roam_result,
                    instagram_url=instagram_url
                )

                await processing_message.edit_text(reply_message)
                logger.info(f"處理完成: {instagram_url}")

            finally:
                # 清理暫存檔案
                if audio_path:
                    await self.downloader.cleanup(audio_path)
                if video_path:
                    await self.downloader.cleanup(video_path)

        except Exception as e:
            logger.error(f"處理過程發生錯誤: {e}")
            await processing_message.edit_text(
                f"❌ 處理過程發生錯誤\n\n{str(e)}\n\n請稍後再試。"
            )

    async def _handle_post(
        self,
        instagram_url: str,
        chat_id: str,
        processing_message,
    ) -> None:
        """處理 Instagram 貼文（圖片）"""
        try:
            # 步驟 1: 嘗試下載貼文圖片
            logger.info(f"開始處理貼文: {instagram_url}")
            await processing_message.edit_text("⏳ 下載貼文中...")
            
            post_result = await self.downloader.download_post(instagram_url)
            
            # 如果是影片貼文，改用影片處理流程
            if not post_result.success and post_result.content_type == "reel":
                logger.info("貼文為影片類型，切換至影片處理流程")
                await self._handle_reel(instagram_url, chat_id, processing_message)
                return
            
            if not post_result.success:
                await self._save_failed_task(
                    instagram_url, chat_id, ErrorType.DOWNLOAD, post_result.error_message
                )
                await processing_message.edit_text(
                    f"❌ 下載失敗\n\n{post_result.error_message}\n\n已排入重試佇列。"
                )
                return
            
            image_paths = post_result.image_paths
            caption = post_result.caption or ""
            post_title = post_result.title or "未知標題"
            
            # 記錄下載資訊
            content_type = "post_carousel" if len(image_paths) > 1 else "post_image"
            self.download_logger.log_post_download(
                instagram_url=instagram_url,
                title=post_title,
                image_paths=image_paths,
                content_type=content_type,
            )
            
            try:
                # 步驟 2: 分析圖片（每張圖片獨立分析）
                await processing_message.edit_text(
                    f"⏳ 分析圖片中... (共 {len(image_paths)} 張)"
                )
                
                visual_result = await self.visual_analyzer.analyze_images(image_paths)
                
                if not visual_result.success:
                    error_msg = visual_result.error_message or "圖片分析失敗"
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.TRANSCRIBE, error_msg
                    )
                    await processing_message.edit_text(f"❌ 處理失敗\n\n{error_msg}")
                    return
                
                visual_description = visual_result.overall_visual_summary
                logger.info(f"圖片分析完成，共 {len(visual_result.frame_descriptions)} 張")
                
                # 步驟 3: 使用 LLM 生成完整 Markdown 筆記
                await processing_message.edit_text("⏳ 生成筆記中...")
                
                note_result = await self.summarizer.generate_post_note(
                    url=instagram_url,
                    title=post_title,
                    caption=caption,
                    visual_description=visual_description,
                )
                
                if not note_result.success:
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.SUMMARIZE, note_result.error_message
                    )
                    await processing_message.edit_text(
                        f"❌ 筆記生成失敗\n\n{note_result.error_message}\n\n已排入重試佇列。"
                    )
                    return
                
                # 步驟 4: 儲存 LLM 生成的 Markdown 筆記（包含原始貼文文字）
                roam_result = await self.roam_sync.save_post_note(
                    post_title=post_title,
                    markdown_content=note_result.markdown_content,
                    caption=caption,
                )
                
                if not roam_result.success:
                    logger.warning(f"筆記儲存失敗: {roam_result.error_message}")
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.SYNC, roam_result.error_message
                    )
                
                # 構建回覆訊息
                reply_message = self._format_reply_simple(
                    summary=note_result.summary,
                    bullet_points=note_result.bullet_points,
                    roam_result=roam_result,
                    instagram_url=instagram_url
                )
                
                await processing_message.edit_text(reply_message)
                logger.info(f"貼文處理完成: {instagram_url}")
                
            finally:
                # 清理暫存圖片檔案（圖片已複製到 roam_backup）
                await self.downloader.cleanup_post_images(image_paths)
        
        except Exception as e:
            logger.error(f"處理貼文過程發生錯誤: {e}")
            await processing_message.edit_text(
                f"❌ 處理過程發生錯誤\n\n{str(e)}\n\n請稍後再試。"
            )

    def _format_reply(
        self,
        summary: str,
        bullet_points: list,
        roam_result,
        instagram_url: str,
        tools_and_skills: list = None,
        visual_observations: list = None,
    ) -> str:
        """格式化回覆訊息"""
        # 重點列表
        bullets_text = "\n".join([f"• {point}" for point in bullet_points])

        # 工具與技能部分
        tools_section = ""
        if tools_and_skills:
            tools_text = "\n".join([f"• {tool}" for tool in tools_and_skills])
            tools_section = f"\n🛠 工具與技能\n{tools_text}\n"

        # 視覺觀察部分
        visual_section = ""
        if visual_observations:
            visual_text = "\n".join([f"• {obs}" for obs in visual_observations])
            visual_section = f"\n👁 畫面觀察\n{visual_text}\n"

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
{tools_section}{visual_section}
{roam_section}

🔗 原始連結
{instagram_url}"""

    def _format_reply_simple(
        self,
        summary: str,
        bullet_points: list,
        roam_result,
        instagram_url: str,
    ) -> str:
        """格式化簡潔版回覆訊息（用於 LLM 生成筆記模式）"""
        # 重點列表
        bullets_text = "\n".join([f"• {point}" for point in bullet_points])

        # Roam 連結部分
        if roam_result.success and roam_result.page_url:
            roam_section = f"📎 筆記已儲存\n{roam_result.page_url}"
        else:
            roam_section = "📎 筆記儲存\n⚠️ 儲存失敗，已排入重試佇列"

        return f"""✅ 筆記生成完成！

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
            raise RuntimeError("Application not initialized. Call build_application first.")

        try:
            update = Update.de_json(update_data, self.application.bot)
            await self.application.process_update(update)
        except Exception as e:
            logger.error(f"處理更新失敗: {e}", exc_info=True)
            raise
