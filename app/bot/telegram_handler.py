"""Telegram Bot 處理器"""

import hashlib
import logging
import re
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

from app.config import settings
from app.services.downloader import InstagramDownloader, PostDownloadResult
from app.services.threads_downloader import (
    ThreadsDownloader,
    ThreadsDownloadResult,
    ThreadsMediaDownloadResult,
)
from app.services.transcriber import WhisperTranscriber
from app.services.summarizer_factory import get_summarizer
from app.services.roam_sync import RoamSyncService
from app.services.visual_analyzer import VideoVisualAnalyzer
from app.services.download_logger import DownloadLogger
from app.services.notebooklm_sync import NotebookLMSyncService, NotebookLMResult
from app.database.models import (
    FailedTask,
    ErrorType,
    TaskStatus,
    AsyncSessionLocal,
    check_url_processed,
    save_processed_url,
    delete_processed_url,
)
from telegram.error import TelegramError, TimedOut, NetworkError


logger = logging.getLogger(__name__)


class TelegramBotHandler:
    """Telegram Bot 訊息處理器"""

    # Instagram URL 正則表達式
    INSTAGRAM_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?instagram\.com/(?:reel|p|reels)/([A-Za-z0-9_-]+)"
    )

    # Threads URL 正則表達式（支援 threads.net 和 threads.com）
    THREADS_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?threads\.(?:net|com)/(?:@[\w.]+/post|t)/([A-Za-z0-9_-]+)"
    )

    def __init__(self):
        self.downloader = InstagramDownloader()
        self.threads_downloader = ThreadsDownloader()
        self.transcriber = WhisperTranscriber()
        self.summarizer = get_summarizer()
        self.roam_sync = RoamSyncService()
        self.visual_analyzer = VideoVisualAnalyzer()
        self.download_logger = DownloadLogger()
        self.notebooklm_sync: Optional[NotebookLMSyncService] = (
            NotebookLMSyncService() if settings.notebooklm_enabled else None
        )
        self.application: Optional[Application] = None
        # 用於防止重複處理同一訊息
        self._processed_message_ids: set[int] = set()
        # 用於暫存待確認的筆記
        self._pending_notes: dict = {}
        # 用於 reprocess callback_data 的 URL 映射（避免超過 Telegram 64-byte 限制）
        self._reprocess_urls: dict[str, str] = {}

    def _is_authorized(self, chat_id: str) -> bool:
        """檢查使用者是否有權限使用 Bot"""
        allowed_ids = settings.allowed_chat_ids
        if not allowed_ids:
            # 如果沒有設定，允許所有使用者
            return True
        return str(chat_id) in allowed_ids

    async def _safe_edit_message(self, message, text: str) -> bool:
        """安全地編輯訊息，處理網路超時等錯誤
        
        Args:
            message: Telegram 訊息物件（可能為 None）
            text: 要更新的文字
            
        Returns:
            bool: 是否成功編輯訊息
        """
        if message is None:
            logger.debug("訊息物件為 None，跳過編輯")
            return False
        try:
            await message.edit_text(text)
            return True
        except (TimedOut, NetworkError) as e:
            logger.warning(f"編輯訊息超時或網路錯誤，無法通知使用者: {e}")
            return False
        except TelegramError as e:
            logger.warning(f"編輯訊息失敗: {e}")
            return False

    def _extract_instagram_url(self, text: str) -> Optional[str]:
        """從訊息中提取 Instagram URL"""
        match = self.INSTAGRAM_URL_PATTERN.search(text)
        if match:
            return match.group(0)
        return None

    def _extract_threads_url(self, text: str) -> Optional[str]:
        """從訊息中提取 Threads URL"""
        match = self.THREADS_URL_PATTERN.search(text)
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

        welcome_message = """👋 歡迎使用社群內容摘要 Bot！

📱 使用方式：
直接分享連結給我，我會自動幫你：
1. 下載影片/貼文/串文
2. 轉錄語音（影片）/ 分析圖片 / 整理文字
3. 生成摘要與重點
4. 同步到 Roam Research

⚡ 指令：
/start - 顯示此說明
/status - 查看系統狀態

🔗 支援的連結格式：
📸 Instagram
• instagram.com/reel/xxx（影片 Reels）
• instagram.com/reels/xxx（影片 Reels）
• instagram.com/p/xxx（貼文/圖片/輪播圖）

🧵 Threads
• threads.net/@user/post/xxx
• threads.net/t/xxx

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

        # 優先檢查是否為 Threads URL
        threads_url = self._extract_threads_url(message_text)
        if threads_url and settings.threads_enabled:
            logger.info(f"收到訊息 ID {message_id}: {threads_url} (Threads)")
            
            # 檢查是否已處理過
            existing = await check_url_processed(threads_url)
            if existing:
                logger.info(f"URL 已處理過: {threads_url}")
                reprocess_key = hashlib.md5(threads_url.encode()).hexdigest()[:12]
                self._reprocess_urls[reprocess_key] = threads_url
                keyboard = [
                    [
                        InlineKeyboardButton("🔄 重新處理", callback_data=f"reprocess:{reprocess_key}"),
                        InlineKeyboardButton("⏭ 跳過", callback_data="skip"),
                    ]
                ]
                await update.message.reply_text(
                    f"📝 此連結已於 {existing.processed_at.strftime('%Y-%m-%d %H:%M')} 處理過\n\n"
                    f"標題：{existing.title or '未知'}\n\n"
                    f"是否要重新處理？",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return
            
            try:
                processing_message = await update.message.reply_text("⏳ 處理 Threads 串文中...")
            except (TimedOut, NetworkError) as e:
                logger.warning(f"發送初始訊息超時，繼續處理: {e}")
                processing_message = None
            await self._handle_threads(threads_url, chat_id, processing_message)
            return

        # 提取 Instagram URL
        instagram_url = self._extract_instagram_url(message_text)

        if not instagram_url:
            # 只有當訊息看起來像是想分享連結時才回覆
            if "instagram" in message_text.lower() or "threads" in message_text.lower() or "http" in message_text.lower():
                await update.message.reply_text(
                    "❓ 請分享有效的連結。\n"
                    "支援格式：\n"
                    "• instagram.com/reel/xxx\n"
                    "• instagram.com/p/xxx\n"
                    "• threads.net/@user/post/xxx"
                )
            # 否則忽略訊息，不回覆
            return

        logger.info(f"收到訊息 ID {message_id}: {instagram_url}")

        # 檢查是否已處理過
        existing = await check_url_processed(instagram_url)
        if existing:
            logger.info(f"URL 已處理過: {instagram_url}")
            reprocess_key = hashlib.md5(instagram_url.encode()).hexdigest()[:12]
            self._reprocess_urls[reprocess_key] = instagram_url
            keyboard = [
                [
                    InlineKeyboardButton("🔄 重新處理", callback_data=f"reprocess:{reprocess_key}"),
                    InlineKeyboardButton("⏭ 跳過", callback_data="skip"),
                ]
            ]
            await update.message.reply_text(
                f"📝 此連結已於 {existing.processed_at.strftime('%Y-%m-%d %H:%M')} 處理過\n\n"
                f"標題：{existing.title or '未知'}\n\n"
                f"是否要重新處理？",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # 發送處理中訊息（處理網路超時）
        try:
            processing_message = await update.message.reply_text("⏳ 處理中，請稍候...")
        except (TimedOut, NetworkError) as e:
            logger.warning(f"發送初始訊息超時，繼續處理: {e}")
            processing_message = None

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
                await self._safe_edit_message(
                    processing_message,
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
                    await self._safe_edit_message(processing_message, "⏳ 分析畫面中...")
                    visual_result = await self.visual_analyzer.analyze(video_path)
                    if visual_result.success:
                        visual_description = visual_result.overall_visual_summary
                        logger.info(f"視覺分析完成，包含 {len(visual_result.frame_descriptions)} 幀描述")
                    else:
                        logger.warning(f"視覺分析失敗: {visual_result.error_message}")

                # 檢查：如果語音、視覺分析和貼文說明都沒有，回報錯誤
                has_caption = bool(video_caption and video_caption.strip())
                if not transcript and not visual_description and not has_caption:
                    error_msg = "此影片無可辨識的語音內容，視覺分析也失敗，且無貼文說明"
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.TRANSCRIBE, error_msg
                    )
                    await self._safe_edit_message(processing_message, f"❌ 處理失敗\n\n{error_msg}")
                    return
                
                # 如果逐字稿為空但有貼文說明或視覺分析，記錄 fallback 資訊
                if not transcript and (has_caption or visual_description):
                    fallback_sources = []
                    if visual_description:
                        fallback_sources.append("視覺分析")
                    if has_caption:
                        fallback_sources.append("貼文說明")
                    logger.info(f"逐字稿為空，將使用 {' + '.join(fallback_sources)} 進行摘要")

                # 步驟 3: 使用 LLM 生成完整 Markdown 筆記
                await self._safe_edit_message(processing_message, "⏳ 生成筆記中...")
                
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
                    await self._safe_edit_message(
                        processing_message,
                        f"❌ 筆記生成失敗\n\n{note_result.error_message}\n\n已排入重試佇列。"
                    )
                    return

                # 步驟 4: 上傳到 NotebookLM（如果啟用）— 先於 Roam 儲存，以便將連結寫入筆記
                notebooklm_result = None
                if self.notebooklm_sync:
                    try:
                        await self._safe_edit_message(processing_message, "⏳ 上傳到 NotebookLM...")
                        notebooklm_result = await self.notebooklm_sync.upload_reel(
                            markdown_content=note_result.markdown_content,
                            video_path=video_path,
                            title=video_title,
                        )
                        if not notebooklm_result.success:
                            logger.warning(f"NotebookLM 上傳失敗: {notebooklm_result.error_message}")
                    except Exception as e:
                        logger.warning(f"NotebookLM 上傳過程發生錯誤: {e}")

                # 步驟 5: 儲存 LLM 生成的 Markdown 筆記（包含 NotebookLM 連結）
                markdown_for_roam = self._inject_nlm_link(
                    note_result.markdown_content, notebooklm_result
                )
                roam_result = await self.roam_sync.save_markdown_note(
                    video_title=video_title,
                    markdown_content=markdown_for_roam,
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
                    instagram_url=instagram_url,
                    notebooklm_result=notebooklm_result,
                )

                await self._safe_edit_message(processing_message, reply_message)

                # 儲存已處理的 URL
                await save_processed_url(
                    url=instagram_url,
                    url_type="instagram_reel",
                    chat_id=chat_id,
                    title=video_title,
                    note_path=None,
                )
                logger.info(f"處理完成: {instagram_url}")

            finally:
                # 清理暫存檔案
                if audio_path:
                    await self.downloader.cleanup(audio_path)
                if video_path:
                    await self.downloader.cleanup(video_path)

        except Exception as e:
            logger.error(f"處理過程發生錯誤: {e}", exc_info=True)
            await self._safe_edit_message(
                processing_message,
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
            await self._safe_edit_message(processing_message, "⏳ 下載貼文中...")
            
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
                await self._safe_edit_message(
                    processing_message,
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
                await self._safe_edit_message(
                    processing_message,
                    f"⏳ 分析圖片中... (共 {len(image_paths)} 張)"
                )
                
                visual_result = await self.visual_analyzer.analyze_images(image_paths)
                
                if not visual_result.success:
                    error_msg = visual_result.error_message or "圖片分析失敗"
                    await self._save_failed_task(
                        instagram_url, chat_id, ErrorType.TRANSCRIBE, error_msg
                    )
                    await self._safe_edit_message(processing_message, f"❌ 處理失敗\n\n{error_msg}")
                    return
                
                visual_description = visual_result.overall_visual_summary
                logger.info(f"圖片分析完成，共 {len(visual_result.frame_descriptions)} 張")
                
                # 步驟 3: 使用 LLM 生成完整 Markdown 筆記
                await self._safe_edit_message(processing_message, "⏳ 生成筆記中...")
                
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
                    await self._safe_edit_message(
                        processing_message,
                        f"❌ 筆記生成失敗\n\n{note_result.error_message}\n\n已排入重試佇列。"
                    )
                    return
                
                # 步驟 4: 上傳到 NotebookLM（如果啟用）— 先於 Roam 儲存，以便將連結寫入筆記
                notebooklm_result = None
                if self.notebooklm_sync:
                    try:
                        await self._safe_edit_message(processing_message, "⏳ 上傳到 NotebookLM...")
                        notebooklm_result = await self.notebooklm_sync.upload_post(
                            markdown_content=note_result.markdown_content,
                            image_paths=image_paths,
                            title=post_title,
                        )
                        if not notebooklm_result.success:
                            logger.warning(f"NotebookLM 上傳失敗: {notebooklm_result.error_message}")
                    except Exception as e:
                        logger.warning(f"NotebookLM 上傳過程發生錯誤: {e}")
                
                # 步驟 5: 儲存 LLM 生成的 Markdown 筆記（包含 NotebookLM 連結 + 原始貼文文字）
                markdown_for_roam = self._inject_nlm_link(
                    note_result.markdown_content, notebooklm_result
                )
                roam_result = await self.roam_sync.save_post_note(
                    post_title=post_title,
                    markdown_content=markdown_for_roam,
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
                    instagram_url=instagram_url,
                    notebooklm_result=notebooklm_result,
                )
                
                await self._safe_edit_message(processing_message, reply_message)
                
                # 儲存已處理的 URL
                await save_processed_url(
                    url=instagram_url,
                    url_type="instagram_post",
                    chat_id=chat_id,
                    title=post_title,
                    note_path=None,
                )
                logger.info(f"貼文處理完成: {instagram_url}")
                
            finally:
                # 清理暫存圖片檔案（圖片已複製到 roam_backup）
                await self.downloader.cleanup_post_images(image_paths)
        
        except Exception as e:
            logger.error(f"處理貼文過程發生錯誤: {e}", exc_info=True)
            await self._safe_edit_message(
                processing_message,
                f"❌ 處理過程發生錯誤\n\n{str(e)}\n\n請稍後再試。"
            )

    async def _handle_threads(
        self,
        threads_url: str,
        chat_id: str,
        processing_message,
    ) -> None:
        """處理 Threads 串文（支援圖片和影片）"""
        media_download_result: ThreadsMediaDownloadResult = None

        try:
            # 步驟 1: 下載 Threads 貼文內容
            logger.info(f"開始處理 Threads: {threads_url}")
            download_result = await self.threads_downloader.download(threads_url)

            if not download_result.success:
                await self._save_failed_task(
                    threads_url, chat_id, ErrorType.DOWNLOAD, download_result.error_message
                )
                await self._safe_edit_message(
                    processing_message,
                    f"❌ 下載失敗\n\n{download_result.error_message}\n\n已排入重試佇列。"
                )
                return

            # 取得作者名稱
            if download_result.content_type == "single_post" and download_result.post:
                author = download_result.post.author_username
            elif download_result.content_type == "thread" and download_result.thread_posts:
                author = download_result.thread_posts[0].author_username
            elif download_result.conversation:
                author = download_result.conversation.parent_post.author_username
            else:
                author = "unknown"

            # 步驟 2: 格式化文字內容
            formatted_content = self.threads_downloader.format_for_summary(download_result)

            if not formatted_content:
                await self._save_failed_task(
                    threads_url, chat_id, ErrorType.DOWNLOAD, "無法取得串文內容"
                )
                await self._safe_edit_message(
                    processing_message,
                    "❌ 無法取得串文內容\n\n已排入重試佇列。"
                )
                return

            # 步驟 3: 下載並分析媒體（如果有）
            visual_description = None
            transcript = None

            all_media = self.threads_downloader.get_all_media(download_result)

            # 記錄下載資訊
            content_log_type_map = {
                "thread_conversation": "threads_conversation",
                "thread": "threads_thread",
                "single_post": "threads",
            }
            content_log_type = content_log_type_map.get(
                download_result.content_type, "threads"
            )
            if all_media:
                await self._safe_edit_message(
                    processing_message,
                    f"⏳ 下載媒體中... ({len(all_media)} 個檔案)"
                )
                media_download_result = await self.threads_downloader.download_media(all_media)

                if media_download_result.success:
                    visual_parts = []

                    # 分析圖片
                    if media_download_result.image_paths:
                        await self._safe_edit_message(
                            processing_message,
                            f"⏳ 分析圖片中... ({len(media_download_result.image_paths)} 張)"
                        )
                        image_result = await self.visual_analyzer.analyze_images(
                            media_download_result.image_paths
                        )
                        if image_result.success and image_result.overall_visual_summary:
                            visual_parts.append("【圖片內容】\n" + image_result.overall_visual_summary)

                    # 分析影片
                    if media_download_result.video_paths:
                        await self._safe_edit_message(
                            processing_message,
                            f"⏳ 分析影片中... ({len(media_download_result.video_paths)} 個)"
                        )
                        for i, video_path in enumerate(media_download_result.video_paths, 1):
                            video_result = await self.visual_analyzer.analyze(video_path)
                            if video_result.success and video_result.overall_visual_summary:
                                visual_parts.append(
                                    f"【影片 {i} 內容】\n" + video_result.overall_visual_summary
                                )

                    # 轉錄音訊（如果有）
                    if media_download_result.audio_paths:
                        await self._safe_edit_message(processing_message, "⏳ 轉錄語音中...")
                        transcripts = []
                        for audio_path in media_download_result.audio_paths:
                            trans_result = await self.transcriber.transcribe(audio_path)
                            if trans_result.success and trans_result.transcript:
                                transcripts.append(trans_result.transcript)
                        if transcripts:
                            transcript = "\n\n".join(transcripts)

                    if visual_parts:
                        visual_description = "\n\n".join(visual_parts)

                    # 記錄 Threads 下載（含媒體大小）
                    self.download_logger.log_threads_download(
                        threads_url=threads_url,
                        title=f"@{author}",
                        image_paths=media_download_result.image_paths,
                        video_paths=media_download_result.video_paths,
                        audio_paths=media_download_result.audio_paths,
                        content_type=content_log_type,
                    )
            else:
                # 純文字 Threads，無媒體
                self.download_logger.log_threads_download(
                    threads_url=threads_url,
                    title=f"@{author}",
                    content_type=content_log_type,
                )

            # 步驟 4: 使用 LLM 生成筆記
            await self._safe_edit_message(processing_message, "⏳ 生成筆記中...")

            note_result = await self.summarizer.generate_threads_note(
                url=threads_url,
                author=author,
                content=formatted_content,
                visual_description=visual_description,
                transcript=transcript,
            )

            if not note_result.success:
                await self._save_failed_task(
                    threads_url, chat_id, ErrorType.SUMMARIZE, note_result.error_message
                )
                await self._safe_edit_message(
                    processing_message,
                    f"❌ 筆記生成失敗\n\n{note_result.error_message}\n\n已排入重試佇列。"
                )
                return

            # 步驟 5: 上傳到 NotebookLM（如果啟用）— 先於 Roam 儲存，以便將連結寫入筆記
            notebooklm_result = None
            if self.notebooklm_sync:
                try:
                    await self._safe_edit_message(processing_message, "⏳ 上傳到 NotebookLM...")
                    # 收集所有媒體路徑
                    media_paths = []
                    if media_download_result:
                        media_paths.extend(media_download_result.image_paths or [])
                        media_paths.extend(media_download_result.video_paths or [])
                    notebooklm_result = await self.notebooklm_sync.upload_threads(
                        markdown_content=note_result.markdown_content,
                        media_paths=media_paths if media_paths else None,
                        title=f"@{author}",
                    )
                    if not notebooklm_result.success:
                        logger.warning(f"NotebookLM 上傳失敗: {notebooklm_result.error_message}")
                except Exception as e:
                    logger.warning(f"NotebookLM 上傳過程發生錯誤: {e}")

            # 步驟 6: 儲存筆記到 Roam（包含 NotebookLM 連結）
            markdown_for_roam = self._inject_nlm_link(
                note_result.markdown_content, notebooklm_result
            )
            roam_result = await self.roam_sync.save_threads_note(
                author=author,
                markdown_content=markdown_for_roam,
                original_url=threads_url,
            )

            if not roam_result.success:
                logger.warning(f"筆記儲存失敗: {roam_result.error_message}")
                await self._save_failed_task(
                    threads_url, chat_id, ErrorType.SYNC, roam_result.error_message
                )

            # 構建回覆訊息
            has_media = bool(all_media)
            thread_count = (
                len(download_result.thread_posts)
                if download_result.content_type == "thread"
                else 0
            )
            reply_message = self._format_threads_reply(
                author=author,
                summary=note_result.summary,
                bullet_points=note_result.bullet_points,
                roam_result=roam_result,
                threads_url=threads_url,
                content_type=download_result.content_type,
                reply_count=len(download_result.conversation.replies) if download_result.conversation else 0,
                has_media=has_media,
                notebooklm_result=notebooklm_result,
                thread_count=thread_count,
            )

            await self._safe_edit_message(processing_message, reply_message)
            
            # 儲存已處理的 URL
            await save_processed_url(
                url=threads_url,
                url_type="threads",
                chat_id=chat_id,
                title=f"@{author}",
                note_path=None,
            )
            logger.info(f"Threads 處理完成: {threads_url}")

        except Exception as e:
            logger.error(f"處理 Threads 過程發生錯誤: {e}", exc_info=True)
            await self._safe_edit_message(
                processing_message,
                f"❌ 處理過程發生錯誤\n\n{str(e)}\n\n請稍後再試。"
            )

        finally:
            # 清理暫存媒體檔案
            if media_download_result:
                self.threads_downloader.cleanup_media(media_download_result)

    def _format_threads_reply(
        self,
        author: str,
        summary: str,
        bullet_points: list,
        roam_result,
        threads_url: str,
        content_type: str = "single_post",
        reply_count: int = 0,
        has_media: bool = False,
        notebooklm_result=None,
        thread_count: int = 0,
    ) -> str:
        """格式化 Threads 回覆訊息"""
        # 重點列表
        bullets_text = "\n".join([f"• {point}" for point in bullet_points])

        # 內容類型說明
        type_info_parts = []
        if content_type == "thread" and thread_count > 1:
            type_info_parts.append(f"串文 {thread_count} 則")
        elif content_type == "thread_conversation" and reply_count > 0:
            type_info_parts.append(f"含 {reply_count} 則回覆")
        if has_media:
            type_info_parts.append("含媒體")
        type_info = f"（{'、'.join(type_info_parts)}）" if type_info_parts else ""

        # Roam 連結部分
        if roam_result and roam_result.success and roam_result.page_url:
            roam_section = f"📎 筆記已儲存\n{roam_result.page_url}"
        else:
            roam_section = "📎 筆記儲存\n⚠️ 儲存失敗，已排入重試佇列"

        # NotebookLM 連結部分
        nlm_section = ""
        if notebooklm_result and notebooklm_result.success and notebooklm_result.notebook_url:
            nlm_section = f"\n🤖 NotebookLM\n{notebooklm_result.notebook_url}\n"

        return f"""✅ Threads 筆記生成完成！{type_info}

