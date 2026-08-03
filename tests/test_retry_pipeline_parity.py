"""重試路徑與主 pipeline 對齊（F16）。

漂移的成本是靜默的：retry 每小時都在跑，產出卻缺 vault_sync、缺視覺分析、
/p/ 貼文還走 reel 下載路徑。這裡釘住「兩條路徑共用同一個入口」。
"""
import pytest

from app.bot.process_result import ProcessResult
from app.database.models import ErrorType


REEL_URL = "https://www.instagram.com/reel/DaSd7YuD_x8/"
POST_URL = "https://www.instagram.com/p/DaSd-YuD_x8/"
THREADS_URL = "https://www.threads.com/@dustin_gmat/post/DbHiGmWD10O"


class _Recorder:
    """記錄呼叫並回傳指定結果的 handler 替身。"""

    def __init__(self, result=None):
        self.calls = []
        self.result = result or ProcessResult.ok("done")

    async def __call__(self, url, chat_id, processing_message, retry_mode=False):
        self.calls.append({"url": url, "chat_id": chat_id, "retry_mode": retry_mode})
        return self.result


@pytest.fixture
def handler():
    from app.bot.telegram_handler import TelegramBotHandler

    return TelegramBotHandler()


class TestRouting:
    """路由分流：同一個入口決定 reel / post / threads，兩條路徑共用。"""

    @pytest.mark.asyncio
    async def test_reel_url_goes_to_reel_handler(self, handler, monkeypatch):
        reel, post, threads = _Recorder(), _Recorder(), _Recorder()
        monkeypatch.setattr(handler, "_handle_reel", reel)
        monkeypatch.setattr(handler, "_handle_post", post)
        monkeypatch.setattr(handler, "_handle_threads", threads)

        await handler.process_url(REEL_URL, "42", None)

        assert len(reel.calls) == 1
        assert post.calls == [] and threads.calls == []

    @pytest.mark.asyncio
    async def test_post_url_goes_to_post_handler_not_reel_download(self, handler, monkeypatch):
        """/p/ 貼文必須走 instaloader 貼文路徑——舊 retry 對它呼叫 reel 下載。"""
        reel, post, threads = _Recorder(), _Recorder(), _Recorder()
        monkeypatch.setattr(handler, "_handle_reel", reel)
        monkeypatch.setattr(handler, "_handle_post", post)
        monkeypatch.setattr(handler, "_handle_threads", threads)

        await handler.process_url(POST_URL, "42", None)

        assert len(post.calls) == 1
        assert reel.calls == [] and threads.calls == []

    @pytest.mark.asyncio
    async def test_threads_url_goes_to_threads_handler(self, handler, monkeypatch):
        reel, post, threads = _Recorder(), _Recorder(), _Recorder()
        monkeypatch.setattr(handler, "_handle_reel", reel)
        monkeypatch.setattr(handler, "_handle_post", post)
        monkeypatch.setattr(handler, "_handle_threads", threads)

        await handler.process_url(THREADS_URL, "42", None)

        assert len(threads.calls) == 1
        assert reel.calls == [] and post.calls == []

    @pytest.mark.asyncio
    async def test_retry_mode_is_passed_through(self, handler, monkeypatch):
        reel = _Recorder()
        monkeypatch.setattr(handler, "_handle_reel", reel)

        await handler.process_url(REEL_URL, "42", None, retry_mode=True)

        assert reel.calls[0]["retry_mode"] is True


class TestRetryModeSuppressesDuplicateFailedTasks:
    """重試時 handler 不得再寫一筆 failed_task——否則每小時長一筆 pending。"""

    @pytest.mark.asyncio
    async def test_handler_does_not_record_failure_in_retry_mode(self, handler, monkeypatch):
        saved = []

        async def spy_save(*args, **kwargs):
            saved.append(args)

        async def failing_download(url):
            class _R:
                success = False
                error_message = "boom"
                content_type = None

            return _R()

        monkeypatch.setattr(handler, "_save_failed_task", spy_save)
        monkeypatch.setattr(handler.downloader, "download", failing_download)

        result = await handler._handle_reel(REEL_URL, "42", None, retry_mode=True)

        assert result.success is False
        assert result.error_type == ErrorType.DOWNLOAD
        assert saved == [], "retry 模式不得再寫入 failed_task"

    @pytest.mark.asyncio
    async def test_handler_records_failure_in_normal_mode(self, handler, monkeypatch):
        saved = []

        async def spy_save(*args, **kwargs):
            saved.append(args)

        async def failing_download(url):
            class _R:
                success = False
                error_message = "boom"
                content_type = None

            return _R()

        monkeypatch.setattr(handler, "_save_failed_task", spy_save)
        monkeypatch.setattr(handler.downloader, "download", failing_download)

        await handler._handle_reel(REEL_URL, "42", None)

        assert len(saved) == 1


