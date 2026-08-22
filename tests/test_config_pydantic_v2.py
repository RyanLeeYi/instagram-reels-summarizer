"""F11：config.py 不得再走 pydantic V1 相容路徑，且環境變數綁定不能因此斷掉"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 這兩個是 Settings 的必填欄位，子行程沒有 .env 也要能建起來
REQUIRED_ENV = {
    "TELEGRAM_BOT_TOKEN": "test-token",
    "ROAM_GRAPH_NAME": "test-graph",
}


def test_import_and_construct_emits_no_pydantic_deprecation():
    """warning 是 import 期的全域狀態，必須在乾淨的直譯器裡驗"""
    probe = (
        "import warnings\n"
        "from pydantic import PydanticDeprecatedSince20\n"
        "warnings.filterwarnings('error', category=PydanticDeprecatedSince20)\n"
        "from app.config import Settings\n"
        "Settings()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env={**os.environ, **REQUIRED_ENV},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr


def test_env_var_still_binds_by_field_name(monkeypatch):
    """移掉 Field(env=...) 之後，綁定改由欄位名推導——這條會在推導失效時紅"""
    from app.config import Settings

    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("OLLAMA_MODEL", "sentinel-model")
    monkeypatch.setenv("ANTIGRAVITY_VISION_TIMEOUT_SECONDS", "7")

    settings = Settings(_env_file=None)

    assert settings.telegram_bot_token == "test-token"
    assert settings.ollama_model == "sentinel-model"
    assert settings.antigravity_vision_timeout_seconds == 7
