"""CDP Chrome 生命週期（F19）：擁有權、停止時關閉、啟動時收養殘留。

規格：docs/prd/chrome-cdp-lifecycle.md
全程 mock，不真的開關 Chrome。
"""
import asyncio
import json

import pytest

from app.services import chrome_lifecycle as cl


@pytest.fixture
def env(tmp_path, monkeypatch):
    """把 profile 目錄導到 tmp、固定 port，並確保每個測試從無擁有權開始。"""
    monkeypatch.setattr(cl, "get_chrome_profile_dir", lambda: str(tmp_path))
    monkeypatch.setattr(cl, "get_cdp_port", lambda: 9222)
    cl.clear_ownership()
    yield tmp_path
    cl.clear_ownership()


def _write_state(tmp_path, pid=4321, port=9222):
    (tmp_path / cl.STATE_FILENAME).write_text(
        json.dumps({"pid": pid, "port": port, "profile": str(tmp_path), "launched_at": "2026-08-03T10:00:00"}),
        encoding="utf-8",
    )


class _Spy:
    """記錄呼叫次數與參數的極簡替身。"""

    def __init__(self, result=None):
        self.calls = []
        self.kwargs = []
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        self.kwargs.append(kwargs)
        return self.result


class TestMarkOwned:
    def test_writes_state_file_and_sets_ownership(self, env):
        cl.mark_owned(1234)

        assert cl.owned_pid() == 1234
        state = json.loads((env / cl.STATE_FILENAME).read_text(encoding="utf-8"))
        assert state["pid"] == 1234
        assert state["port"] == 9222
        assert state["profile"] == str(env)
        assert state["launched_at"]

    def test_ownership_is_module_level_not_per_instance(self, env, monkeypatch):
        """cookie 刷新每次 new 一個 NotebookLMSyncService，擁有權不能跟著歸零。"""
        from app.services.notebooklm_sync import NotebookLMSyncService

        cl.mark_owned(1234)
        NotebookLMSyncService()
        NotebookLMSyncService()

        assert cl.owned_pid() == 1234


