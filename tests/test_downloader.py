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
