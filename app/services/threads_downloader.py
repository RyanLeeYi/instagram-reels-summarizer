"""Threads (Meta) 串文下載服務"""

import asyncio
import http.cookiejar
import logging
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import requests

from app.config import settings


logger = logging.getLogger(__name__)


# Cookies 檔案路徑
COOKIES_FILE_PATH = Path(__file__).parent.parent.parent / "cookies.txt"


@dataclass
class ThreadsMedia:
    """Threads 媒體資料"""

    url: str
    media_type: str  # "image" | "video"


@dataclass
class ThreadsMediaDownloadResult:
    """Threads 媒體下載結果"""

    success: bool
    image_paths: List[Path] = field(default_factory=list)
    video_paths: List[Path] = field(default_factory=list)
    audio_paths: List[Path] = field(default_factory=list)  # 從影片中提取的音訊
    error_message: Optional[str] = None


@dataclass
class ThreadPost:
    """Threads 貼文資料"""

    id: str
    author_username: str
    text_content: str
    timestamp: Optional[datetime] = None
    like_count: int = 0
    reply_count: int = 0
    media: List[ThreadsMedia] = field(default_factory=list)  # 媒體列表（含類型）
    quoted_post: Optional["ThreadPost"] = None


@dataclass
class ThreadConversation:
    """Threads 對話串資料"""

    parent_post: ThreadPost
    replies: List[ThreadPost] = field(default_factory=list)


@dataclass
class ThreadsDownloadResult:
    """Threads 下載結果"""

    success: bool
    content_type: str = "single_post"  # "single_post" | "thread_conversation"
    post: Optional[ThreadPost] = None
    conversation: Optional[ThreadConversation] = None
    error_message: Optional[str] = None