class TestCloseOwnedChrome:
    @pytest.mark.asyncio
    async def test_does_nothing_when_not_owned(self, env, monkeypatch):
        close_targets, kill = _Spy(), _Spy()
        monkeypatch.setattr(cl, "close_all_targets", close_targets)
        monkeypatch.setattr(cl, "kill_process_tree", kill)

        assert await cl.close_owned_chrome() is False
        assert close_targets.calls == []
        assert kill.calls == []

    @pytest.mark.asyncio
    async def test_graceful_close_does_not_force_kill(self, env, monkeypatch):
        close_targets, kill = _Spy(), _Spy()
        monkeypatch.setattr(cl, "close_all_targets", close_targets)
        monkeypatch.setattr(cl, "kill_process_tree", kill)
        monkeypatch.setattr(cl, "cdp_responding", lambda port: False)  # 關完就沒回應
        cl.mark_owned(1234)

        assert await cl.close_owned_chrome() is True
        assert close_targets.calls == [(9222,)]
        assert kill.calls == []
        assert cl.owned_pid() is None
        assert not (env / cl.STATE_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_force_kills_when_port_still_alive_after_timeout(self, env, monkeypatch):
        close_targets, kill = _Spy(), _Spy()
        monkeypatch.setattr(cl, "close_all_targets", close_targets)
        monkeypatch.setattr(cl, "kill_process_tree", kill)
        monkeypatch.setattr(cl, "cdp_responding", lambda port: True)  # 賴著不走
        cl.mark_owned(1234)

        assert await cl.close_owned_chrome(timeout=0.2) is True
        assert kill.calls[0][0] == 1234
        assert cl.owned_pid() is None

    @pytest.mark.asyncio
    async def test_exception_is_swallowed_and_ownership_cleared(self, env, monkeypatch):
        def boom(port):
            raise OSError("CDP 端點炸了")

        monkeypatch.setattr(cl, "close_all_targets", boom)
        monkeypatch.setattr(cl, "kill_process_tree", _Spy())
        monkeypatch.setattr(cl, "cdp_responding", lambda port: False)  # 例外後 Chrome 確實沒了
        cl.mark_owned(1234)

        await cl.close_owned_chrome(timeout=0.2)  # 不得拋錯

        assert cl.owned_pid() is None
        assert not (env / cl.STATE_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_state_file_survives_when_chrome_does(self, env, monkeypatch):
        """關不掉時狀態檔必須留著——這是異常結束後唯一的回收線索。

        反例（2026-08-03 codex review P1）：若在關閉前就刪檔，收尾中途被中台強殺
        會留下「Chrome 活著但沒有狀態檔」的局面，下次啟動把它當使用者手開的，
        永遠收不回來。反過來留下的殘檔是自癒的——判定表對 port 已死的殘檔會清掉。
        """
        monkeypatch.setattr(cl, "close_all_targets", _Spy())
        monkeypatch.setattr(cl, "kill_process_tree", _Spy())
        monkeypatch.setattr(cl, "cdp_responding", lambda port: True)  # 殺不死
        cl.mark_owned(1234)

        await cl.close_owned_chrome(timeout=0.2)

        assert (env / cl.STATE_FILENAME).exists()
        assert cl.owned_pid() is None  # 本行程仍要放手

    @pytest.mark.asyncio
    async def test_total_time_stays_within_budget(self, env, monkeypatch):
        """graceful 卡住時不能拖過預算——超過 grace 就換服務自己被強殺。"""
        import time

        def slow_close(port):
            time.sleep(10)  # 模擬 Chrome 拆解時 HTTP 逐一逾時

        kill = _Spy()
        monkeypatch.setattr(cl, "close_all_targets", slow_close)
        monkeypatch.setattr(cl, "kill_process_tree", kill)
        monkeypatch.setattr(cl, "cdp_responding", lambda port: True)
        cl.mark_owned(1234)

        started = asyncio.get_event_loop().time()
        await cl.close_owned_chrome(timeout=2)
        elapsed = asyncio.get_event_loop().time() - started

        assert elapsed < 3, f"收尾耗時 {elapsed:.1f}s，超出預算"
        assert kill.calls[0][0] == 1234

    @pytest.mark.asyncio
    async def test_second_call_is_noop(self, env, monkeypatch):
        kill = _Spy()
        monkeypatch.setattr(cl, "close_all_targets", _Spy())
        monkeypatch.setattr(cl, "kill_process_tree", kill)
        monkeypatch.setattr(cl, "cdp_responding", lambda port: True)
        cl.mark_owned(1234)

        await cl.close_owned_chrome(timeout=0.1)
        await cl.close_owned_chrome(timeout=0.1)

        assert len(kill.calls) == 1  # 第二次沒有擁有權，不會再殺一輪


class TestReclaimOrphanChrome:
    """啟動時的回收判定表（PRD 1c）。"""

    @pytest.mark.asyncio
    async def test_no_state_file_means_chrome_belongs_to_user(self, env, monkeypatch):
        """沒有狀態檔但 port 有回應＝Ryan 自己開的，絕不能碰。"""
        monkeypatch.setattr(cl, "cdp_responding", lambda port: True)
        monkeypatch.setattr(cl, "pid_is_chrome", lambda pid: True)

        assert await cl.reclaim_orphan_chrome() is False
        assert cl.owned_pid() is None

    @pytest.mark.asyncio
    async def test_adopts_live_orphan_from_previous_run(self, env, monkeypatch):
        monkeypatch.setattr(cl, "cdp_responding", lambda port: True)
        monkeypatch.setattr(cl, "pid_is_chrome", lambda pid: pid == 4321)
        _write_state(env, pid=4321)

        assert await cl.reclaim_orphan_chrome() is True
        assert cl.owned_pid() == 4321
        assert (env / cl.STATE_FILENAME).exists()  # 收養＝續用，狀態檔留著

    @pytest.mark.asyncio
    async def test_stale_pid_is_not_adopted(self, env, monkeypatch):
        """PID 已死或被回收成別的程序 → 不可信，不擁有也不殺。"""
        monkeypatch.setattr(cl, "cdp_responding", lambda port: True)
        monkeypatch.setattr(cl, "pid_is_chrome", lambda pid: False)
        _write_state(env, pid=4321)

        assert await cl.reclaim_orphan_chrome() is False
        assert cl.owned_pid() is None
        assert not (env / cl.STATE_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_dead_port_clears_stale_state_file(self, env, monkeypatch):
        monkeypatch.setattr(cl, "cdp_responding", lambda port: False)
        monkeypatch.setattr(cl, "pid_is_chrome", lambda pid: True)
        _write_state(env, pid=4321)

        assert await cl.reclaim_orphan_chrome() is False
        assert cl.owned_pid() is None
        assert not (env / cl.STATE_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_corrupt_state_file_is_discarded_without_raising(self, env, monkeypatch):
        monkeypatch.setattr(cl, "cdp_responding", lambda port: True)
        monkeypatch.setattr(cl, "pid_is_chrome", lambda pid: True)
        (env / cl.STATE_FILENAME).write_text("{not json", encoding="utf-8")

        assert await cl.reclaim_orphan_chrome() is False
        assert cl.owned_pid() is None
        assert not (env / cl.STATE_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_port_mismatch_is_not_adopted(self, env, monkeypatch):
        """狀態檔記的是別的 port → 端點上那個不是我們那台。"""
        monkeypatch.setattr(cl, "cdp_responding", lambda port: True)
        monkeypatch.setattr(cl, "pid_is_chrome", lambda pid: True)
        _write_state(env, pid=4321, port=9333)

        assert await cl.reclaim_orphan_chrome() is False
        assert cl.owned_pid() is None


class TestSystemWrappers:
    def test_kill_process_tree_kills_children_too(self, monkeypatch):
        run = _Spy()
        monkeypatch.setattr(cl.subprocess, "run", run)
        monkeypatch.setattr(cl.sys, "platform", "win32")

        cl.kill_process_tree(1234)

        argv = run.calls[0][0]
        assert argv[0] == "taskkill"
        assert "/PID" in argv and "1234" in argv
        assert "/T" in argv  # 少了它 renderer 子程序會留下
        assert "/F" in argv

    def test_cdp_responding_is_false_when_endpoint_unreachable(self, monkeypatch):
        def boom(url, timeout):
            raise OSError("connection refused")

        monkeypatch.setattr(cl.requests, "get", boom)

        assert cl.cdp_responding(9222) is False

    def test_close_all_targets_closes_every_target(self, monkeypatch):
        requested = []

        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return [{"id": "AAA"}, {"id": "BBB"}]

        def fake_get(url, timeout):
            requested.append(url)
            return _Resp()

        monkeypatch.setattr(cl.requests, "get", fake_get)

        cl.close_all_targets(9222)

        assert requested[0].endswith("/json/list")
        assert any(u.endswith("/json/close/AAA") for u in requested)
        assert any(u.endswith("/json/close/BBB") for u in requested)


class TestLaunchWiring:
    """_start_chrome_cdp 成功時必須登記擁有權，否則收尾拿不到 PID。"""

    def test_start_chrome_cdp_marks_ownership(self, env, monkeypatch):
        from app.services.notebooklm_sync import NotebookLMSyncService

        class _Proc:
            pid = 5555

        monkeypatch.setattr(NotebookLMSyncService, "_find_chrome_executable", staticmethod(lambda: "chrome.exe"))
        monkeypatch.setattr(cl.subprocess, "Popen", lambda *a, **kw: _Proc())
        import app.services.notebooklm_sync as nl

        monkeypatch.setattr(nl.subprocess, "Popen", lambda *a, **kw: _Proc())

        svc = NotebookLMSyncService()
        assert svc._start_chrome_cdp() is True
        assert cl.owned_pid() == 5555