class TestCodexReviewRegressions:
    """2026-08-03 codex review 抓到的三個委派副作用。"""

    @pytest.mark.asyncio
    async def test_threads_url_is_rejected_when_feature_disabled(self, handler, monkeypatch):
        """P2：停用 Threads 時不得把 threads.com 丟進 IG 貼文下載器空轉重試次數。"""
        from app.config import settings

        post = _Recorder()
        monkeypatch.setattr(handler, "_handle_post", post)
        monkeypatch.setattr(settings, "threads_enabled", False)

        result = await handler.process_url(THREADS_URL, "42", None, retry_mode=True)

        assert result.success is False
        assert post.calls == []

    @pytest.mark.asyncio
    async def test_sync_failure_during_retry_keeps_task_failed(self, handler, monkeypatch):
        """P1：重試時 Roam 同步失敗仍回報失敗，否則任務被標成 success 就再也不同步。"""

        class _Ok:
            success = True
            error_message = None

        class _Fail:
            success = False
            error_message = "roam 掛了"

        async def fake_download(url):
            class _R:
                success = True
                audio_path = None
                video_path = None
                title = "t"
                caption = "有說明文"
                video_size_bytes = 0
                audio_size_bytes = 0

            return _R()

        async def fake_note(**kwargs):
            class _R:
                success = True
                markdown_content = "# note"
                summary = "s"
                bullet_points = ["b"]

            return _R()

        async def fake_save_markdown(**kwargs):
            return _Fail()

        monkeypatch.setattr(handler.downloader, "download", fake_download)
        monkeypatch.setattr(handler.summarizer, "generate_note", fake_note)
        monkeypatch.setattr(handler.roam_sync, "save_markdown_note", fake_save_markdown)
        monkeypatch.setattr(handler, "vault_sync", None)

        result = await handler._handle_reel(REEL_URL, "42", None, retry_mode=True)

        assert result.success is False
        assert result.error_type == ErrorType.SYNC


class TestPostToReelSwitch:
    @pytest.mark.asyncio
    async def test_video_post_switches_to_reel_handler_exactly_once(self, handler, monkeypatch):
        """貼文偵測到是影片時只能轉交一次——重複呼叫等於整條 pipeline 跑兩遍。"""
        reel = _Recorder()

        async def post_says_its_a_reel(url):
            class _R:
                success = False
                content_type = "reel"
                error_message = None

            return _R()

        monkeypatch.setattr(handler, "_handle_reel", reel)
        monkeypatch.setattr(handler.downloader, "download_post", post_says_its_a_reel)

        result = await handler._handle_post(POST_URL, "42", None)

        assert len(reel.calls) == 1
        assert result.success is True


class _FakeTask:
    def __init__(self, url=POST_URL):
        self.instagram_url = url
        self.telegram_chat_id = "42"
        self.error_type = ErrorType.DOWNLOAD.value
        self.error_message = None
        self.retry_count = 0


class TestRetrySchedulerDelegates:
    """重試不再自己走一條 pipeline，而是委派給主 pipeline 入口。"""

    @pytest.fixture
    def scheduler(self):
        from app.scheduler.retry_job import RetryScheduler

        return RetryScheduler()

    @pytest.mark.asyncio
    async def test_delegates_to_process_url_with_retry_mode(self, scheduler):
        calls = []

        class _FakeHandler:
            async def process_url(self, url, chat_id, processing_message, retry_mode=False):
                calls.append((url, chat_id, retry_mode))
                return ProcessResult.ok("✅ 筆記完成")

        scheduler.set_handler(_FakeHandler())
        task = _FakeTask()

        assert await scheduler._retry_full_process(task) is True
        assert calls == [(POST_URL, "42", True)]

    @pytest.mark.asyncio
    async def test_failure_maps_error_type_back_to_task(self, scheduler):
        class _FakeHandler:
            async def process_url(self, url, chat_id, processing_message, retry_mode=False):
                return ProcessResult.fail(ErrorType.SUMMARIZE, "LLM 掛了")

        scheduler.set_handler(_FakeHandler())
        task = _FakeTask()

        assert await scheduler._retry_full_process(task) is False
        assert task.error_type == ErrorType.SUMMARIZE.value
        assert task.error_message == "LLM 掛了"

    @pytest.mark.asyncio
    async def test_without_handler_it_fails_loudly_instead_of_running_a_stale_pipeline(
        self, scheduler
    ):
        """沒注入 handler 就不該偷偷跑舊路徑——那正是漂移的來源。"""
        task = _FakeTask()

        assert await scheduler._retry_full_process(task) is False
        assert task.error_message