👤 作者：@{author}

📝 摘要
{summary}

📌 重點
{bullets_text}

{roam_section}
{nlm_section}
🔗 原始連結
{threads_url}"""

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
        if roam_result and roam_result.success and roam_result.page_url:
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

    @staticmethod
    def _inject_nlm_link(
        markdown_content: str,
        notebooklm_result,
    ) -> str:
        """
        將 NotebookLM 連結注入到 Markdown 內容中

        在「來源資訊」區塊後插入，確保內容儲存到 Roam 時包含 NLM 連結。

        Args:
            markdown_content: 原始 Markdown 內容
            notebooklm_result: NotebookLMResult 物件

        Returns:
            含有 NLM 連結的 Markdown 內容（若上傳失敗則回傳原始內容）
        """
        if (
            not notebooklm_result
            or not notebooklm_result.success
            or not notebooklm_result.notebook_url
        ):
            return markdown_content

        nlm_link = f"\n- 🤖 **NotebookLM**: [{notebooklm_result.notebook_url}]({notebooklm_result.notebook_url})"

        # 嘗試在「來源資訊」區塊後插入
        pattern = r"(## 來源資訊.*?)(\n\n)"
        match = re.search(pattern, markdown_content, re.DOTALL)
        if match:
            insert_pos = match.end(1)
            return markdown_content[:insert_pos] + nlm_link + markdown_content[insert_pos:]

        # 備用：在文件末尾加上
        return markdown_content + f"\n\n## NotebookLM\n\n- 🤖 [{notebooklm_result.notebook_url}]({notebooklm_result.notebook_url})\n"

    def _format_reply_simple(
        self,
        summary: str,
        bullet_points: list,
        roam_result,
        instagram_url: str,
        notebooklm_result=None,
    ) -> str:
        """格式化簡潔版回覆訊息（用於 LLM 生成筆記模式）"""
        # 重點列表
        bullets_text = "\n".join([f"• {point}" for point in bullet_points])

        # Roam 連結部分
        if roam_result and roam_result.success and roam_result.page_url:
            roam_section = f"📎 筆記已儲存\n{roam_result.page_url}"
        elif roam_result is None:
            roam_section = "📎 筆記尚未儲存（等待確認）"
        else:
            roam_section = "📎 筆記儲存\n⚠️ 儲存失敗，已排入重試佇列"

        # NotebookLM 連結部分
        nlm_section = ""
        if notebooklm_result and notebooklm_result.success and notebooklm_result.notebook_url:
            nlm_section = f"\n🤖 NotebookLM\n{notebooklm_result.notebook_url}\n"

        return f"""✅ 筆記生成完成！

