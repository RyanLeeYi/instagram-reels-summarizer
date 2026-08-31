"""F20：init.ps1 在 pip 安裝失敗時必須非零結束、不得印 init OK，且要指名失敗的套件。

兩個刻意的設計：

1. **真的跑一次 init.ps1**，不做 structure assertion——原本的 bug 就是「腳本讀起來沒問題但
   行為是 fail-open」，比對字串抓不到。用 PIP_NO_INDEX 讓 pip 離線失敗，測試不碰網路。
2. **每個裝得到的 PowerShell host 各跑一次。** 這條是關鍵：pwsh 7.4+ 預設
   `$PSNativeCommandUseErrorActionPreference = $true`，native 非零會自動變成終止錯誤，
   所以**修好之前的 init.ps1 在 pwsh 底下本來就是綠的**——只在 Windows PowerShell 5.1
   fail-open（實測 exit 0 且印 init OK）。只測 pwsh 的話這條測試永遠不會紅。
"""

import codecs
import os
import re
import shutil
import subprocess
import sysconfig
import venv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = REPO_ROOT / "init.ps1"

IMPOSSIBLE_PACKAGE = "reels-summarizer-no-such-package==9.9.9"

# F27：pip < 25.1 用 locale（中文 Windows = cp950）解碼 requirements 檔，中文註解會炸。
# 新舊 pip 都認 PEP-263 宣告，所以真檔與這裡的假檔都在第一行宣告一次。
ENCODING_COOKIE = "# -*- coding: utf-8 -*-\n"

POWERSHELL_HOSTS = [exe for exe in ("pwsh", "powershell") if shutil.which(exe)]


