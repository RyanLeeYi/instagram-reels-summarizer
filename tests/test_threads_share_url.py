"""Threads /share/ 短連結支援測試（F17）

驗證分享/複製連結產生的 threads.com/share/<code> 格式能被辨識並正規化。
"""

import asyncio
from unittest.mock import patch, MagicMock

import pytest
import requests

from app.services.threads_downloader import ThreadsDownloader


SHARE_URL = "https://www.threads.com/share/BAUrkxxv3Q/"
CANONICAL_URL = "https://www.threads.com/@dustin_gmat/post/DbHiGmWD10O"
CANONICAL_URL_WITH_QUERY = CANONICAL_URL + "?xmt=AQG07wRj&slof=1"


class TestThreadsShareUrl:
    def setup_method(self):
        self.downloader = ThreadsDownloader()

    # ---- validate_url ----
    def test_validate_url_accepts_share(self):
        assert self.downloader.validate_url(SHARE_URL) is True

    def test_validate_url_accepts_share_net_domain(self):
        assert self.downloader.validate_url(
            "https://www.threads.net/share/BAUrkxxv3Q/"
        ) is True

    def test_validate_url_accepts_share_no_www(self):
        assert self.downloader.validate_url(
            "https://threads.com/share/BAUrkxxv3Q"
        ) is True

    # ---- is_share_url ----
    def test_is_share_url_true(self):
        assert self.downloader.is_share_url(SHARE_URL) is True

    def test_is_share_url_false_for_canonical(self):
        assert self.downloader.is_share_url(CANONICAL_URL) is False

    # ---- 轉址解析 ----
    def test_resolve_share_url_follows_redirect(self):
        mock_resp = MagicMock()
        mock_resp.url = CANONICAL_URL_WITH_QUERY
        with patch(
            "app.services.threads_downloader.requests.get", return_value=mock_resp
        ) as mock_get:
            resolved = self.downloader._resolve_share_url(SHARE_URL)
        # query 參數被去除，取得乾淨的正規貼文 URL
        assert resolved == CANONICAL_URL
        # 確實有跟隨轉址
        _, kwargs = mock_get.call_args
        assert kwargs.get("allow_redirects") is True

    def test_resolve_share_url_fallback_on_error(self):
        with patch(
            "app.services.threads_downloader.requests.get",
            side_effect=requests.RequestException("boom"),
        ):
            resolved = self.downloader._resolve_share_url(SHARE_URL)
        # 轉址失敗時降級回原 url，不 crash
        assert resolved == SHARE_URL

    # ---- download() 對 share 連結先正規化再解析 ----
    def test_download_resolves_share_then_extracts_post_id(self):
        captured = {}

        def fake_download_sync(post_id, url):
            captured["post_id"] = post_id
            captured["url"] = url
            from app.services.threads_downloader import ThreadsDownloadResult
            return ThreadsDownloadResult(success=True)

        with patch.object(
            self.downloader, "_resolve_share_url", return_value=CANONICAL_URL
        ), patch.object(
            self.downloader, "_download_sync", side_effect=fake_download_sync
        ):
            result = asyncio.run(self.downloader.download(SHARE_URL))

        assert result.success is True
        # 解析出的是正規貼文碼，而非 share code
        assert captured["post_id"] == "DbHiGmWD10O"
        assert captured["url"] == CANONICAL_URL


class TestHandlerSharePattern:
    def test_handler_pattern_matches_share(self):
        from app.bot.telegram_handler import TelegramBotHandler

        assert TelegramBotHandler.THREADS_URL_PATTERN.search(SHARE_URL)

    def test_handler_pattern_still_matches_canonical(self):
        from app.bot.telegram_handler import TelegramBotHandler

        assert TelegramBotHandler.THREADS_URL_PATTERN.search(CANONICAL_URL)
