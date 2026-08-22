"""FastAPI 主程式入口"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.database.models import init_db
from app.bot.telegram_handler import TelegramBotHandler
from app.scheduler.retry_job import retry_scheduler
from app.services.chrome_lifecycle import close_owned_chrome, reclaim_orphan_chrome
from app.services.ig_cookie_provider import provider as ig_cookie_provider


# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# 全域 Bot Handler
bot_handler = TelegramBotHandler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    # 啟動時執行
    logger.info("正在初始化應用程式...")

    # 初始化資料庫
    await init_db()
    logger.info("資料庫初始化完成")

    # 回收上一輪殘留的 CDP Chrome（F19；服務被強制 kill 時 shutdown 收不到）
    await reclaim_orphan_chrome()

    # 建立 Telegram Bot Application
    telegram_app = bot_handler.build_application()
    await telegram_app.initialize()
    
    # 清除 webhook 中的舊訊息，並重新設定 webhook
    try:
        # 先刪除 webhook 並清除所有 pending updates
        await telegram_app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("已清除 webhook 舊訊息")
        
        # 如果有設定 webhook URL，自動重新設定
        if settings.webhook_url:
            webhook_full_url = f"{settings.webhook_url}/webhook/telegram"
            await telegram_app.bot.set_webhook(url=webhook_full_url)
            logger.info(f"已設定 webhook: {webhook_full_url}")
    except Exception as e:
        logger.warning(f"設定 webhook 失敗: {e}")

    # 設定排程器的 Bot 與主 pipeline 入口（F16：重試走同一條流程，不再自己維護簡化版）
    retry_scheduler.set_bot(telegram_app.bot)
    retry_scheduler.set_handler(bot_handler)

    # F12(b)：IG cookie provider 斷線告警管道——走同一個 Telegram bot，
    # 送給 allowed_chat_ids 全員（provider 是 import 期建立的模組級單例，拿不到 bot，
    # 用同 retry_scheduler 的注入 pattern 補上）
    async def _alert_ig_disconnected(message: str) -> None:
        for chat_id in settings.allowed_chat_ids:
            try:
                await telegram_app.bot.send_message(chat_id=chat_id, text=message)
            except Exception as e:
                logger.warning(f"IG 斷線告警發送失敗（chat_id={chat_id}）: {e}")

    ig_cookie_provider.set_alert_callback(_alert_ig_disconnected)

    # 啟動排程器（如果啟用）
    if settings.retry_enabled:
        retry_scheduler.start()
        logger.info("排程器啟動完成")
    else:
        logger.info("重試排程器已停用 (RETRY_ENABLED=false)")

    logger.info("應用程式初始化完成！")

    yield

    # 關閉時執行
    logger.info("正在關閉應用程式...")
    if settings.retry_enabled:
        retry_scheduler.stop()
    await telegram_app.shutdown()

    # 收掉本服務啟動的 CDP Chrome（F19）——使用者自己開的不會被碰
    await close_owned_chrome()

    logger.info("應用程式已關閉")


# 建立 FastAPI 應用程式
app = FastAPI(
    title="Instagram Reels 摘要系統",
    description="透過 Telegram Bot 自動摘要 Instagram Reels 影片",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    """根路徑健康檢查"""
    return {
        "status": "ok",
        "message": "Instagram Reels 摘要系統運行中",
        "version": "1.0.0",
    }


@app.get("/health")
async def health_check():
    """健康檢查端點"""
    return {"status": "healthy"}


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Telegram Webhook 端點

    接收來自 Telegram 的更新
    先立即回應 Telegram（避免超時），再在背景處理訊息
    """
    try:
        update_data = await request.json()
        logger.debug(f"收到 Telegram 更新: {update_data}")

        # 在背景處理訊息，不等待完成就先回應 Telegram
        asyncio.create_task(process_update_in_background(update_data))

        return JSONResponse(content={"ok": True})

    except Exception as e:
        logger.error(f"處理 Webhook 失敗: {e}")
        # 即使處理失敗也返回 200，避免 Telegram 重試導致循環
        return JSONResponse(content={"ok": True})


async def process_update_in_background(update_data: dict):
    """在背景處理 Telegram 更新"""
    try:
        await bot_handler.process_update(update_data)
    except Exception as e:
        logger.error(f"背景處理更新失敗: {e}")


@app.post("/webhook/setup")
async def setup_webhook(webhook_url: str):
    """
    設定 Telegram Webhook

    Args:
        webhook_url: Webhook URL（需要是 https）
    """
    try:
        full_url = f"{webhook_url}/webhook/telegram"
        await bot_handler.setup_webhook(full_url)
        return {"status": "ok", "webhook_url": full_url}
    except Exception as e:
        logger.error(f"設定 Webhook 失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def get_stats():
    """取得系統統計資訊"""
    from sqlalchemy import select, func
    from app.database.models import FailedTask, TaskStatus, AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        # 待處理任務數
        pending_result = await session.execute(
            select(func.count(FailedTask.id)).where(
                FailedTask.status == TaskStatus.PENDING.value
            )
        )
        pending_count = pending_result.scalar() or 0

        # 成功任務數
        success_result = await session.execute(
            select(func.count(FailedTask.id)).where(
                FailedTask.status == TaskStatus.SUCCESS.value
            )
        )
        success_count = success_result.scalar() or 0

        # 放棄任務數
        abandoned_result = await session.execute(
            select(func.count(FailedTask.id)).where(
                FailedTask.status == TaskStatus.ABANDONED.value
            )
        )
        abandoned_count = abandoned_result.scalar() or 0

    return {
        "pending_tasks": pending_count,
        "success_tasks": success_count,
        "abandoned_tasks": abandoned_count,
        "retry_interval_hours": settings.retry_interval_hours,
        "max_retry_count": settings.max_retry_count,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
