"""F15：NotebookLMSyncService._launch_browser 的降級 timeout 與 auto_start 開關。

真正的 180s 空等來自 playwright.chromium.connect_over_cdp 的預設 timeout；
ig_cookie_provider 這條路徑不該自動拉起 Chrome，也不能沿用那個預設值。
"""
import types

import pytest


class TestAutoStartFalseSkipsChromeBootstrap:
    @pytest.mark.asyncio
    async def test_auto_start_false_returns_fast_without_launching_chrome(self, monkeypatch):
        from app.services.notebooklm_sync import NotebookLMSyncService

        svc = NotebookLMSyncService()
        monkeypatch.setattr(svc, "_is_cdp_running", lambda: False)

        called = {"start": False, "wait": False}

        def fake_start():
            called["start"] = True
            return True

        async def fake_wait(timeout=15):
            called["wait"] = True
            return True

        monkeypatch.setattr(svc, "_start_chrome_cdp", fake_start)
        monkeypatch.setattr(svc, "_wait_for_cdp_ready", fake_wait)

        result = await svc._launch_browser(auto_start=False)

        assert result is False
        assert called["start"] is False, "auto_start=False 不該嘗試拉起 Chrome"
        assert called["wait"] is False, "auto_start=False 不該進入 15s 就緒等待"

    @pytest.mark.asyncio
    async def test_auto_start_default_true_preserves_existing_bootstrap_behavior(self, monkeypatch):
        """既有呼叫者（NotebookLM 主動同步）不傳 auto_start 時，行為不變：CDP 沒開仍會嘗試拉起。"""
        from app.services.notebooklm_sync import NotebookLMSyncService

        svc = NotebookLMSyncService()
        monkeypatch.setattr(svc, "_is_cdp_running", lambda: False)

        called = {"start": False}

        def fake_start():
            called["start"] = True
            return False  # 找不到 Chrome，快速失敗，不必真的等待 15s

        monkeypatch.setattr(svc, "_start_chrome_cdp", fake_start)

        result = await svc._launch_browser()

        assert result is False
        assert called["start"] is True, "預設行為必須維持自動拉起 Chrome"


class TestConnectTimeoutForwarding:
    @pytest.mark.asyncio
    async def test_connect_timeout_ms_forwarded_when_cdp_already_running(self, monkeypatch):
        from app.services.notebooklm_sync import NotebookLMSyncService

        svc = NotebookLMSyncService()
        monkeypatch.setattr(svc, "_is_cdp_running", lambda: True)

        captured = {}

        class FakeBrowser:
            contexts = []

            async def new_context(self):
                return object()

        class FakeChromium:
            @staticmethod
            async def connect_over_cdp(url, **kwargs):
                captured["url"] = url
                captured["kwargs"] = kwargs
                return FakeBrowser()

        svc._playwright = types.SimpleNamespace(chromium=FakeChromium())

        result = await svc._launch_browser(auto_start=False, connect_timeout_ms=8000)

        assert result is True
        assert captured["kwargs"].get("timeout") == 8000

    @pytest.mark.asyncio
    async def test_default_call_does_not_force_a_timeout_kwarg(self, monkeypatch):
        """既有呼叫者不傳 connect_timeout_ms 時，不主動帶 timeout kwarg，
        維持 Playwright 原本預設行為（避免我們的改動反過來影響到需要真的等待的呼叫者）。"""
        from app.services.notebooklm_sync import NotebookLMSyncService

        svc = NotebookLMSyncService()
        monkeypatch.setattr(svc, "_is_cdp_running", lambda: True)

        captured = {}

        class FakeBrowser:
            contexts = []

            async def new_context(self):
                return object()

        class FakeChromium:
            @staticmethod
            async def connect_over_cdp(url, **kwargs):
                captured["kwargs"] = kwargs
                return FakeBrowser()

        svc._playwright = types.SimpleNamespace(chromium=FakeChromium())

        result = await svc._launch_browser()

        assert result is True
        assert "timeout" not in captured["kwargs"]
