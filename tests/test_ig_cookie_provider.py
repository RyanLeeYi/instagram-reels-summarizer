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
            return [_pw_cookie("sessionid", "s3cr3t"), _pw_cookie("csrftoken", "tok")]

        p = IGCookieProvider(cookies_file=target, fetch_cookies=fake_fetch)
        assert await p.refresh() is True
        text = target.read_text(encoding="utf-8")
        assert "sessionid\ts3cr3t" in text
        assert "csrftoken\ttok" in text

    @pytest.mark.asyncio
    async def test_no_sessionid_keeps_existing_file(self, tmp_path):
        target = tmp_path / "cookies.txt"
        target.write_text("OLD CONTENT", encoding="utf-8")

        async def fake_fetch():
            return [_pw_cookie("mid", "anon-only")]

        p = IGCookieProvider(cookies_file=target, fetch_cookies=fake_fetch)
        assert await p.refresh() is False
        assert target.read_text(encoding="utf-8") == "OLD CONTENT"

    @pytest.mark.asyncio
    async def test_cdp_unavailable_keeps_existing_file(self, tmp_path):
        target = tmp_path / "cookies.txt"
        target.write_text("OLD CONTENT", encoding="utf-8")

        async def fake_fetch():
            return None

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
            return [_pw_cookie("sessionid", "new")]

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
            return [_pw_cookie("sessionid", "fresh-login")]

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
            return [_pw_cookie("sessionid", "renewed")]

        p = IGCookieProvider(cookies_file=target, max_age_seconds=3600, fetch_cookies=fake_fetch)
        assert await p.refresh_if_stale() is True
        assert "sessionid\trenewed" in target.read_text(encoding="utf-8")
