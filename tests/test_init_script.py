"""F20：init.ps1 在 pip 安裝失敗時必須非零結束、不得印 init OK，且要指名失敗的套件。

兩個刻意的設計：

1. **真的跑一次 init.ps1**，不做 structure assertion——原本的 bug 就是「腳本讀起來沒問題但
   行為是 fail-open」，比對字串抓不到。用 PIP_NO_INDEX 讓 pip 離線失敗，測試不碰網路。
2. **每個裝得到的 PowerShell host 各跑一次。** 這條是關鍵：pwsh 7.4+ 預設
   `$PSNativeCommandUseErrorActionPreference = $true`，native 非零會自動變成終止錯誤，
   所以**修好之前的 init.ps1 在 pwsh 底下本來就是綠的**——只在 Windows PowerShell 5.1
   fail-open（實測 exit 0 且印 init OK）。只測 pwsh 的話這條測試永遠不會紅。
"""

import os
import shutil
import subprocess
import venv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = REPO_ROOT / "init.ps1"

IMPOSSIBLE_PACKAGE = "reels-summarizer-no-such-package==9.9.9"

POWERSHELL_HOSTS = [exe for exe in ("pwsh", "powershell") if shutil.which(exe)]


@pytest.mark.skipif(not POWERSHELL_HOSTS, reason="這台機器上找不到 PowerShell")
@pytest.mark.parametrize("host", POWERSHELL_HOSTS)
def test_init_exits_nonzero_and_names_the_package_when_pip_fails(tmp_path, host):
    shutil.copy(INIT_SCRIPT, tmp_path / "init.ps1")
    (tmp_path / "requirements.txt").write_text(
        f"# 註解行不該被當成套件\n\n{IMPOSSIBLE_PACKAGE}\n", encoding="utf-8"
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
