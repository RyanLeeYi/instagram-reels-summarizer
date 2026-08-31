"""F26: /backend 指令——查詢與即時切換摘要 backend（不重啟服務）。

用 mock 取代真實 CLI/Ollama：check_claude_cli_available / check_copilot_cli_available
被 monkeypatch 成回傳固定值，summarizer 實例本身照常建立（建構子不打真的 CLI）。
"""

import pytest

from app.bot.telegram_handler import TelegramBotHandler
from app.config import settings
from app.services.claude_summarizer import ClaudeCodeSummarizer
from app.services.copilot_summarizer import CopilotCLISummarizer
from app.services.summarizer import OllamaSummarizer


class _Message:
    """記錄 reply_text 呼叫內容的替身。"""

    def __init__(self):
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)


class _Update:
    def __init__(self, chat_id):
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.message = _Message()


class _Context:
    def __init__(self, args):
        self.args = args


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setattr(settings, "summarizer_backend", "ollama", raising=False)
    monkeypatch.setattr(settings, "telegram_allowed_chat_ids", "42", raising=False)
    return TelegramBotHandler()


class TestNoArgsQuery:
    @pytest.mark.asyncio
    async def test_replies_current_backend_model_and_availability(self, handler, monkeypatch):
        monkeypatch.setattr(
            "app.services.claude_summarizer.check_claude_cli_available", lambda: True
        )
        monkeypatch.setattr(
            "app.services.copilot_summarizer.check_copilot_cli_available", lambda: False
        )

        update = _Update("42")
        await handler.backend_command(update, _Context([]))

        assert len(update.message.replies) == 1
        text = update.message.replies[0]
        assert "ollama" in text
        assert settings.ollama_model in text
        assert "claude" in text
        assert "copilot" in text


class TestValidSwitch:
    @pytest.mark.asyncio
    async def test_switch_changes_handler_summarizer_type(self, handler, monkeypatch):
        monkeypatch.setattr(
            "app.services.claude_summarizer.check_claude_cli_available", lambda: True
        )

        update = _Update("42")
        await handler.backend_command(update, _Context(["claude"]))

        assert isinstance(handler.summarizer, ClaudeCodeSummarizer)
        assert len(update.message.replies) == 1
        text = update.message.replies[0]
        assert "claude" in text
        assert settings.claude_model in text
        assert "重啟" in text

    @pytest.mark.asyncio
    async def test_switch_accepts_uppercase_argument(self, handler, monkeypatch):
        monkeypatch.setattr(
            "app.services.copilot_summarizer.check_copilot_cli_available", lambda: True
        )

        update = _Update("42")
        await handler.backend_command(update, _Context(["COPILOT"]))

        assert isinstance(handler.summarizer, CopilotCLISummarizer)


class TestFallbackToOllama:
    @pytest.mark.asyncio
    async def test_unavailable_cli_falls_back_and_reply_says_so(self, handler, monkeypatch):
        monkeypatch.setattr(
            "app.services.claude_summarizer.check_claude_cli_available", lambda: False
        )

        update = _Update("42")
        await handler.backend_command(update, _Context(["claude"]))

        assert isinstance(handler.summarizer, OllamaSummarizer)
        text = update.message.replies[0]
        assert "claude" in text and "ollama" in text
        assert "不可用" in text or "退回" in text
        # 不能只回顯使用者輸入而不講實際生效的是 ollama
        assert "已切換摘要 backend 為 claude" not in text


class TestInvalidArgument:
    @pytest.mark.asyncio
    async def test_invalid_backend_name_keeps_current_and_shows_usage(self, handler):
        before = handler.summarizer

        update = _Update("42")
        await handler.backend_command(update, _Context(["gemini"]))

        assert handler.summarizer is before
        text = update.message.replies[0]
        assert "用法" in text
        assert settings.summarizer_backend == "ollama"


class TestAuthorization:
    @pytest.mark.asyncio
    async def test_unauthorized_chat_is_rejected(self, handler):
        before = handler.summarizer

        update = _Update("999")
        await handler.backend_command(update, _Context(["claude"]))

        assert handler.summarizer is before
        assert len(update.message.replies) == 1
        assert "權限" in update.message.replies[0]