📝 摘要
{summary}

📌 重點
{bullets_text}

{roam_section}
{nlm_section}
🔗 原始連結
{instagram_url}"""

    async def _error_handler(
        self, update: object, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """全域錯誤處理器
        
        處理所有未被捕獲的異常，避免 "No error handlers are registered" 警告
        """
        logger.error(f"處理更新時發生未預期錯誤: {context.error}", exc_info=context.error)
        
        # 嘗試通知使用者（如果可能）
        if update and hasattr(update, 'effective_chat') and update.effective_chat:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ 發生未預期的錯誤，請稍後再試。"
                )
            except Exception as e:
                logger.warning(f"無法發送錯誤通知給使用者: {e}")

    async def _send_review_message(
        self, processing_message, reply_message: str, callback_id: str
    ) -> None:
        """發送帶確認/篩除按鈕的筆記預覽訊息"""
        keyboard = [
            [
                InlineKeyboardButton("✅ 儲存筆記", callback_data=f"save:{callback_id}"),
                InlineKeyboardButton("🗑 篩除", callback_data=f"discard:{callback_id}"),
            ]
        ]
        await self._safe_edit_message(processing_message, reply_message)
        # edit_text 不支援 reply_markup，需要用 edit_reply_markup
        try:
            await processing_message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.warning(f"無法新增按鈕: {e}")

    async def handle_callback_query(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """處理 inline keyboard 按鈕回調"""
        query = update.callback_query
        await query.answer()  # 回應按鈕點擊（移除載入動畫）

        data = query.data

        if data == "skip":
            await query.edit_message_text("⏭ 已跳過，不重新處理。")
            return

        if data.startswith("save:"):
            callback_id = data[len("save:"):]
            pending = self._pending_notes.pop(callback_id, None)
            if not pending:
                await query.edit_message_text("⚠️ 筆記已過期或已處理過。")
                return
            await query.edit_message_text("⏳ 正在儲存筆記...")
            try:
                save_func = pending["save_func"]
                roam_result = await save_func()
                # 儲存已處理 URL
                await save_processed_url(
                    url=pending["url"],
                    url_type=pending["url_type"],
                    chat_id=pending["chat_id"],
                    title=pending["title"],
                    note_path=None,
                )
                if roam_result.success:
                    final_text = pending["reply_text"].replace(
                        "📎 筆記尚未儲存（等待確認）",
                        f"📎 筆記已儲存\n{roam_result.page_url or ''}"
                    )
                    await query.edit_message_text(final_text)
                else:
                    final_text = pending["reply_text"].replace(
                        "📎 筆記尚未儲存（等待確認）",
                        "📎 筆記儲存\n⚠️ 儲存失敗，已排入重試佇列"
                    )
                    await query.edit_message_text(final_text)
            except Exception as e:
                logger.error(f"儲存筆記失敗: {e}")
                await query.edit_message_text(f"❌ 儲存失敗: {e}")
            return

        if data.startswith("discard:"):
            callback_id = data[len("discard:"):]
            self._pending_notes.pop(callback_id, None)
            await query.edit_message_text("🗑 已篩除，不儲存筆記。")
            return

        if data.startswith("reprocess:"):
            reprocess_key = data[len("reprocess:"):]
            url = self._reprocess_urls.pop(reprocess_key, None)
            if not url:
                await query.edit_message_text("⚠️ 重新處理請求已過期，請重新傳送連結。")
                return
            chat_id = str(update.effective_chat.id)

            # 先刪除舊的處理紀錄
            deleted = await delete_processed_url(url)
            if deleted:
                logger.info(f"已刪除舊紀錄: {url}")

            # 更新按鈕訊息為處理中
            await query.edit_message_text("⏳ 重新處理中，請稍候...")
            # 用 edit 後的訊息作為 processing_message
            processing_message = query.message

            # 判斷 URL 類型並分發處理
            if self.THREADS_URL_PATTERN.search(url):
                await self._handle_threads(url, chat_id, processing_message)
            elif self._is_reel_url(url):
                await self._handle_reel(url, chat_id, processing_message)
            else:
                await self._handle_post(url, chat_id, processing_message)
            return

    def build_application(self) -> Application:
        """建立並設定 Telegram Application"""
        # 設定更寬裕的網路超時（預設 5 秒太短）
        request = HTTPXRequest(
            connect_timeout=20.0,   # 連線超時（20 秒）
            read_timeout=30.0,      # 讀取超時（30 秒）
            write_timeout=30.0,     # 寫入超時（30 秒）
            pool_timeout=10.0,      # 連線池超時（10 秒）
        )
        
        self.application = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .request(request)
            .build()
        )

        # 註冊指令處理器
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("status", self.status_command))

        # 註冊訊息處理器
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        # 註冊 inline keyboard 回調處理器
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))

        # 註冊全域錯誤處理器
        self.application.add_error_handler(self._error_handler)

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
