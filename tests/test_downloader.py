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


class TestUserAgentPropagation:
    """F13：instaloader 必須用 cookies 誕生瀏覽器的 UA（否則 IG 判 cross-client 拒絕）"""

    def test_get_instaloader_uses_saved_browser_ua(self, tmp_path, monkeypatch):
        import types

        from app.services import downloader as dl_module

        monkeypatch.chdir(tmp_path)
        (tmp_path / "cookies.txt").write_text("# empty\n", encoding="utf-8")
        (tmp_path / "cookies.txt.ua").write_text("UA-FROM-BROWSER\n", encoding="utf-8")

        captured = {}

        class FakeLoader:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                sess = types.SimpleNamespace(
                    cookies=types.SimpleNamespace(set=lambda *a, **k: None)
                )
                self.context = types.SimpleNamespace(_session=sess)

            def test_login(self):
                return None

            def save_session_to_file(self, path):
                pass

        monkeypatch.setattr(dl_module.instaloader, "Instaloader", FakeLoader)
        d = InstagramDownloader()
        d._get_instaloader()
        assert captured.get("user_agent") == "UA-FROM-BROWSER"

    def test_get_instaloader_sets_context_username_after_cookie_login(self, tmp_path, monkeypatch):
        """cookie 注入登入後必須設 context.username——instaloader 內部以它判斷
        is_logged_in；漏設會導致 Post.from_shortcode 走匿名端點被擋、session 存檔失敗"""
        import types

        from app.services import downloader as dl_module

        monkeypatch.chdir(tmp_path)
        (tmp_path / "cookies.txt").write_text(
            "# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tabc\n",
            encoding="utf-8",
        )

        class FakeLoader:
            def __init__(self, **kwargs):
                sess = types.SimpleNamespace(
                    cookies=types.SimpleNamespace(set=lambda *a, **k: None)
                )
                self.context = types.SimpleNamespace(_session=sess, username=None)

            def test_login(self):
                return "tester"

            def save_session_to_file(self, path):
                pass

        monkeypatch.setattr(dl_module.instaloader, "Instaloader", FakeLoader)
        d = InstagramDownloader()
        loader = d._get_instaloader()
        assert loader.context.username == "tester"


class TestLoginFailureMessageMapping:
    """F12(a)：instaloader 登入態失效時常見丟出 TypeError('NoneType' object is
    not subscriptable)（解析未登入回應的空 JSON 所致），不是具名例外。要映射成
    使用者看得懂、做得到的訊息，不能讓原始字串外洩。"""

    def test_nonetype_not_subscriptable_maps_to_actionable_message(self, tmp_path, monkeypatch):
        from app.services import downloader as dl_module

        monkeypatch.chdir(tmp_path)
        d = InstagramDownloader()

        def boom(context, shortcode):
            raise TypeError("'NoneType' object is not subscriptable")

        monkeypatch.setattr(dl_module.instaloader.Post, "from_shortcode", staticmethod(boom))

        result = d._download_post_sync("ABC123")

        assert result.success is False
        assert "NoneType" not in result.error_message
        assert "not subscriptable" not in result.error_message
        assert result.error_message == dl_module.LOGIN_REQUIRED_MESSAGE

    def test_unrelated_error_keeps_original_message(self, tmp_path, monkeypatch):
        """不是登入態訊號的錯誤不該被誤判、吞掉原始資訊。"""
        from app.services import downloader as dl_module

        monkeypatch.chdir(tmp_path)
        d = InstagramDownloader()

        def boom(context, shortcode):
            raise RuntimeError("disk full while writing image")

        monkeypatch.setattr(dl_module.instaloader.Post, "from_shortcode", staticmethod(boom))

        result = d._download_post_sync("ABC123")

        assert result.success is False
        assert "disk full" in result.error_message

    def test_yt_dlp_login_required_signal_maps_to_actionable_message(self, tmp_path, monkeypatch):
        """Reel 路徑（_download_sync 的 yt-dlp 分支）也要映射同型的登入失效訊號。"""
        import yt_dlp

        from app.services import downloader as dl_module

        monkeypatch.chdir(tmp_path)
        (tmp_path / "cookies.txt").write_text("# manual", encoding="utf-8")
        d = InstagramDownloader()

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=True):
                raise yt_dlp.utils.DownloadError(
                    "ERROR: [Instagram] login_required: You need to log in"
                )

        monkeypatch.setattr(dl_module.yt_dlp, "YoutubeDL", FakeYDL)

        result = d._download_sync(
            "https://www.instagram.com/reel/ABC123xyz",
            {"outtmpl": str(tmp_path / "x")},
            None,
        )

        assert result.success is False
        assert result.error_message == dl_module.LOGIN_REQUIRED_MESSAGE
