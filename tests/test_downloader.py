"""下載器服務測試"""

import pytest
from app.services.downloader import InstagramDownloader


class TestInstagramDownloader:
    """InstagramDownloader 測試"""

    def setup_method(self):
        """測試前設定"""
        self.downloader = InstagramDownloader()

    def test_validate_url_valid_reel(self):
        """測試有效的 reel 連結"""
        url = "https://www.instagram.com/reel/ABC123xyz"
        assert self.downloader.validate_url(url) is True

    def test_validate_url_valid_p(self):
        """測試有效的 p 連結"""
        url = "https://www.instagram.com/p/ABC123xyz"
        assert self.downloader.validate_url(url) is True

    def test_validate_url_valid_reels(self):
        """測試有效的 reels 連結"""
        url = "https://www.instagram.com/reels/ABC123xyz"
        assert self.downloader.validate_url(url) is True

    def test_validate_url_invalid(self):
        """測試無效的連結"""
        url = "https://www.youtube.com/watch?v=ABC123"
        assert self.downloader.validate_url(url) is False

    def test_validate_url_no_www(self):
        """測試沒有 www 的連結"""
        url = "https://instagram.com/reel/ABC123xyz"
        assert self.downloader.validate_url(url) is True

    def test_extract_post_id(self):
        """測試提取貼文 ID"""
        url = "https://www.instagram.com/reel/ABC123xyz"
        post_id = self.downloader.extract_post_id(url)
        assert post_id == "ABC123xyz"

    def test_extract_post_id_invalid(self):
        """測試從無效連結提取 ID"""
        url = "https://www.youtube.com/watch?v=ABC123"
        post_id = self.downloader.extract_post_id(url)
        assert post_id is None


class TestEnsureFreshCookies:
    """F13：下載前自動刷新 cookies（CDP 供應）"""

    @pytest.mark.asyncio
    async def test_refresh_called_and_cookies_file_rediscovered(self, tmp_path, monkeypatch):
        """刷新後新出現的 cookies.txt 要被撿起來用"""
        from app.services import downloader as dl_module

        monkeypatch.chdir(tmp_path)
        d = InstagramDownloader()
        assert d._cookies_file is None  # 一開始沒有 cookies.txt

        async def fake_refresh():
            (tmp_path / "cookies.txt").write_text("# fresh", encoding="utf-8")
            return True

        monkeypatch.setattr(dl_module.ig_cookie_provider, "refresh_if_stale", fake_refresh)
        await d._ensure_fresh_cookies()
        assert d._cookies_file is not None

    @pytest.mark.asyncio
    async def test_refresh_failure_keeps_existing_cookies_file(self, tmp_path, monkeypatch):
        """CDP 失敗時沿用既有檔案（fallback 行為）"""
        from app.services import downloader as dl_module

        monkeypatch.chdir(tmp_path)
        (tmp_path / "cookies.txt").write_text("# manual", encoding="utf-8")
        d = InstagramDownloader()
        assert d._cookies_file is not None

        async def fake_refresh():
            return False

        monkeypatch.setattr(dl_module.ig_cookie_provider, "refresh_if_stale", fake_refresh)
        await d._ensure_fresh_cookies()
        assert d._cookies_file is not None