class ThreadsDownloader:
    """Threads (Meta) 串文下載器"""

    # 支援的 Threads URL 格式
    # https://www.threads.net/@username/post/ABC123xyz
    # https://www.threads.com/@username/post/ABC123xyz
    # https://threads.net/t/ABC123xyz
    THREADS_URL_PATTERNS = [
        r"https?://(?:www\.)?threads\.(?:net|com)/@([\w.]+)/post/([A-Za-z0-9_-]+)",
        r"https?://(?:www\.)?threads\.(?:net|com)/t/([A-Za-z0-9_-]+)",
    ]

    def __init__(self):
        self._api = None
        self._logged_in = False

    def _load_cookies_from_file(self) -> dict:
        """
        從 Netscape cookie 檔案載入 cookies
        
        Returns:
            dict: 包含 cookie 名稱和值的字典
        """
        cookies = {}
        
        if not COOKIES_FILE_PATH.exists():
            logger.debug(f"Cookie 檔案不存在: {COOKIES_FILE_PATH}")
            return cookies
            
        try:
            # 使用 http.cookiejar 解析 Netscape 格式
            cookie_jar = http.cookiejar.MozillaCookieJar(str(COOKIES_FILE_PATH))
            cookie_jar.load(ignore_discard=True, ignore_expires=True)
            
            for cookie in cookie_jar:
                # 只載入 instagram.com 和 threads.net 的 cookies
                if 'instagram.com' in cookie.domain or 'threads.net' in cookie.domain:
                    cookies[cookie.name] = cookie.value
                    
            logger.debug(f"從 cookies.txt 載入 {len(cookies)} 個 cookies")
            return cookies
            
        except Exception as e:
            logger.warning(f"載入 cookies 失敗: {e}")
            return cookies

    def _get_api(self):
        """
        取得 MetaThreads API 實例（懶惰初始化）

        Returns:
            ThreadsAPI: MetaThreads API 實例
        """
        if self._api is not None:
            return self._api

        try:
            from metathreads import MetaThreads

            self._api = MetaThreads()

            # 優先嘗試使用 cookie 認證
            cookies = self._load_cookies_from_file()
            if cookies:
                try:
                    # 將 cookies 注入到 httpx session
                    for name, value in cookies.items():
                        self._api.session.cookies.set(name, value, domain=".threads.net")
                        # 也設定到 instagram.com（有些 API 可能需要）
                        self._api.session.cookies.set(name, value, domain=".instagram.com")
                    
                    self._logged_in = True
                    logger.info(f"✅ Threads 使用 cookie 認證成功 (載入 {len(cookies)} 個 cookies)")
                except Exception as e:
                    logger.warning(f"⚠️ 注入 cookies 失敗: {e}")
                    self._logged_in = False
            # 若無 cookie，嘗試帳號密碼登入
            elif settings.threads_username and settings.threads_password:
                try:
                    self._api.login(
                        settings.threads_username,
                        settings.threads_password
                    )
                    self._logged_in = True
                    logger.info(f"✅ Threads 登入成功: @{settings.threads_username}")
                except Exception as e:
                    logger.warning(f"⚠️ Threads 登入失敗: {e}，將使用未認證模式")
                    self._logged_in = False
            else:
                logger.info("Threads 使用未認證模式（僅能存取公開內容）")

            return self._api

        except ImportError:
            logger.error("❌ MetaThreads 函式庫未安裝，請執行 'pip install metathreads'")
            raise RuntimeError("MetaThreads 函式庫未安裝，請執行 'pip install metathreads'")

    def _get_session_with_cookies(self) -> requests.Session:
        """
        建立帶有 cookies 的 requests Session（用於 web scraping）
        
        Returns:
            requests.Session: 設定好 cookies 的 session
        """
        session = requests.Session()
        
        # 載入 cookies
        if COOKIES_FILE_PATH.exists():
            try:
                cookie_jar = http.cookiejar.MozillaCookieJar(str(COOKIES_FILE_PATH))
                cookie_jar.load(ignore_discard=True, ignore_expires=True)
                for cookie in cookie_jar:
                    session.cookies.set(cookie.name, cookie.value, domain=cookie.domain)
                logger.debug(f"Web scraping: 載入 {len(session.cookies)} 個 cookies")
            except Exception as e:
                logger.warning(f"載入 cookies 失敗: {e}")
        
        # 設定瀏覽器 headers (簡化版，避免觸發反爬蟲)
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        
        return session

    def _decode_unicode_text(self, raw_text: str) -> str:
        """
        解碼 unicode 轉義序列
        
        Args:
            raw_text: 原始文字（可能包含 \\uXXXX）
            
        Returns:
            解碼後的文字
        """
        try:
            # 使用 latin-1 編碼然後 unicode-escape 解碼
            return raw_text.encode('latin-1').decode('unicode-escape')
        except Exception:
            try:
                # 備用方案：直接 unicode-escape
                return raw_text.encode('utf-8').decode('unicode-escape')
            except Exception:
                # 最後方案：返回原始文字
                return raw_text

    def _download_via_web_scraping(self, url: str) -> Optional[ThreadPost]:
        """
        透過 Web Scraping 下載 Threads 貼文（備用方案）
        支援串文（thread）- 會抓取同一作者的所有連續貼文
        
        Args:
            url: Threads 貼文 URL
            
        Returns:
            ThreadPost 或 None
        """
        logger.info(f"嘗試使用 Web Scraping 抓取 Threads 貼文...")
        
        try:
            session = self._get_session_with_cookies()
            response = session.get(url, timeout=30)
            response.raise_for_status()
            
            html = response.text
            
            # 提取使用者名稱
            username = self.extract_username(url)
            if not username:
                # 從 HTML 中提取
                username_match = re.search(r'"username":"([^"]+)"', html)
                if username_match:
                    username = username_match.group(1)
            
            # 提取貼文 ID
            post_id = self.extract_post_id(url) or ""
            
            # 檢查是否為串文（thread）
            is_thread = 'thread_items' in html
            
            # 找到所有貼文的 code（ID），用於識別串文中的貼文
            all_codes = re.findall(r'"code":"([A-Za-z0-9_-]+)"', html)
            # 過濾掉非貼文 code（如 en_US）
            post_codes = [c for c in all_codes if len(c) > 5 and not c.startswith('en_')]
            # 取得主貼文 ID 的前綴（串文中的貼文通常有相似的 ID 前綴）
            main_prefix = post_id[:4] if post_id else ""
            # 串文中的貼文 code
            thread_codes = set(c for c in post_codes if c.startswith(main_prefix)) if main_prefix else set()
            
            logger.debug(f"Web scraping: 主貼文 ID={post_id}, 串文貼文數={len(thread_codes)}")
            
            # 提取所有文字內容
            text_matches = re.findall(r'"text":"((?:[^"\\]|\\.)*?)"', html)
            logger.debug(f"Web scraping: 找到 {len(text_matches)} 個 text 欄位")
            
            all_texts = []
            seen_texts = set()  # 用於去重
            
            for raw_text in text_matches:
                if len(raw_text) < 10:  # 忽略太短的文字
                    continue
                    
                decoded = self._decode_unicode_text(raw_text)
                
                # 去重（避免重複的文字）
                text_hash = decoded[:50] if len(decoded) > 50 else decoded
                if text_hash in seen_texts:
                    continue
                seen_texts.add(text_hash)
                
                # 過濾掉非貼文內容
                if is_thread and len(thread_codes) > 1:
                    # 對於串文，只收集：
                    # 1. 有編號的文字 (1️⃣ 2️⃣ 等)
                    # 2. 第一則（最長）的貼文
                    # 3. 結尾類的文字（如果你也覺得...）
                    has_number = any(c in decoded for c in '1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣🔟')
                    is_conclusion = decoded.startswith('如果你也') or decoded.startswith('歡迎')
                    is_main_post = len(decoded) > 200  # 主貼文通常較長
                    
                    if has_number or is_conclusion or is_main_post:
                        all_texts.append(decoded)
                else:
                    # 單一貼文或無法識別串文結構
                    all_texts.append(decoded)
            
            # 組合文字內容
            if is_thread and len(all_texts) > 1:
                # 串文：按順序組合，用分隔線分開
                text_content = "\n\n---\n\n".join(all_texts)
                logger.info(f"Web scraping: 偵測到串文，共 {len(all_texts)} 則貼文")
            elif all_texts:
                # 單一貼文：取最長的
                text_content = max(all_texts, key=len)
            else:
                text_content = ""
            
            # 如果文字內容是空的，嘗試其他方法
            if not text_content:
                caption_match = re.search(r'"caption":\s*\{\s*"text":"((?:[^"\\]|\\.)*)"', html)
                if caption_match:
                    text_content = self._decode_unicode_text(caption_match.group(1))
            
            # 提取媒體 URL
            media_list: List[ThreadsMedia] = []
            
            # 圖片 URL (scontent CDN)
            img_urls = re.findall(r'"url":"(https://scontent[^"]+)"', html)
            # 過濾掉 profile 圖片（通常較小）
            img_urls = [u for u in img_urls if 's150x150' not in u and '_s150x150' not in u and 't51.2885' not in u]
            # 去重並取最高解析度
            seen_base = set()
            for img_url in img_urls:
                # 取基本 URL（去掉解析度參數）
                base_url = re.sub(r'_e\d+_', '_', img_url.split('?')[0])
                if base_url not in seen_base:
                    seen_base.add(base_url)
                    media_list.append(ThreadsMedia(url=img_url, media_type="image"))
            
            # 影片 URL
            video_urls = re.findall(r'"video_url":"([^"]+)"', html)
            for video_url in video_urls:
                # 解碼 URL
                video_url = video_url.replace('\\u0026', '&').replace('\\/', '/')
                media_list.append(ThreadsMedia(url=video_url, media_type="video"))
            
            # 也檢查 video_versions
            video_version_urls = re.findall(r'"video_versions":\[.*?"url":"([^"]+)"', html)
            for video_url in video_version_urls:
                video_url = video_url.replace('\\u0026', '&').replace('\\/', '/')
                if not any(m.url == video_url for m in media_list):
                    media_list.append(ThreadsMedia(url=video_url, media_type="video"))
            
            # 提取時間戳
            timestamp = None
            taken_at_match = re.search(r'"taken_at":(\d+)', html)
            if taken_at_match:
                try:
                    timestamp = datetime.fromtimestamp(int(taken_at_match.group(1)))
                except:
                    pass
            
            # 提取互動數據
            like_count = 0
            like_match = re.search(r'"like_count":(\d+)', html)
            if like_match:
                like_count = int(like_match.group(1))
            
            reply_count = 0
            reply_match = re.search(r'"reply_count":(\d+)|"direct_reply_count":(\d+)', html)
            if reply_match:
                reply_count = int(reply_match.group(1) or reply_match.group(2) or 0)
            
            if not text_content and not media_list:
                logger.warning("Web scraping: 無法提取貼文內容或媒體")
                return None
            
            logger.info(f"Web scraping 成功: @{username}, {len(media_list)} 個媒體, {len(text_content)} 字")
            
            return ThreadPost(
                id=post_id,
                author_username=username or "unknown",
                text_content=text_content,
                timestamp=timestamp,
                like_count=like_count,
                reply_count=reply_count,
                media=media_list,
            )
            
        except requests.RequestException as e:
            logger.error(f"Web scraping 請求失敗: {e}")
            return None
        except Exception as e:
            logger.error(f"Web scraping 解析失敗: {e}")
            return None

    def validate_url(self, url: str) -> bool:
        """驗證是否為有效的 Threads 連結"""
        for pattern in self.THREADS_URL_PATTERNS:
            if re.match(pattern, url):
                return True
        return False

    def extract_post_id(self, url: str) -> Optional[str]:
        """
        從 URL 提取貼文 ID

        Args:
            url: Threads 連結

        Returns:
            貼文 ID 或 None
        """
        # 格式 1: https://threads.net/@username/post/ABC123xyz 或 threads.com
        match = re.match(
            r"https?://(?:www\.)?threads\.(?:net|com)/@[\w.]+/post/([A-Za-z0-9_-]+)",
            url
        )
        if match:
            return match.group(1)

        # 格式 2: https://threads.net/t/ABC123xyz 或 threads.com
        match = re.match(
            r"https?://(?:www\.)?threads\.(?:net|com)/t/([A-Za-z0-9_-]+)",
            url
        )
        if match:
            return match.group(1)

        return None

    def extract_username(self, url: str) -> Optional[str]:
        """
        從 URL 提取使用者名稱

        Args:
            url: Threads 連結

        Returns:
            使用者名稱或 None
        """
        match = re.match(
            r"https?://(?:www\.)?threads\.(?:net|com)/@([\w.]+)/post/",
            url
        )
        if match:
            return match.group(1)
        return None

    async def download(self, url: str) -> ThreadsDownloadResult:
        """
        下載 Threads 貼文內容

        Args:
            url: Threads 連結

        Returns:
            ThreadsDownloadResult: 下載結果
        """
        if not self.validate_url(url):
            return ThreadsDownloadResult(
                success=False,
                error_message="無法解析此連結，請確認是否為有效的 Threads 連結",
            )

        post_id = self.extract_post_id(url)
        if not post_id:
            return ThreadsDownloadResult(
                success=False,
                error_message="無法從連結提取貼文 ID",
            )

        try:
            # 在執行緒池中執行（MetaThreads 是同步的）
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._download_sync, post_id, url
            )
            return result

        except Exception as e:
            logger.error(f"下載 Threads 貼文失敗: {e}")
            return ThreadsDownloadResult(
                success=False,
                error_message=f"下載失敗: {str(e)}",
            )

    def _download_sync(self, post_id: str, url: str) -> ThreadsDownloadResult:
        """同步下載方法"""
        api_failed = False
        api_error_message = ""
        
        try:
            api = self._get_api()

            # 取得貼文資料
            logger.info(f"正在抓取 Threads 貼文: {post_id}")

            try:
                post_data = api.get_thread(post_id)
                
                # 檢查是否為錯誤回應
                if isinstance(post_data, dict):
                    if post_data.get("status") == "fail" or post_data.get("message"):
                        error_msg = post_data.get("message", "").lower()
                        if "login" in error_msg:
                            api_failed = True
                            api_error_message = "API 需要登入"
                        elif "not found" in error_msg or "404" in str(post_data):
                            return ThreadsDownloadResult(
                                success=False,
                                error_message="找不到此貼文，可能已被刪除或為私人內容",
                            )
                        else:
                            api_failed = True
                            api_error_message = post_data.get('message', '未知錯誤')
                            
            except Exception as e:
                error_msg = str(e).lower()
                if "not found" in error_msg or "404" in error_msg:
                    return ThreadsDownloadResult(
                        success=False,
                        error_message="找不到此貼文，可能已被刪除或為私人內容",
                    )
                api_failed = True
                api_error_message = str(e)

            # 如果 API 失敗，嘗試 Web Scraping
            if api_failed:
                logger.warning(f"MetaThreads API 失敗 ({api_error_message})，嘗試 Web Scraping...")
                scraped_post = self._download_via_web_scraping(url)
                if scraped_post:
                    logger.info(f"✅ Web Scraping 成功: @{scraped_post.author_username}")
                    return ThreadsDownloadResult(
                        success=True,
                        content_type="single_post",
                        post=scraped_post,
                    )
                else:
                    return ThreadsDownloadResult(
                        success=False,
                        error_message=f"API 和 Web Scraping 都無法取得內容。\n\nAPI 錯誤: {api_error_message}\n\n請確認：\n1. cookies.txt 包含有效的 Instagram 登入資訊\n2. 或在 .env 設定 THREADS_USERNAME 和 THREADS_PASSWORD",
                    )

            # 解析貼文資料
            parent_post = self._parse_post_data(post_data)

            if not parent_post:
                # API 回傳但解析失敗，嘗試 Web Scraping
                logger.warning("API 資料解析失敗，嘗試 Web Scraping...")
                scraped_post = self._download_via_web_scraping(url)
                if scraped_post:
                    return ThreadsDownloadResult(
                        success=True,
                        content_type="single_post",
                        post=scraped_post,
                    )
                return ThreadsDownloadResult(
                    success=False,
                    error_message="無法解析貼文資料",
                )

            # 如果啟用了抓取回覆，嘗試取得對話串
            if settings.threads_fetch_replies:
                try:
                    conversation = self._fetch_conversation(api, post_id, parent_post)
                    if conversation and conversation.replies:
                        logger.info(f"成功抓取對話串，共 {len(conversation.replies)} 則回覆")
                        return ThreadsDownloadResult(
                            success=True,
                            content_type="thread_conversation",
                            conversation=conversation,
                        )
                except Exception as e:
                    logger.warning(f"抓取對話串失敗，將只回傳原始貼文: {e}")

            # 回傳單一貼文
            logger.info(f"成功抓取 Threads 貼文: @{parent_post.author_username}")
            return ThreadsDownloadResult(
                success=True,
                content_type="single_post",
                post=parent_post,
            )

        except RuntimeError as e:
            # MetaThreads 未安裝
            return ThreadsDownloadResult(
                success=False,
                error_message=str(e),
            )
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Threads 下載失敗: {error_msg}")

            if "rate limit" in error_msg.lower():
                return ThreadsDownloadResult(
                    success=False,
                    error_message="已達到 API 請求限制，請稍後再試",
                )

            return ThreadsDownloadResult(
                success=False,
                error_message=f"下載時發生錯誤: {error_msg}",
            )

    def _parse_post_data(self, post_data: dict) -> Optional[ThreadPost]:
        """
        解析 MetaThreads 回傳的貼文資料

        Args:
            post_data: MetaThreads API 回傳的原始資料

        Returns:
            ThreadPost 或 None
        """
        try:
            # MetaThreads 的資料結構可能在不同版本有所不同
            # 嘗試多種欄位名稱
            post_id = (
                post_data.get("id")
                or post_data.get("pk")
                or post_data.get("code")
                or ""
            )

            # 取得作者資訊
            user_data = post_data.get("user", {})
            author_username = (
                user_data.get("username")
                or post_data.get("username")
                or "unknown"
            )

            # 取得文字內容
            text_content = (
                post_data.get("caption", {}).get("text")
                if isinstance(post_data.get("caption"), dict)
                else post_data.get("caption")
                or post_data.get("text")
                or post_data.get("text_post_app_info", {}).get("share_info", {}).get("quoted_text")
                or ""
            )

            # 取得時間戳記
            timestamp = None
            taken_at = post_data.get("taken_at") or post_data.get("created_at")
            if taken_at:
                try:
                    if isinstance(taken_at, (int, float)):
                        timestamp = datetime.fromtimestamp(taken_at)
                    elif isinstance(taken_at, str):
                        timestamp = datetime.fromisoformat(taken_at.replace("Z", "+00:00"))
                except Exception:
                    pass

            # 取得互動數據
            like_count = (
                post_data.get("like_count")
                or post_data.get("likes", {}).get("count")
                or 0
            )
            reply_count = (
                post_data.get("reply_count")
                or post_data.get("text_post_app_info", {}).get("direct_reply_count")
                or 0
            )

            # 取得媒體 URL（含類型判斷）
            media_list: List[ThreadsMedia] = []
            carousel_media = post_data.get("carousel_media", [])
            if carousel_media:
                for media in carousel_media:
                    if media.get("video_versions"):
                        media_list.append(ThreadsMedia(
                            url=media["video_versions"][0]["url"],
                            media_type="video"
                        ))
                    elif media.get("image_versions2", {}).get("candidates"):
                        media_list.append(ThreadsMedia(
                            url=media["image_versions2"]["candidates"][0]["url"],
                            media_type="image"
                        ))
            elif post_data.get("video_versions"):
                media_list.append(ThreadsMedia(
                    url=post_data["video_versions"][0]["url"],
                    media_type="video"
                ))
            elif post_data.get("image_versions2", {}).get("candidates"):
                media_list.append(ThreadsMedia(
                    url=post_data["image_versions2"]["candidates"][0]["url"],
                    media_type="image"
                ))

            # 取得引用貼文（如果有）
            quoted_post = None
            quoted_post_data = post_data.get("text_post_app_info", {}).get("share_info", {}).get("quoted_post")
            if quoted_post_data:
                quoted_post = self._parse_post_data(quoted_post_data)

            return ThreadPost(
                id=str(post_id),
                author_username=author_username,
                text_content=text_content,
                timestamp=timestamp,
                like_count=like_count,
                reply_count=reply_count,
                media=media_list,
                quoted_post=quoted_post,
            )

        except Exception as e:
            logger.warning(f"解析貼文資料失敗: {e}")
            return None

    def _fetch_conversation(
        self,
        api,
        post_id: str,
        parent_post: ThreadPost
    ) -> Optional[ThreadConversation]:
        """
        取得完整對話串（包含回覆）

        Args:
            api: MetaThreads API 實例
            post_id: 貼文 ID
            parent_post: 父貼文

        Returns:
            ThreadConversation 或 None
        """
        try:
            # 取得回覆
            replies_data = api.get_thread_replies(post_id)

            if not replies_data:
                return ThreadConversation(parent_post=parent_post, replies=[])

            replies = []
            max_replies = settings.threads_max_replies

            for reply_data in replies_data[:max_replies]:
                reply = self._parse_post_data(reply_data)
                if reply:
                    replies.append(reply)

            return ThreadConversation(
                parent_post=parent_post,
                replies=replies,
            )

        except Exception as e:
            logger.warning(f"取得對話串失敗: {e}")
            return None

    def format_for_summary(self, result: ThreadsDownloadResult) -> str:
        """
        將下載結果格式化為適合 LLM 摘要的文字

        Args:
            result: 下載結果

        Returns:
            格式化後的文字內容
        """
        if not result.success:
            return ""

        lines = []

        if result.content_type == "single_post" and result.post:
            lines.append(self._format_post(result.post, is_main=True))

        elif result.content_type == "thread_conversation" and result.conversation:
            # 格式化主貼文
            lines.append(self._format_post(result.conversation.parent_post, is_main=True))

            # 格式化回覆
            if result.conversation.replies:
                lines.append("\n【對話串回覆】")
                for i, reply in enumerate(result.conversation.replies, 1):
                    lines.append(f"\n--- 回覆 #{i} ---")
                    lines.append(self._format_post(reply, is_main=False))

        return "\n".join(lines)

    def _format_post(self, post: ThreadPost, is_main: bool = False) -> str:
        """格式化單一貼文"""
        lines = []

        if is_main:
            lines.append(f"【主貼文】 @{post.author_username}")
        else:
            lines.append(f"@{post.author_username}")

        if post.timestamp:
            lines.append(f"發佈時間: {post.timestamp.strftime('%Y-%m-%d %H:%M')}")

        lines.append(f"\n{post.text_content}")

        if post.like_count > 0 or post.reply_count > 0:
            stats = []
            if post.like_count > 0:
                stats.append(f"❤️ {post.like_count}")
            if post.reply_count > 0:
                stats.append(f"💬 {post.reply_count}")
            lines.append(f"\n({' | '.join(stats)})")

        if post.quoted_post:
            lines.append(f"\n> 引用自 @{post.quoted_post.author_username}:")
            lines.append(f"> {post.quoted_post.text_content[:200]}...")

        if post.media:
            image_count = sum(1 for m in post.media if m.media_type == "image")
            video_count = sum(1 for m in post.media if m.media_type == "video")
            media_info = []
            if image_count > 0:
                media_info.append(f"{image_count} 張圖片")
            if video_count > 0:
                media_info.append(f"{video_count} 個影片")
            lines.append(f"\n[附件: {', '.join(media_info)}]")

        return "\n".join(lines)

    # ==================== 媒體下載方法 ====================

    def _get_temp_dir(self) -> Path:
        """取得暫存目錄"""
        temp_dir = Path(settings.temp_video_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def _download_image_sync(self, url: str, retry: int = 2) -> Optional[Path]:
        """
        下載單張圖片（同步方法，含重試機制）

        Args:
            url: 圖片 URL
            retry: 重試次數

        Returns:
            圖片檔案路徑或 None
        """
        temp_dir = self._get_temp_dir()
        file_id = uuid.uuid4().hex[:8]
        image_path = temp_dir / f"threads_img_{file_id}.jpg"

        for attempt in range(retry + 1):
            try:
                response = requests.get(url, timeout=30, stream=True)
                response.raise_for_status()

                with open(image_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                logger.info(f"✅ 圖片下載成功: {image_path.name}")
                return image_path

            except Exception as e:
                if attempt < retry:
                    logger.warning(f"圖片下載失敗 (第 {attempt + 1} 次)，重試中: {e}")
                else:
                    logger.error(f"圖片下載失敗 (已達最大重試): {e}")

        return None

    def _download_video_sync(self, url: str, retry: int = 2) -> tuple[Optional[Path], Optional[Path]]:
        """
        下載影片並提取音訊（同步方法，含重試機制）

        Args:
            url: 影片 URL
            retry: 重試次數

        Returns:
            (影片路徑, 音訊路徑) 或 (None, None)
        """
        temp_dir = self._get_temp_dir()
        file_id = uuid.uuid4().hex[:8]
        video_path = temp_dir / f"threads_vid_{file_id}.mp4"
        audio_path = temp_dir / f"threads_aud_{file_id}.mp3"

        for attempt in range(retry + 1):
            try:
                # 下載影片
                response = requests.get(url, timeout=60, stream=True)
                response.raise_for_status()

                with open(video_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                logger.info(f"✅ 影片下載成功: {video_path.name}")

                # 使用 ffmpeg 提取音訊（如果有音軌）
                if self._has_audio_track(video_path):
                    try:
                        subprocess.run(
                            [
                                "ffmpeg", "-y", "-i", str(video_path),
                                "-vn", "-acodec", "libmp3lame", "-q:a", "2",
                                str(audio_path)
                            ],
                            capture_output=True,
                            timeout=60,
                        )
                        if audio_path.exists():
                            logger.info(f"✅ 音訊提取成功: {audio_path.name}")
                            return video_path, audio_path
                    except Exception as e:
                        logger.warning(f"音訊提取失敗: {e}")

                return video_path, None

            except Exception as e:
                if attempt < retry:
                    logger.warning(f"影片下載失敗 (第 {attempt + 1} 次)，重試中: {e}")
                else:
                    logger.error(f"影片下載失敗 (已達最大重試): {e}")

        return None, None

    def _has_audio_track(self, video_path: Path) -> bool:
        """
        使用 ffprobe 檢測影片是否含有音軌

        Args:
            video_path: 影片檔案路徑

        Returns:
            True 表示有音軌，False 表示無音軌
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "a",
                    "-show_entries", "stream=codec_type",
                    "-of", "csv=p=0",
                    str(video_path)
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            has_audio = "audio" in result.stdout.lower()
            logger.debug(f"影片 {video_path.name} 音軌偵測: {'有' if has_audio else '無'}")
            return has_audio
        except Exception as e:
            logger.warning(f"音軌偵測失敗，預設為有音軌: {e}")
            return True  # 偵測失敗時預設為有音軌（會嘗試轉錄）

    async def download_media(self, media_list: List[ThreadsMedia]) -> ThreadsMediaDownloadResult:
        """
        下載所有媒體檔案

        Args:
            media_list: 媒體列表

        Returns:
            ThreadsMediaDownloadResult: 下載結果
        """
        if not media_list:
            return ThreadsMediaDownloadResult(success=True)

        image_paths: List[Path] = []
        video_paths: List[Path] = []
        audio_paths: List[Path] = []

        loop = asyncio.get_event_loop()

        for media in media_list:
            if media.media_type == "image":
                path = await loop.run_in_executor(
                    None, self._download_image_sync, media.url
                )
                if path:
                    image_paths.append(path)

            elif media.media_type == "video":
                video_path, audio_path = await loop.run_in_executor(
                    None, self._download_video_sync, media.url
                )
                if video_path:
                    video_paths.append(video_path)
                if audio_path:
                    audio_paths.append(audio_path)

        # 只要有任何媒體成功下載就算成功
        success = len(image_paths) > 0 or len(video_paths) > 0
        error_message = None

        if not success and media_list:
            error_message = "所有媒體下載失敗"

        logger.info(
            f"媒體下載完成: {len(image_paths)} 張圖片, "
            f"{len(video_paths)} 個影片, {len(audio_paths)} 個音訊"
        )

        return ThreadsMediaDownloadResult(
            success=success,
            image_paths=image_paths,
            video_paths=video_paths,
            audio_paths=audio_paths,
            error_message=error_message,
        )

    def cleanup_media(self, result: ThreadsMediaDownloadResult) -> None:
        """
        清理暫存的媒體檔案

        Args:
            result: 媒體下載結果
        """
        all_paths = result.image_paths + result.video_paths + result.audio_paths

        for path in all_paths:
            try:
                if path.exists():
                    path.unlink()
                    logger.debug(f"已刪除暫存檔案: {path.name}")
            except Exception as e:
                logger.warning(f"刪除暫存檔案失敗 {path}: {e}")

    def get_all_media(self, result: ThreadsDownloadResult) -> List[ThreadsMedia]:
        """
        從下載結果中收集所有媒體（包含主貼文和回覆）

        Args:
            result: Threads 下載結果

        Returns:
            所有媒體列表
        """
        all_media: List[ThreadsMedia] = []

        if result.content_type == "single_post" and result.post:
            all_media.extend(result.post.media)

        elif result.content_type == "thread_conversation" and result.conversation:
            all_media.extend(result.conversation.parent_post.media)
            for reply in result.conversation.replies:
                all_media.extend(reply.media)

        return all_media
