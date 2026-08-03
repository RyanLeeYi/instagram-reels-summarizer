"""CDP Chrome 生命週期（F19）——讓沒有任何 Chrome 活得比服務久。

規格：docs/prd/chrome-cdp-lifecycle.md

服務為了 IG cookies 刷新（F13）與 NotebookLM（F7）會自動啟動一個專用 Chrome
（獨立 profile + remote debugging port）。這個模組負責：

- **擁有權**：只有「本服務啟動的」Chrome 才可以被關閉。使用者自己開的一律不碰。
- **持久化**：擁有權寫進 profile 目錄下的狀態檔，跨行程存活——服務被強制 kill 時
  lifespan 不會跑，殘留只能靠下一次啟動回收。
- **收養**：啟動時遇到上一輪的殘留就接管（不重開），使其於本輪結束時一併關閉。

擁有權狀態刻意放模組層級：cookies 刷新每次現場 new 一個 NotebookLMSyncService，
放 instance 屬性等於每次歸零。
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from app.config import settings


logger = logging.getLogger(__name__)

STATE_FILENAME = ".owned-by-reels.json"
# 收尾要快：服務關閉有預算（mission-control 的 grace 為 10 秒，逾時整棵樹被強殺），
# 所以每個 HTTP 呼叫都短逾時、graceful 階段另有硬上限，失敗一律由強殺兜底。
_HTTP_TIMEOUT = 1
_POLL_INTERVAL_SECONDS = 0.25
_GRACEFUL_PHASE_RATIO = 0.6  # 總預算中分給「關閉分頁」的比例，其餘留給輪詢

# 本輪擁有的 Chrome PID；None 代表不擁有任何 Chrome。
_owned_pid: Optional[int] = None


# ==================== 設定解析 ====================


def get_cdp_port() -> int:
    """CDP remote debugging port（來源同 NotebookLM 設定）。"""
    return urlparse(settings.notebooklm_cdp_url).port or 9222


def get_chrome_profile_dir() -> str:
    """CDP Chrome 專用 user-data-dir。"""
    if settings.notebooklm_chrome_profile:
        return settings.notebooklm_chrome_profile
    return os.path.join(os.path.expanduser("~"), ".chrome-cdp-notebooklm")


def state_file_path() -> Path:
    """擁有權狀態檔——放 profile 目錄內，與那個 Chrome 同生共死。"""
    return Path(get_chrome_profile_dir()) / STATE_FILENAME


# ==================== 系統呼叫（薄包裝，測試時替換）====================


def cdp_responding(port: int) -> bool:
    """CDP 端點是否還活著。"""
    try:
        resp = requests.get(f"http://localhost:{port}/json/version", timeout=_HTTP_TIMEOUT)
        return resp.status_code == 200
    except Exception:
        return False


def pid_is_chrome(pid: int) -> bool:
    """PID 還活著且確實是 chrome.exe。

    擋的是「PID 被作業系統回收給別的程序」——沒有這道，殘留狀態檔可能害我們
    強殺一個毫不相干的程序。
    """
    try:
        if sys.platform != "win32":
            os.kill(pid, 0)
            return True
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "chrome.exe" in (out.stdout or "")
    except Exception as e:
        logger.debug(f"檢查 PID {pid} 失敗: {e}")
        return False


def close_all_targets(port: int) -> None:
    """透過 DevTools HTTP 端點關閉所有分頁——最後一個關掉時 Chrome 自己會結束。"""
    resp = requests.get(f"http://localhost:{port}/json/list", timeout=_HTTP_TIMEOUT)
    for target in resp.json():
        target_id = target.get("id")
        if not target_id:
            continue
        try:
            requests.get(f"http://localhost:{port}/json/close/{target_id}", timeout=_HTTP_TIMEOUT)
        except Exception as e:
            logger.debug(f"關閉 target {target_id} 失敗: {e}")


def kill_process_tree(pid: int, timeout: float = 3.0) -> None:
    """強制結束整棵程序樹——只殺 PID 會留下 renderer 子程序。

    Chrome 以獨立 process group / session 啟動，所以非 Windows 平台要對整個
    group 發訊號，不能只殺父 PID。
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=timeout,
        )
    else:
        import signal

        os.killpg(os.getpgid(pid), signal.SIGKILL)


# ==================== 擁有權 ====================


def owned_pid() -> Optional[int]:
    """本輪擁有的 Chrome PID；None 代表不擁有。"""
    return _owned_pid