@pytest.mark.skipif(not POWERSHELL_HOSTS, reason="這台機器上找不到 PowerShell")
@pytest.mark.parametrize("host", POWERSHELL_HOSTS)
def test_init_exits_nonzero_and_names_the_package_when_pip_fails(tmp_path, host):
    shutil.copy(INIT_SCRIPT, tmp_path / "init.ps1")
    (tmp_path / "requirements.txt").write_text(
        f"{ENCODING_COOKIE}# 註解行不該被當成套件\n\n{IMPOSSIBLE_PACKAGE}\n",
        encoding="utf-8",
    )
    # init.ps1 走「venv 已存在」分支；要帶 pip，pip 才有東西可失敗
    venv.create(tmp_path / ".venv", with_pip=True)

    result = subprocess.run(
        [shutil.which(host), "-NoProfile", "-File", str(tmp_path / "init.ps1")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PIP_NO_INDEX": "1", "PIP_NO_INPUT": "1"},
        timeout=600,
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, f"[{host}] pip 裝不起來卻 exit 0：\n{output}"
    assert "init OK" not in output, f"[{host}] pip 裝不起來卻印了 init OK：\n{output}"
    assert IMPOSSIBLE_PACKAGE in output, f"[{host}] 沒有指名失敗的套件：\n{output}"


@pytest.mark.skipif(
    "powershell" not in POWERSHELL_HOSTS, reason="沒有 Windows PowerShell 5.1"
)
def test_init_script_has_utf8_bom():
    """5.1 沒有 BOM 就按 ANSI codepage(cp950) 讀，中文會被拆壞到連 parse 都過不了。

    實測：無 BOM 版在 5.1 是 `TerminatorExpectedAtEndOfString` parse error——
    也就是說少了 BOM，上面那條測試想驗的失敗處理根本沒機會執行。
    """
    assert INIT_SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_requirements_txt_declares_its_encoding():
    """requirements.txt 有非 ASCII 內容就必須自己宣告編碼，否則 pip 拿 locale 去解。

    pip < 25.1 的解碼順序是 BOM -> PEP-263 註解 -> locale。中文 Windows 的 locale 是 cp950，
    所以檔裡的中文註解會讓 `pip install -r` 在解析階段就 UnicodeDecodeError，init.ps1 一個
    套件都裝不起來。pip >= 25.1 改成先試 UTF-8，但兩個版本都認 PEP-263 註解。

    F27 之所以 8/27 綠、8/31 紅：executor worktree 的 venv 建出來的臨時 venv 帶 pip 25.0.1
    （會過），主工作區 .venv（Python 3.13.0）建出來的帶 pip 24.2（會炸）。綠不綠取決於是誰
    建的 venv，不是程式改了什麼——所以要把「檔頭有宣告」這件事釘住。
    """
    data = (REPO_ROOT / "requirements.txt").read_bytes()
    if data.isascii():
        return

    head = b"\n".join(data.split(b"\n")[:2])
    assert data.startswith(codecs.BOM_UTF8) or re.search(
        rb"coding[:=]\s*utf-8", head, re.IGNORECASE
    ), "requirements.txt 有非 ASCII 內容卻沒在前兩行宣告編碼，舊 pip 會用 cp950 解碼失敗"


def _venv_with_host_pytest(root: Path) -> None:
    r"""在 root 下建一個離線就有 pytest 的 venv。

    init.ps1 寫死用 `.\.venv\Scripts\python.exe`，而 F25 要驗的是「pip 全裝成功、
    只有煙霧測試失敗」那條路徑——所以新 venv 必須裝得起 pytest，又不能碰網路。
    做法是把跑這支測試的 venv 的 site-packages 用 .pth 掛進去：pytest 直接可 import，
    PIP_NO_INDEX 下的 `pip install pytest` 也就變成「Requirement already satisfied」exit 0。
    """
    venv.create(root / ".venv", with_pip=True)
    python = root / ".venv" / "Scripts" / "python.exe"
    target_sp = subprocess.run(
        [str(python), "-c", "import sysconfig;print(sysconfig.get_paths()['purelib'])"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    (Path(target_sp) / "_host_site.pth").write_text(
        sysconfig.get_paths()["purelib"] + "\n", encoding="utf-8"
    )


@pytest.mark.skipif(not POWERSHELL_HOSTS, reason="這台機器上找不到 PowerShell")
@pytest.mark.parametrize("host", POWERSHELL_HOSTS)
def test_init_exits_nonzero_and_blames_the_tests_when_smoke_tests_fail(tmp_path, host):
    """F25：套件都裝好、只有煙霧測試沒過時，不能再印 init OK。

    斷言全部用 ASCII——兩個 PowerShell host 都以 cp950 輸出中文，用 utf-8 收會變亂碼
    （與檔頭 F20 那條同一個理由），所以失敗訊息帶 `[smoke-test]` 這個 ASCII 標記，
    用來證明腳本有講清楚是測試階段失敗、不是安裝失敗。
    """
    shutil.copy(INIT_SCRIPT, tmp_path / "init.ps1")
    # 註解行以外沒有套件 -> 離線也裝得完，讓流程走到煙霧測試那一步
    (tmp_path / "requirements.txt").write_text(
        f"{ENCODING_COOKIE}# 本測試不裝任何東西\n", encoding="utf-8"
    )
    # .env 已存在就不會走 Copy-Item .env.example（那會在 $ErrorActionPreference=Stop 下中斷）
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_smoke_fails.py").write_text(
        "def test_deliberately_failing():\n    assert False\n", encoding="utf-8"
    )
    _venv_with_host_pytest(tmp_path)

    result = subprocess.run(
        [shutil.which(host), "-NoProfile", "-File", str(tmp_path / "init.ps1")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PIP_NO_INDEX": "1", "PIP_NO_INPUT": "1"},
        timeout=600,
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, f"[{host}] 煙霧測試失敗卻 exit 0：\n{output}"
    assert "init OK" not in output, f"[{host}] 煙霧測試失敗卻印了 init OK：\n{output}"
    assert "[smoke-test]" in output, f"[{host}] 沒說明失敗發生在煙霧測試階段：\n{output}"
