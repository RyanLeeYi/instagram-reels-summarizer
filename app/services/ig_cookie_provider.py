"""IG cookies 自動供應：從 NotebookLM 同一個 CDP Chrome profile 抽 IG cookies。

原理：在 CDP Chrome 登入 IG 一次，session 由真瀏覽器維持活性；下載前把
最新 cookies 轉成 Netscape 格式覆寫 cookies.txt（yt-dlp / instaloader 共用），
從此不需手動匯出。CDP 不可用或該 profile 未登入 IG 時，保留既有檔案並輸出
可行動警告（fallback 到手動 cookies.txt 的舊行為）。
"""

import logging
import time
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

logger = logging.getLogger(__name__)

IG_URLS = ["https://www.instagram.com", "https://i.instagram.com"]
NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n# 由 ig_cookie_provider 自動產生，手動修改會被覆寫\n"

# 可注入的抓取函式型別：回傳 (cookies, user_agent)；cookies 為 None 代表 CDP 不可用。
# UA 必須跟著 cookies 走：IG session 綁 client 指紋，用別的 UA 打會被判 cross-client 拒絕
FetchResult = tuple[Optional[List[dict]], Optional[str]]
FetchCookies = Callable[[], Awaitable[FetchResult]]


class IGCookieProvider:
    """把 CDP Chrome 的 IG 登入態變成 cookies.txt 的供應器。"""

    def __init__(
        self,
        cookies_file: Path = Path("cookies.txt"),
        max_age_seconds: int = 3600,
        fetch_cookies: Optional[FetchCookies] = None,
    ):
        self.cookies_file = cookies_file
        self.user_agent_file = cookies_file.parent / (cookies_file.name + ".ua")
        self.max_age_seconds = max_age_seconds
        self._fetch_cookies = fetch_cookies or self._fetch_from_cdp

    @staticmethod
    def to_netscape(cookies: List[dict]) -> str:
        """Playwright cookie dicts → Netscape cookies.txt 內容。"""
        lines = [NETSCAPE_HEADER.rstrip("\n")]
        for c in cookies:
            domain = c.get("domain", "")
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            secure = "TRUE" if c.get("secure") else "FALSE"
            expires = c.get("expires", 0) or 0
            expiry = "0" if expires < 0 else str(int(expires))
            lines.append(
                "\t".join(
                    [domain, include_subdomains, c.get("path", "/"), secure,
                     expiry, c.get("name", ""), c.get("value", "")]
                )
            )
        return "\n".join(lines) + "\n"

    def _file_is_fresh(self) -> bool:
        """檔案存在、未過期、且含 sessionid 才算新鮮。"""
        if not self.cookies_file.exists():
            return False
        age = time.time() - self.cookies_file.stat().st_mtime
        if age > self.max_age_seconds:
            return False
        try:
            content = self.cookies_file.read_text(encoding="utf-8")
        except OSError:
            return False
        return "sessionid" in content

    def read_user_agent(self) -> Optional[str]:
        """取 cookies 誕生瀏覽器的 UA（sidecar 檔）；沒有回 None。"""
        try:
            ua = self.user_agent_file.read_text(encoding="utf-8").strip()
            return ua or None
        except OSError:
            return None

    async def refresh(self) -> bool:
        """從 CDP 抽 cookies 覆寫 cookies.txt；拿不到含 sessionid 的就保留原檔。"""
        cookies, user_agent = await self._fetch_cookies()
        if cookies is None:
            logger.warning("⚠️ CDP Chrome 不可用，沿用既有 cookies.txt")
            return False
        if not any(c.get("name") == "sessionid" and c.get("value") for c in cookies):
            logger.warning(
                "⚠️ CDP Chrome 的 profile 尚未登入 Instagram（無 sessionid）——"
                "請在該 Chrome 視窗開 instagram.com 登入一次，之後即可自動供應"
            )
            return False
        self.cookies_file.write_text(self.to_netscape(cookies), encoding="utf-8")
        if user_agent:
            self.user_agent_file.write_text(user_agent + "\n", encoding="utf-8")
        logger.info(f"✅ 已從 CDP Chrome 刷新 IG cookies（{len(cookies)} 個）→ {self.cookies_file}")
        return True

    async def refresh_if_stale(self) -> bool:
        """檔案還新鮮就跳過；過期或缺 sessionid 才刷新。回傳「現在檔案可不可用」。"""
        if self._file_is_fresh():
            return True
        return await self.refresh()

    async def _fetch_from_cdp(self) -> FetchResult:
        """連 CDP Chrome 取 IG cookies + 瀏覽器 UA；Chrome 沒開就嘗試拉起（同 NotebookLM profile）。"""
        try:
            # 延遲 import 避免循環依賴；共用 NotebookLM 的 Chrome 啟動邏輯與 profile，
            # _launch_browser 會自動拉起 Chrome 並設定 _context（現有 context 含登入態）
            from app.services.notebooklm_sync import NotebookLMSyncService

            svc = NotebookLMSyncService()
            if not await svc._launch_browser():
                return None, None
            try:
                cookies = await svc._context.cookies(IG_URLS)
                page = await svc._context.new_page()
                try:
                    user_agent = await page.evaluate("navigator.userAgent")
                finally:
                    await page.close()
                return cookies, user_agent
            finally:
                await svc._close_browser()
        except Exception as e:
            logger.warning(f"從 CDP 取 IG cookies 失敗: {e}")
            return None, None


# 模組級單例：downloader 直接用
provider = IGCookieProvider(
    cookies_file=Path("cookies.txt"),
    max_age_seconds=3600,
)