def mark_owned(pid: int) -> None:
    """登記「這個 Chrome 是我起的」——記憶體旗標 + 狀態檔（供下次啟動回收）。"""
    global _owned_pid
    _owned_pid = pid

    state = {
        "pid": pid,
        "port": get_cdp_port(),
        "profile": get_chrome_profile_dir(),
        "launched_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        path = state_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        # 寫不進去只會失去跨行程回收能力，本輪關閉仍靠記憶體旗標
        logger.warning(f"⚠️ 無法寫入 Chrome 擁有權狀態檔: {e}")


def _delete_state_file() -> None:
    try:
        state_file_path().unlink(missing_ok=True)
    except Exception as e:
        logger.debug(f"刪除擁有權狀態檔失敗: {e}")


def clear_ownership() -> None:
    """放棄擁有權並刪掉狀態檔。"""
    global _owned_pid
    _owned_pid = None
    _delete_state_file()


def _read_state() -> Optional[dict]:
    """讀狀態檔；不存在或毀損都回 None（毀損的順手清掉）。"""
    path = state_file_path()
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or not isinstance(state.get("pid"), int):
            raise ValueError("狀態檔缺少有效的 pid")
        return state
    except Exception as e:
        logger.warning(f"⚠️ Chrome 擁有權狀態檔無法解析（已丟棄）: {e}")
        clear_ownership()
        return None


# ==================== 啟動回收 / 停止關閉 ====================


async def reclaim_orphan_chrome() -> bool:
    """啟動時回收上一輪殘留的 Chrome。回傳是否收養成功。

    判定表（PRD 1c）：只有「狀態檔存在 + port 有回應 + 檔中 PID 仍是活的 chrome」
    才收養。沒有狀態檔卻有人佔著 port，那是使用者自己開的，不碰。
    """
    try:
        state = _read_state()
        if state is None:
            return False

        port = get_cdp_port()
        if state.get("port") != port:
            logger.info("狀態檔記錄的 CDP port 與現行設定不符，視為無效並清除")
            clear_ownership()
            return False

        if not cdp_responding(port):
            logger.info("上一輪的 CDP Chrome 已不在，清除殘留狀態檔")
            clear_ownership()
            return False

        pid = state["pid"]
        if not pid_is_chrome(pid):
            logger.warning(f"⚠️ 狀態檔 PID {pid} 已不是執行中的 Chrome，不予收養（避免誤殺）")
            clear_ownership()
            return False

        global _owned_pid
        _owned_pid = pid
        logger.info(f"♻️ 收養上一輪殘留的 CDP Chrome (PID={pid})，將於本次服務結束時關閉")
        return True

    except Exception as e:
        logger.warning(f"⚠️ 回收殘留 Chrome 時發生錯誤（略過）: {e}")
        return False


async def _wait_until_port_closed(port: int, timeout: float) -> bool:
    """輪詢到 CDP 端點失聯為止。阻塞式 HTTP 丟到 thread，避免卡住 event loop。"""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        if not await asyncio.to_thread(cdp_responding, port):
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def close_owned_chrome(timeout: float = 5.0) -> bool:
    """關閉本服務擁有的 CDP Chrome。不擁有就什麼都不做。

    先 graceful（關掉所有分頁，讓 Chrome 自己把 profile 寫回磁碟——IG session
    的活性靠它），整體逾時才強制殺整棵程序樹。

    `timeout` 是**總預算**：graceful 關分頁與後續輪詢都在裡面。收尾跑太久會被
    mission-control 的 grace（10 秒）攔腰砍掉，反而留下殘局。

    任何失敗只記 WARNING——收尾不該擋住服務關閉。
    """
    global _owned_pid
    pid = _owned_pid
    if pid is None:
        return False

    port = get_cdp_port()
    try:
        logger.info(f"正在關閉本服務啟動的 CDP Chrome (PID={pid}, port={port})...")

        try:
            await asyncio.wait_for(
                asyncio.to_thread(close_all_targets, port),
                timeout=timeout * _GRACEFUL_PHASE_RATIO,
            )
        except asyncio.TimeoutError:
            logger.warning("⚠️ 關閉分頁逾時，改走強制結束")
        except Exception as e:
            logger.warning(f"⚠️ 關閉分頁失敗（改走強制結束）: {e}")

        remaining = timeout * (1 - _GRACEFUL_PHASE_RATIO)
        if await _wait_until_port_closed(port, remaining):
            logger.info("✅ CDP Chrome 已關閉")
        else:
            logger.warning(f"⚠️ CDP Chrome {timeout} 秒內未結束，強制結束程序樹 (PID={pid})")
            # 強殺也綁預算：taskkill 卡住的話，換成服務自己被中台攔腰砍掉
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(kill_process_tree, pid, remaining), timeout=remaining
                )
            except Exception as e:
                logger.warning(f"⚠️ 強制結束失敗: {e}")

        return True

    except Exception as e:
        logger.warning(f"⚠️ 關閉 CDP Chrome 時發生錯誤（略過）: {e}")
        return True

    finally:
        # 本行程不再擁有它；但**狀態檔只在確認關掉之後才刪**——
        # 若收尾中途被強殺而 Chrome 還活著，狀態檔要留給下次啟動回收。
        # （殘檔不會誤導：判定表對「port 已死」的殘檔會自行清除。）
        _owned_pid = None
        if not cdp_responding(port):
            _delete_state_file()
        else:
            logger.warning("⚠️ Chrome 仍在執行，保留狀態檔供下次啟動回收")
