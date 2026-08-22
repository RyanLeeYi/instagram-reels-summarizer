"""IG cookies 自動供應（F13）：CDP 抽 cookies → Netscape 檔的轉換與刷新邏輯。"""
import time

import pytest

from app.services.ig_cookie_provider import IGCookieProvider


def _pw_cookie(name, value, domain=".instagram.com", expires=None, secure=True):
    """Playwright context.cookies() 回傳格式的最小樣本。"""
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": "/",
        "expires": expires if expires is not None else time.time() + 86400,
        "httpOnly": True,
        "secure": secure,
        "sameSite": "Lax",
    }


class TestToNetscape:
    def test_formats_header_and_tab_separated_fields(self):
        out = IGCookieProvider.to_netscape([_pw_cookie("sessionid", "abc123", expires=1800000000)])
        lines = out.splitlines()
        assert lines[0].startswith("# Netscape HTTP Cookie File")
        fields = lines[-1].split("\t")
        assert fields == [".instagram.com", "TRUE", "/", "TRUE", "1800000000", "sessionid", "abc123"]

    def test_leading_dot_domain_means_include_subdomains(self):
        out = IGCookieProvider.to_netscape([_pw_cookie("mid", "x", domain="www.instagram.com")])
        fields = out.splitlines()[-1].split("\t")
        assert fields[0] == "www.instagram.com"
        assert fields[1] == "FALSE"

    def test_session_cookie_expires_minus_one_becomes_zero(self):
        out = IGCookieProvider.to_netscape([_pw_cookie("rur", "y", expires=-1)])
        assert out.splitlines()[-1].split("\t")[4] == "0"


class TestRefresh:
    @pytest.mark.asyncio
    async def test_writes_file_when_sessionid_present(self, tmp_path):
        target = tmp_path / "cookies.txt"

        async def fake_fetch():
            return [_pw_cookie("sessionid", "s3cr3t"), _pw_cookie("csrftoken", "tok")], None

        p = IGCookieProvider(cookies_file=target, fetch_cookies=fake_fetch)
        assert await p.refresh() is True
        text = target.read_text(encoding="utf-8")
        assert "sessionid\ts3cr3t" in text
        assert "csrftoken\ttok" in text

    @pytest.mark.asyncio
    async def test_writes_user_agent_sidecar(self, tmp_path):
        """session 綁 client 指紋：cookies 誕生的瀏覽器 UA 要一起存，
        instaloader/yt-dlp 用同一個 UA 才不會被 IG 判 cross-client 拒絕。"""
        target = tmp_path / "cookies.txt"
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/150.0.0.0"

        async def fake_fetch():
            return [_pw_cookie("sessionid", "s")], ua

        p = IGCookieProvider(cookies_file=target, fetch_cookies=fake_fetch)
        assert await p.refresh() is True
        assert p.user_agent_file.read_text(encoding="utf-8").strip() == ua
        assert p.read_user_agent() == ua

    @pytest.mark.asyncio
    async def test_read_user_agent_returns_none_when_missing(self, tmp_path):
        p = IGCookieProvider(cookies_file=tmp_path / "cookies.txt")
        assert p.read_user_agent() is None

    @pytest.mark.asyncio
    async def test_no_sessionid_keeps_existing_file(self, tmp_path):
        target = tmp_path / "cookies.txt"
        target.write_text("OLD CONTENT", encoding="utf-8")

        async def fake_fetch():
            return [_pw_cookie("mid", "anon-only")], None

        p = IGCookieProvider(cookies_file=target, fetch_cookies=fake_fetch)
        assert await p.refresh() is False
        assert target.read_text(encoding="utf-8") == "OLD CONTENT"

    @pytest.mark.asyncio
    async def test_cdp_unavailable_keeps_existing_file(self, tmp_path):
        target = tmp_path / "cookies.txt"
        target.write_text("OLD CONTENT", encoding="utf-8")

        async def fake_fetch():
            return None, None

        p = IGCookieProvider(cookies_file=target, fetch_cookies=fake_fetch)
        assert await p.refresh() is False
        assert target.read_text(encoding="utf-8") == "OLD CONTENT"


class TestRefreshIfStale:
    @pytest.mark.asyncio
    async def test_fresh_file_with_sessionid_skips_fetch(self, tmp_path):
        target = tmp_path / "cookies.txt"
        target.write_text(
            "# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t1800000000\tsessionid\tabc\n",
            encoding="utf-8",
        )
        called = False

        async def fake_fetch():
            nonlocal called
            called = True
            return [_pw_cookie("sessionid", "new")], None

        p = IGCookieProvider(cookies_file=target, max_age_seconds=3600, fetch_cookies=fake_fetch)
        assert await p.refresh_if_stale() is True
        assert called is False

    @pytest.mark.asyncio
    async def test_file_without_sessionid_triggers_refresh_even_if_fresh(self, tmp_path):
        target = tmp_path / "cookies.txt"
        target.write_text(
            "# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t1800000000\tmid\tanon\n",
            encoding="utf-8",
        )

        async def fake_fetch():
            return [_pw_cookie("sessionid", "fresh-login")], None

        p = IGCookieProvider(cookies_file=target, max_age_seconds=3600, fetch_cookies=fake_fetch)
        assert await p.refresh_if_stale() is True
        assert "sessionid\tfresh-login" in target.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_stale_file_triggers_refresh(self, tmp_path, monkeypatch):
        import os

        target = tmp_path / "cookies.txt"
        target.write_text(
            "# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t1800000000\tsessionid\told\n",
            encoding="utf-8",
        )
        old = time.time() - 7200
        os.utime(target, (old, old))

        async def fake_fetch():
            return [_pw_cookie("sessionid", "renewed")], None

        p = IGCookieProvider(cookies_file=target, max_age_seconds=3600, fetch_cookies=fake_fetch)
        assert await p.refresh_if_stale() is True
        assert "sessionid\trenewed" in target.read_text(encoding="utf-8")


