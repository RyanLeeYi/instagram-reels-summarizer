"""摘要服務測試"""

import pytest
from app.services.summarizer import OllamaSummarizer


class TestOllamaSummarizer:
    """OllamaSummarizer 測試"""

    def setup_method(self):
        """測試前設定"""
        self.summarizer = OllamaSummarizer()

    def test_parse_response_standard_format(self):
        """測試解析標準格式的回應"""
        content = """【摘要】
這是一個關於如何提高工作效率的影片。講者分享了三個實用的技巧。

【重點】
• 第一個技巧是番茄工作法
• 第二個技巧是任務清單
• 第三個技巧是定期休息"""

        result = self.summarizer._parse_response(content)

        assert result.success is True
        assert "工作效率" in result.summary
        assert len(result.bullet_points) == 3
        assert "番茄工作法" in result.bullet_points[0]

    def test_parse_response_with_dashes(self):
        """測試解析使用破折號的重點"""
        content = """【摘要】
這是摘要內容。

【重點】
- 重點一
- 重點二
- 重點三"""

        result = self.summarizer._parse_response(content)

        assert result.success is True
        assert len(result.bullet_points) == 3

    def test_parse_response_with_numbers(self):
        """測試解析使用數字的重點"""
        content = """【摘要】
這是摘要內容。

【重點】
1. 重點一
2. 重點二
3. 重點三"""

        result = self.summarizer._parse_response(content)

        assert result.success is True
        assert len(result.bullet_points) == 3

    def test_parse_response_fallback(self):
        """測試無法解析時的備用方案"""
        content = "這只是一段純文字，沒有格式。"

        result = self.summarizer._parse_response(content)

        assert result.success is True
        assert result.summary == content
