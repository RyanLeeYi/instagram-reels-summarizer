"""metathreads 缺席時的降級行為測試（F23）

metathreads 已從 requirements.txt 移除（PyPI 最高 0.0.4，且釘死 httpx==0.24.1，
與本專案 httpx>=0.25.0 衝突）。全新環境不會有這個套件，_get_api() 會丟 RuntimeError。
這時候不能讓整條 Threads 下載死掉——Googlebot SSR 與 Web Scraping 兩條 fallback
本來就不經過 MetaThreads。
"""

from unittest.mock import MagicMock, patch

from app.services.threads_downloader import ThreadsDownloader, ThreadsDownloadResult


POST_URL = "https://www.threads.com/@someone/post/DbHiGmWD10O"
IMPORT_ERROR = RuntimeError("MetaThreads 函式庫未安裝，請執行 'pip install metathreads'")


def _downloader_without_api():
    d = ThreadsDownloader()
    d._get_api = MagicMock(side_effect=IMPORT_ERROR)
    return d


def test_falls_back_to_ssr_when_metathreads_missing():
    d = _downloader_without_api()
    ssr_ok = ThreadsDownloadResult(success=True, content_type="single_post")

    with patch.object(d, "_download_via_googlebot_ssr", return_value=ssr_ok) as ssr, \
         patch.object(d, "_download_via_web_scraping") as scrape:
        result = d._download_sync("DbHiGmWD10O", POST_URL)

    assert result.success is True
    ssr.assert_called_once_with(POST_URL)
    scrape.assert_not_called()


def test_falls_back_to_web_scraping_when_ssr_also_fails():
    d = _downloader_without_api()
    scraped = MagicMock(author_username="someone")

    with patch.object(d, "_download_via_googlebot_ssr", return_value=None), \
         patch.object(d, "_download_via_web_scraping", return_value=scraped):
        result = d._download_sync("DbHiGmWD10O", POST_URL)

    assert result.success is True
    assert result.content_type == "single_post"
    assert result.post is scraped


def test_reports_failure_only_when_every_fallback_fails():
    d = _downloader_without_api()

    with patch.object(d, "_download_via_googlebot_ssr", return_value=None), \
         patch.object(d, "_download_via_web_scraping", return_value=None):
        result = d._download_sync("DbHiGmWD10O", POST_URL)

    assert result.success is False
    # 訊息不再叫使用者去 pip install 一個裝不起來的套件
    assert "pip install metathreads" not in result.error_message


def test_requirements_does_not_pin_unsatisfiable_metathreads():
    """F23 的本體：requirements.txt 每一條都要裝得起來。"""
    from pathlib import Path

    req = Path(__file__).resolve().parents[1] / "requirements.txt"
    lines = [
        ln.strip()
        for ln in req.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert not any("metathreads" in ln for ln in lines)