class TestFastDegradeWhenCdpUnavailable:
    """F15：CDP 不可用時，cookies 刷新這條路徑要在 ≤10s 內降級，
    不能沿用 playwright connect_over_cdp 的 180s 預設 timeout，也不該自動拉起 Chrome
   （那是 notebooklm_sync 自己主動同步時才該做的事）。"""

    @pytest.mark.asyncio
    async def test_cdp_not_running_degrades_fast_and_keeps_file(self, tmp_path, monkeypatch):
        import time

        from app.services import notebooklm_sync as nb_module

        target = tmp_path / "cookies.txt"
        target.write_text("OLD CONTENT", encoding="utf-8")

        captured = {}

        class FakeSvc:
            def _is_cdp_running(self):
                return False

            async def _launch_browser(self, auto_start=True, connect_timeout_ms=None):
                captured["auto_start"] = auto_start
                captured["connect_timeout_ms"] = connect_timeout_ms
                return False

            async def _close_browser(self):
                pass

        monkeypatch.setattr(nb_module, "NotebookLMSyncService", FakeSvc)

        p = IGCookieProvider(cookies_file=target)
        start = time.monotonic()
        result = await p.refresh()
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed <= 10, f"降級耗時 {elapsed:.2f}s 超過 10s 預算"
        assert target.read_text(encoding="utf-8") == "OLD CONTENT"
        # 這兩個斷言是本測試改動前會紅的核心：舊版 _fetch_from_cdp 呼叫
        # svc._launch_browser() 不帶任何參數，會自動拉起 Chrome 並可能沿用
        # playwright 預設 180s timeout
        assert captured.get("auto_start") is False, "cookies 刷新路徑不該自動拉起 Chrome"
        assert captured.get("connect_timeout_ms") is not None, "connect 必須帶有界 timeout"
        assert captured["connect_timeout_ms"] <= 10000


class TestDisconnectAlert:
    """F12(b)(c)：CDP 未登入且 cookies.txt 無 session 才是真斷線——
    同一段斷線期間只告警一次（去重），登入態恢復後重新武裝。"""

    @pytest.mark.asyncio
    async def test_alert_fires_once_when_truly_disconnected(self, tmp_path):
        target = tmp_path / "cookies.txt"
        target.write_text("NO SESSION HERE", encoding="utf-8")

        alerts = []

        async def fake_alert(message):
            alerts.append(message)

        async def fake_fetch():
            return [_pw_cookie("mid", "anon-only")], None

        p = IGCookieProvider(cookies_file=target, fetch_cookies=fake_fetch)
        p.set_alert_callback(fake_alert)

        assert await p.refresh() is False
        assert await p.refresh() is False
        assert await p.refresh() is False

        assert len(alerts) == 1

    @pytest.mark.asyncio
    async def test_no_alert_when_cookies_file_still_has_valid_session(self, tmp_path):
        """只有 CDP 沒登入，但 cookies.txt 還留著有效 session 時不該吵人。"""
        target = tmp_path / "cookies.txt"
        target.write_text(
            "# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t1800000000\tsessionid\tstill-valid\n",
            encoding="utf-8",
        )

        alerts = []

        async def fake_alert(message):
            alerts.append(message)

        async def fake_fetch():
            return [_pw_cookie("mid", "anon-only")], None

        p = IGCookieProvider(cookies_file=target, fetch_cookies=fake_fetch)
        p.set_alert_callback(fake_alert)

        assert await p.refresh() is False
        assert alerts == []

    @pytest.mark.asyncio
    async def test_alert_rearms_after_recovery(self, tmp_path):
        """去重期間 cookies.txt 仍留有舊 sessionid 時不重送（見上一條測試）；
        本測試模擬「恢復後 cookies.txt 的 session 也一併失效」的真斷線，
        驗證重新武裝後會再送一次告警。"""
        target = tmp_path / "cookies.txt"
        target.write_text("NO SESSION HERE", encoding="utf-8")

        alerts = []

        async def fake_alert(message):
            alerts.append(message)

        async def fake_fetch_disconnected():
            return [_pw_cookie("mid", "anon-only")], None

        async def fake_fetch_recovered():
            return [_pw_cookie("sessionid", "recovered")], None

        p = IGCookieProvider(cookies_file=target, fetch_cookies=fake_fetch_disconnected)
        p.set_alert_callback(fake_alert)

        assert await p.refresh() is False  # 斷線，送第一次告警
        assert await p.refresh() is False  # 仍斷線，去重不再送
        assert len(alerts) == 1

        p._fetch_cookies = fake_fetch_recovered
        assert await p.refresh() is True  # 恢復登入，重新武裝，cookies.txt 寫回 sessionid

        # 之後 session 整個失效，連本地檔案的 sessionid 也一併作廢
        target.write_text("NO SESSION HERE AGAIN", encoding="utf-8")
        p._fetch_cookies = fake_fetch_disconnected
        assert await p.refresh() is False  # 再次真斷線，應該再送一次
        assert len(alerts) == 2

    @pytest.mark.asyncio
    async def test_no_alert_callback_configured_does_not_raise(self, tmp_path):
        """沒注入 alert callback（例如尚未接上 lifespan）時只寫 log，不能炸掉 refresh()。"""
        target = tmp_path / "cookies.txt"
        target.write_text("NO SESSION HERE", encoding="utf-8")

        async def fake_fetch():
            return [_pw_cookie("mid", "anon-only")], None

        p = IGCookieProvider(cookies_file=target, fetch_cookies=fake_fetch)
        assert await p.refresh() is False
