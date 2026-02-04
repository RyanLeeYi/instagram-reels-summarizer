"""摘要服務工廠模組

根據設定自動選擇使用 Ollama、Claude Code 或 Copilot CLI 作為摘要服務
"""

import logging
from typing import TYPE_CHECKING, Union

from app.config import settings


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.summarizer import OllamaSummarizer
    from app.services.claude_summarizer import ClaudeCodeSummarizer
    from app.services.copilot_summarizer import CopilotCLISummarizer


def get_summarizer() -> Union["OllamaSummarizer", "ClaudeCodeSummarizer", "CopilotCLISummarizer"]:
    """
    根據設定取得摘要服務實例
    
    環境變數 SUMMARIZER_BACKEND 可設定為:
    - "ollama": 使用本地 Ollama + Qwen3 (預設)
    - "claude": 使用 Claude Code CLI
    - "copilot": 使用 GitHub Copilot CLI
    
    Returns:
        摘要服務實例
    """
    backend = settings.summarizer_backend.lower()
    
    if backend == "claude":
        from app.services.claude_summarizer import ClaudeCodeSummarizer, check_claude_cli_available
        
        if check_claude_cli_available():
            logger.info(f"使用 Claude Code CLI 作為摘要服務 (model={settings.claude_model})")
            return ClaudeCodeSummarizer(model=settings.claude_model)
        else:
            logger.warning("Claude Code CLI 不可用，fallback 到 Ollama")
            from app.services.summarizer import OllamaSummarizer
            return OllamaSummarizer()
    
    elif backend == "copilot":
        from app.services.copilot_summarizer import CopilotCLISummarizer, check_copilot_cli_available
        
        if check_copilot_cli_available():
            logger.info(f"使用 Copilot CLI 作為摘要服務 (model={settings.copilot_model})")
            return CopilotCLISummarizer(model=settings.copilot_model)
        else:
            logger.warning("Copilot CLI 不可用，fallback 到 Ollama")
            from app.services.summarizer import OllamaSummarizer
            return OllamaSummarizer()
    
    else:
        from app.services.summarizer import OllamaSummarizer
        logger.info(f"使用 Ollama 作為摘要服務 (model={settings.ollama_model})")
        return OllamaSummarizer()


def check_summarizer_available() -> dict:
    """
    檢查各摘要服務的可用性
    
    Returns:
        dict: 各服務的可用狀態
    """
    status = {
        "ollama": False,
        "claude": False,
        "copilot": False,
        "current_backend": settings.summarizer_backend,
    }
    
    # 檢查 Ollama
    try:
        import ollama
        ollama.list()
        status["ollama"] = True
    except Exception:
        pass
    
    # 檢查 Claude Code CLI
    try:
        from app.services.claude_summarizer import check_claude_cli_available
        status["claude"] = check_claude_cli_available()
    except Exception:
        pass
    
    # 檢查 Copilot CLI
    try:
        from app.services.copilot_summarizer import check_copilot_cli_available
        status["copilot"] = check_copilot_cli_available()
    except Exception:
        pass
    
    return status
