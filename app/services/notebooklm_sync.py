"""NotebookLM 同步服務 — 透過 Chrome CDP 連線自動化上傳摘要與媒體檔案"""

import asyncio
import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import requests

from app.config import settings
from app.database.models import get_notebook_by_date, save_or_update_notebook


logger = logging.getLogger(__name__)

# NotebookLM URL 常數
NOTEBOOKLM_BASE_URL = "https://notebooklm.google.com"
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


@dataclass
class NotebookLMResult:
    """NotebookLM 上傳結果"""

    success: bool
    notebook_url: Optional[str] = None
    notebook_title: Optional[str] = None
    error_message: Optional[str] = None


class NotebookLMSyncService:
    """
    NotebookLM 同步服務

    透過 Chrome CDP（Chrome DevTools Protocol）連接到使用者已開啟的 Chrome 瀏覽器，
    自動化上傳摘要文字與媒體檔案到 NotebookLM。
    按日期分組：每日一個 Notebook，命名 "IG Content - {YYYY-MM-DD}"。

    使用方式：
    1. 設定 NOTEBOOKLM_ENABLED=true
    2. Chrome 會在需要時自動啟動（含 remote debugging）
    3. 首次使用：在自動開啟的 Chrome 視窗中登入 Google 帳號
    4. 設定 NOTEBOOKLM_CDP_URL=http://localhost:9222（預設值）
    5. 可選：設定 NOTEBOOKLM_CHROME_PROFILE 指定 Chrome 使用者資料目錄
    """

    def __init__(self):
        self.cdp_url = settings.notebooklm_cdp_url
        self.upload_video = settings.notebooklm_upload_video
        self._playwright = None
        self._browser = None
        self._context = None
        self._chrome_process = None  # 由本服務啟動的 Chrome 程序

    # ==================== Chrome CDP 自動啟動 ====================

    @staticmethod
    def _find_chrome_executable() -> Optional[str]:
        """在系統中尋找 Chrome 執行檔"""
        # Windows 常見路徑
        if platform.system() == "Windows":
            candidates = [
                os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
            ]
            for c in candidates:
                if c and os.path.isfile(c):
                    return c
        else:
            # macOS / Linux
            for name in ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]:
                path = shutil.which(name)
                if path:
                    return path
            # macOS 常見路徑
            mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            if os.path.isfile(mac_path):
                return mac_path

        return None

    def _get_cdp_port(self) -> int:
        """從 cdp_url 提取 port"""
        parsed = urlparse(self.cdp_url)
        return parsed.port or 9222

    def _get_chrome_profile_dir(self) -> str:
        """取得 Chrome CDP 專用 user-data-dir"""
        if settings.notebooklm_chrome_profile:
            return settings.notebooklm_chrome_profile
        return os.path.join(os.path.expanduser("~"), ".chrome-cdp-notebooklm")

    def _is_cdp_running(self) -> bool:
        """檢查 CDP 是否已執行中"""
        port = self._get_cdp_port()
        try:
            resp = requests.get(f"http://localhost:{port}/json/version", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def _start_chrome_cdp(self) -> bool:
        """
        自動啟動 Chrome 並開啟 remote debugging

        Returns:
            True 表示啟動成功，False 表示失敗
        """
        chrome_path = self._find_chrome_executable()
        if not chrome_path:
            logger.warning("找不到 Chrome 執行檔，無法自動啟動 CDP")
            return False

        port = self._get_cdp_port()
        profile_dir = self._get_chrome_profile_dir()

        logger.info(f"正在自動啟動 Chrome CDP (port={port}, profile={profile_dir})...")

        try:
            args = [
                chrome_path,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                NOTEBOOKLM_BASE_URL,
            ]

            # 使用 subprocess.Popen 在背景啟動（不等待結束）
            if platform.system() == "Windows":
                self._chrome_process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                )
            else:
                self._chrome_process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            logger.info(f"Chrome 已啟動 (PID={self._chrome_process.pid})，等待 CDP 就緒...")
            return True

        except Exception as e:
            logger.error(f"啟動 Chrome 失敗: {e}")
            return False

    async def _wait_for_cdp_ready(self, timeout: int = 15) -> bool:
        """
        等待 CDP 端口就緒

        Args:
            timeout: 最大等待秒數

        Returns:
            True 表示 CDP 已就緒
        """
        for i in range(timeout):
            if self._is_cdp_running():
                logger.info(f"Chrome CDP 已就緒 (等待 {i + 1} 秒)")
                return True
            await asyncio.sleep(1)

        logger.error(f"Chrome CDP 在 {timeout} 秒內未就緒")
        return False

    # ==================== 瀏覽器連線 ====================

    async def _launch_browser(self) -> bool:
        """透過 CDP 連接到 Chrome，若未啟動則自動啟動"""
        try:
            from playwright.async_api import async_playwright

            if self._playwright is None:
                self._playwright = await async_playwright().start()

            # 先檢查 CDP 是否已在執行
            if not self._is_cdp_running():
                logger.warning("Chrome CDP 未執行，嘗試自動啟動...")
                started = self._start_chrome_cdp()
                if not started:
                    logger.error(
                        "無法自動啟動 Chrome。"
                        f"請手動執行: chrome --remote-debugging-port={self._get_cdp_port()} "
                        f'--user-data-dir="{self._get_chrome_profile_dir()}"'
                    )
                    return False

                # 等待 CDP 就緒
                ready = await self._wait_for_cdp_ready(timeout=15)
                if not ready:
                    return False

            self._browser = await self._playwright.chromium.connect_over_cdp(
                self.cdp_url
            )

            # 使用 Chrome 現有的 context（已有登入狀態）
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
                logger.info(f"已透過 CDP 連接到 Chrome（{self.cdp_url}）")
            else:
                # 如果沒有 context，建立新的（不太常見）
                self._context = await self._browser.new_context()
                logger.info("已透過 CDP 連接，建立新 context")

            return True

        except Exception as e:
            logger.error(
                f"CDP 連線失敗: {e}。"
                f"請確認 Chrome 已啟動且開啟 remote debugging（{self.cdp_url}）"
            )
            self._browser = None
            self._context = None
            return False

    async def _close_browser(self):
        """中斷 CDP 連線（不關閉使用者的 Chrome）"""
        try:
            # CDP 模式：只中斷連線，不關閉瀏覽器本身
            if self._browser:
                await self._browser.close()
                self._browser = None
            self._context = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
        except Exception as e:
            logger.debug(f"中斷 CDP 連線時發生錯誤: {e}")

    async def _verify_login(self, page) -> bool:
        """驗證 Google 登入狀態"""
        try:
            await page.goto(NOTEBOOKLM_BASE_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(8000)

            current_url = page.url

            # 如果被導向到登入頁面，表示尚未登入
            if "accounts.google.com" in current_url or "signin" in current_url:
                logger.error("Google 尚未登入，請在 CDP Chrome 中登入 Google 帳號")
                return False

            # 確認在 NotebookLM 頁面
            if "notebooklm.google.com" in current_url:
                logger.info("Google 登入驗證成功，已進入 NotebookLM")
                return True

            logger.warning(f"非預期的頁面: {current_url}")
            return False

        except Exception as e:
            logger.error(f"驗證登入狀態失敗: {e}")
            return False

    async def _is_notebook_not_found(self, page) -> bool:
        """檢查頁面是否顯示 Notebook 不存在的錯誤"""
        try:
            # 檢查頁面是否有「找不到筆記本」的錯誤訊息
            not_found = await page.evaluate("""() => {
                const body = document.body ? document.body.innerText : '';
                const notFoundPhrases = [
                    '找不到筆記本',
                    'Notebook not found',
                    '請檢查網址',
                    'Check the URL',
                    'does not exist',
                    '不存在'
                ];
                return notFoundPhrases.some(phrase => body.includes(phrase));
            }""")

            if not_found:
                return True

            # 如果 URL 被導回首頁（不含 notebook ID），也表示 notebook 不存在
            current_url = page.url
            if current_url.rstrip("/") == NOTEBOOKLM_BASE_URL:
                return True

            return False
        except Exception:
            return False

    async def _ensure_notebook(self, page, date_str: str) -> Optional[str]:
        """
        確保指定日期的 Notebook 存在，不存在則建立

        Args:
            page: Playwright page 物件
            date_str: 日期字串 (YYYY-MM-DD)

        Returns:
            Notebook URL 或 None
        """
        notebook_title = f"IG Content - {date_str}"

        # 查詢 DB 是否已有今日 notebook
        existing = await get_notebook_by_date(date_str)
        if existing and existing.notebook_url:
            logger.info(f"使用既有 Notebook: {existing.notebook_title} ({existing.notebook_url})")
            try:
                await page.goto(existing.notebook_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(8000)

                current_url = page.url

                # 檢查是否被導向到登入頁面
                if "accounts.google.com" in current_url:
                    logger.warning("導航到既有 Notebook 失敗（需要登入），嘗試建立新的")
                # 檢查 Notebook 是否已被刪除（頁面顯示錯誤或被導回首頁）
                elif await self._is_notebook_not_found(page):
                    logger.warning("既有 Notebook 已不存在（可能已被刪除），建立新的")
                elif "notebooklm.google.com" in current_url:
                    return existing.notebook_url
                else:
                    logger.warning(f"導航到非預期頁面: {current_url}，嘗試建立新的")
            except Exception as e:
                logger.warning(f"導航到既有 Notebook 失敗: {e}，嘗試建立新的")

        # 建立新 Notebook
        return await self._create_notebook(page, notebook_title, date_str)

    async def _create_notebook(self, page, title: str, date_str: str) -> Optional[str]:
        """
        建立新的 NotebookLM Notebook

        Args:
            page: Playwright page 物件
            title: Notebook 標題
            date_str: 日期字串

        Returns:
            新建 Notebook 的 URL 或 None
        """
        try:
            # 導航到 NotebookLM 首頁
            await page.goto(NOTEBOOKLM_BASE_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(8000)

            # 點擊「新建」按鈕 (aria-label='建立新的筆記本')
            new_btn = page.locator('button[aria-label="建立新的筆記本"]')
            if await new_btn.count() == 0:
                # 備用：文字匹配
                new_btn = page.locator(
                    'button:has-text("新建"), '
                    'button:has-text("New notebook"), '
                    'button:has-text("Create")'
                )
            if await new_btn.count() > 0:
                await new_btn.first.click()
                await page.wait_for_timeout(5000)
            else:
                logger.error("找不到建立 Notebook 的按鈕")
                return None

            # 新建 Notebook 會自動開啟 add-source 面板，需先關閉才能編輯標題
            close_btn = page.locator('button[aria-label="關閉"]')
            if await close_btn.count() > 0:
                await close_btn.first.click()
                await page.wait_for_timeout(2000)

            # 設定 Notebook 標題
            await self._set_notebook_title(page, title)

            # 取得 Notebook URL（移除 ?addSource=true 參數）
            notebook_url = page.url.split("?")[0]
            logger.info(f"已建立新 Notebook: {title} ({notebook_url})")

            # 儲存到 DB
            await save_or_update_notebook(
                date_str=date_str,
                notebook_url=notebook_url,
                notebook_title=title,
                increment_source=False,
            )

            return notebook_url

        except Exception as e:
            logger.error(f"建立 Notebook 失敗: {e}")
            return None

    async def _set_notebook_title(self, page, title: str) -> None:
        """設定 Notebook 標題"""
        try:
            # NotebookLM 的標題是 <span> 在 <div.title-container> 裡，不可直接點擊（not visible）
            # 需要透過 JS 點擊 div.title-container 來觸發編輯模式
            clicked = await page.evaluate("""() => {
                const container = document.querySelector('.title-container');
                if (container) {
                    container.click();
                    return true;
                }
                return false;
            }""")

            if clicked:
                await page.wait_for_timeout(500)

                # 點擊後會出現 input.title-input
                title_input = page.locator("input.title-input")
                if await title_input.count() > 0 and await title_input.first.is_visible():
                    await title_input.first.click()
                    await title_input.first.fill("")
                    await title_input.first.fill(title)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(500)
                    logger.info(f"已設定 Notebook 標題: {title}")
                    return

            # 備用方法：直接嘗試 get_by_text + force click
            title_el = page.get_by_text("Untitled notebook", exact=True)
            if await title_el.count() > 0:
                await title_el.first.click(force=True)
                await page.wait_for_timeout(500)
                title_input = page.locator("input.title-input")
                if await title_input.count() > 0 and await title_input.first.is_visible():
                    await title_input.first.fill(title)
                    await page.keyboard.press("Enter")
                    logger.info(f"已設定 Notebook 標題（force click）: {title}")
                    return

            logger.warning("找不到標題輸入區域，保持預設標題")

        except Exception as e:
            logger.warning(f"設定 Notebook 標題失敗: {e}")

    async def _upload_text_source(self, page, content: str, title: str) -> bool:
        """
        以「貼上文字」方式上傳摘要到 NotebookLM 作為 source

        Args:
            page: Playwright page 物件
            content: 摘要 Markdown 文字
            title: Source 標題

        Returns:
            是否上傳成功
        """
        try:
            # 確認 add source 面板已開啟（新 Notebook 自動開啟，否則手動開啟）
            paste_btn = page.locator('button:has-text("複製的文字")')
            if await paste_btn.count() == 0:
                # 需要先開啟 add source 面板
                add_source_clicked = await self._click_add_source(page)
                if not add_source_clicked:
                    return False
                await page.wait_for_timeout(2000)

            # 點擊「複製的文字」選項
            paste_btn = page.locator('button:has-text("複製的文字")')
            if await paste_btn.count() == 0:
                paste_btn = page.locator(
                    'button:has-text("Copied text"), '
                    'button:has-text("Paste text")'
                )
            if await paste_btn.count() > 0:
                await paste_btn.first.click(force=True)
                await page.wait_for_timeout(3000)
            else:
                logger.error("找不到「複製的文字」選項")
                return False

            # 填入標題和文字
            # 注意：Angular Material 會在互動時重新渲染元素，導致 detached from DOM
            # 因此使用 JavaScript 直接設定值，避免 stale element 問題
            filled = await page.evaluate(
                """(args) => {
                const [title, content] = args;
                const results = { title: false, content: false };

                // 填入標題 - 找最後一個 title-input（source 的，非 notebook 的）
                const titleInputs = document.querySelectorAll('input.title-input');
                const titleInput = titleInputs[titleInputs.length - 1];
                if (titleInput) {
                    const nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeSetter.call(titleInput, title);
                    titleInput.dispatchEvent(new Event('input', { bubbles: true }));
                    titleInput.dispatchEvent(new Event('change', { bubbles: true }));
                    results.title = true;
                }

                // 填入文字內容
                const textarea = document.querySelector(
                    'textarea[aria-label="貼上的文字"], ' +
                    'textarea.copied-text-input-textarea'
                );
                if (textarea) {
                    const nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value'
                    ).set;
                    nativeSetter.call(textarea, content);
                    textarea.dispatchEvent(new Event('input', { bubbles: true }));
                    textarea.dispatchEvent(new Event('change', { bubbles: true }));
                    results.content = true;
                }

                return results;
            }""",
                [title, content],
            )

            if filled.get("title"):
                logger.debug(f"已填入 source 標題: {title}")
            else:
                logger.warning("無法填入 source 標題")

            if filled.get("content"):
                logger.debug("已填入摘要文字")
            else:
                logger.error("無法填入摘要文字")
                return False

            await page.wait_for_timeout(1000)

            # 點擊「插入」按鈕
            insert_btn = page.locator('button:has-text("插入")')
            if await insert_btn.count() == 0:
                insert_btn = page.locator(
                    'button:has-text("Insert"), '
                    'button:has-text("Add source")'
                )
            if await insert_btn.count() > 0:
                await insert_btn.first.click(force=True)
                await page.wait_for_timeout(8000)
                logger.info(f"已上傳文字 source: {title}")
                return True

            # 如果沒有明確的插入按鈕，嘗試 Enter 或提交
            logger.warning("找不到插入按鈕，嘗試按 Enter")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(3000)
            return True

        except Exception as e:
            logger.error(f"上傳文字 source 失敗: {e}")
            return False

    async def _upload_file_source(self, page, file_path: Path) -> bool:
        """
        上傳單一檔案到 NotebookLM 作為 source

        Args:
            page: Playwright page 物件
            file_path: 檔案路徑

        Returns:
            是否上傳成功
        """
        return await self._upload_multiple_files_at_once(page, [file_path])

    async def _upload_multiple_files_at_once(
        self, page, file_paths: List[Path]
    ) -> bool:
        """
        一次選取多個檔案上傳到 NotebookLM（透過 file chooser 多選）

        Args:
            page: Playwright page 物件
            file_paths: 檔案路徑列表

        Returns:
            是否上傳成功
        """
        try:
            valid_paths = [p for p in file_paths if p and p.exists()]
            if not valid_paths:
                logger.warning("沒有有效的檔案可上傳")
                return False

            file_names = [p.name for p in valid_paths]
            logger.info(f"準備一次上傳 {len(valid_paths)} 個檔案: {file_names}")

            # 開啟 add source 面板
            add_source_clicked = await self._click_add_source(page)
            if not add_source_clicked:
                return False
            await page.wait_for_timeout(2000)

            # 點擊「上傳檔案」按鈕
            upload_btn = page.locator('button:has-text("上傳檔案")')
            if await upload_btn.count() == 0:
                upload_btn = page.locator(
                    'button:has-text("Upload"), '
                    'button:has-text("File upload"), '
                    'button[aria-label="開啟「上傳來源」對話方塊"]'
                )

            if await upload_btn.count() > 0:
                async with page.expect_file_chooser(timeout=10000) as fc_info:
                    await upload_btn.first.click(force=True)
                file_chooser = await fc_info.value
                # 一次選取所有檔案
                await file_chooser.set_files([str(p) for p in valid_paths])
            else:
                # 嘗試直接尋找 input[type=file]
                file_input = page.locator('input[type="file"]')
                if await file_input.count() > 0:
                    await file_input.first.set_input_files(
                        [str(p) for p in valid_paths]
                    )
                else:
                    logger.error("找不到檔案上傳按鈕或 input")
                    return False

            # 等待上傳完成（多檔案需要更長時間）
            wait_seconds = max(10, len(valid_paths) * 5)
            logger.info(
                f"正在上傳 {len(valid_paths)} 個檔案，等待 {wait_seconds} 秒..."
            )
            await page.wait_for_timeout(wait_seconds * 1000)

            # 檢查是否有確認按鈕需要點擊
            confirm_btn = page.locator(
                'button:has-text("插入"), '
                'button:has-text("Insert"), '
                'button:has-text("新增"), '
                'button:has-text("Add")'
            )
            if await confirm_btn.count() > 0:
                await confirm_btn.first.click()
                await page.wait_for_timeout(5000)

            logger.info(f"已一次上傳 {len(valid_paths)} 個檔案 source")
            return True

        except Exception as e:
            logger.error(f"批次上傳檔案 source 失敗: {e}")
            return False

    async def _upload_files_source(
        self, page, file_paths: List[Path], notebook_url: str
    ) -> bool:
        """
        批次上傳多個檔案到 NotebookLM 作為 sources（一次選取所有檔案）

        Args:
            page: Playwright page 物件
            file_paths: 檔案路徑列表
            notebook_url: Notebook URL（用於確保頁面位置）

        Returns:
            是否上傳成功
        """
        valid_paths = [p for p in file_paths if p and p.exists()]
        if not valid_paths:
            return False

        # 確保頁面在 notebook 上
        current_url = page.url
        if not current_url.startswith(notebook_url.split("?")[0]):
            logger.info(f"頁面已跳轉，導航回 notebook: {notebook_url}")
            await page.goto(
                notebook_url, wait_until="domcontentloaded", timeout=30000
            )
            await page.wait_for_timeout(3000)

        # 一次上傳所有檔案
        return await self._upload_multiple_files_at_once(page, valid_paths)

    async def _click_add_source(self, page) -> bool:
        """點擊 'Add source' 按鈕（處理 CDK overlay 遮擋問題）"""
        try:
            # 等待頁面完全載入
            await page.wait_for_timeout(3000)

            # 先關閉任何 CDK overlay backdrop（Angular Material 的遮罩層會攔截點擊）
            await page.evaluate("""() => {
                // 移除所有 CDK overlay backdrop
                document.querySelectorAll('.cdk-overlay-backdrop').forEach(el => el.remove());
                // 也移除可能殘留的 overlay container 中的空 pane
                document.querySelectorAll('.cdk-overlay-pane:empty').forEach(el => el.remove());
            }""")
            await page.wait_for_timeout(500)

            # 用 JavaScript 直接點擊按鈕，繞過 CDK overlay 攔截
            clicked = await page.evaluate("""() => {
                // 嘗試多種選擇器
                const selectors = [
                    'button[aria-label="新增來源"]',
                    'button.add-source-button',
                    'button[mattooltip="新增來源"]',
                    'button[aria-label="Add source"]',
                    'button[mattooltip="Add source"]',
                    'button[aria-label="開啟「上傳來源」對話方塊"]'
                ];

                for (const sel of selectors) {
                    const btn = document.querySelector(sel);
                    if (btn) {
                        btn.click();
                        return { success: true, selector: sel };
                    }
                }

                // 備用：搜尋包含文字的按鈕
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    const text = btn.textContent.trim();
                    if (text.includes('新增來源') || text.includes('Add source')) {
                        btn.click();
                        return { success: true, selector: 'text:' + text.substring(0, 30) };
                    }
                }

                return { success: false, buttons: Array.from(buttons).map(b => ({
                    text: b.textContent.trim().substring(0, 50),
                    aria: b.getAttribute('aria-label') || '',
                    class: b.className.substring(0, 80)
                })).filter(b => b.aria || b.text) };
            }""")

            if clicked.get("success"):
                logger.debug(f"已點擊 Add source 按鈕（{clicked.get('selector')}）")
                await page.wait_for_timeout(2000)
                return True

            logger.error(f"找不到 'Add source' 按鈕。頁面按鈕: {clicked.get('buttons', [])}")
            return False

        except Exception as e:
            logger.error(f"點擊 'Add source' 失敗: {e}")
            return False

    async def _update_markdown_with_link(
        self, note_path: Optional[str], notebook_url: str
    ) -> None:
        """
        在已儲存的 Markdown 檔案中插入 NotebookLM 連結

        Args:
            note_path: Markdown 檔案路徑
            notebook_url: NotebookLM Notebook URL
        """
        if not note_path:
            return

        try:
            file_path = Path(note_path)
            if not file_path.exists():
                logger.warning(f"筆記檔案不存在，無法插入 NotebookLM 連結: {note_path}")
                return

            content = file_path.read_text(encoding="utf-8")

            # 在「來源資訊」區塊後插入 NotebookLM 連結
            nlm_link = f"\n- 🤖 NotebookLM: [{notebook_url}]({notebook_url})"

            pattern = r"(## 來源資訊.*?)(\n\n)"
            match = re.search(pattern, content, re.DOTALL)
            if match:
                insert_pos = match.end(1)
                updated_content = content[:insert_pos] + nlm_link + content[insert_pos:]
            else:
                # 備用：在標題行後插入
                lines = content.split("\n")
                insert_idx = 2 if len(lines) > 2 else len(lines)
                lines.insert(insert_idx, f"\n🤖 NotebookLM: {notebook_url}")
                updated_content = "\n".join(lines)

            file_path.write_text(updated_content, encoding="utf-8")
            logger.info(f"已在筆記中插入 NotebookLM 連結: {note_path}")

        except Exception as e:
            logger.warning(f"插入 NotebookLM 連結失敗: {e}")

    def _find_note_path(self, roam_result) -> Optional[str]:
        """
        從 RoamSyncResult 推算筆記檔案路徑

        Args:
            roam_result: RoamSyncResult 物件

        Returns:
            筆記檔案的完整路徑字串
        """
        if not roam_result or not roam_result.success or not roam_result.page_title:
            return None

        backup_dir = Path(settings.temp_video_dir).parent / "roam_backup"
        safe_title = "".join(
            c for c in roam_result.page_title if c.isalnum() or c in (" ", "-", "_")
        ).strip()
        filename = f"{safe_title}.md"
        file_path = backup_dir / filename

        if file_path.exists():
            return str(file_path)
        return None

    async def _upload_with_retry(
        self,
        markdown_content: str,
        media_paths: List[Path],
        title: str,
    ) -> NotebookLMResult:
        """
        帶重試機制的上傳核心邏輯

        Args:
            markdown_content: 摘要 Markdown 內容
            media_paths: 媒體檔案路徑列表（影片或圖片）
            title: Source 標題
            note_path: 筆記檔案路徑（用於回寫 NotebookLM 連結）

        Returns:
            NotebookLMResult
        """
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # 連接到 Chrome CDP
                launched = await self._launch_browser()
                if not launched:
                    last_error = (
                        "無法連接到 Chrome CDP"
                        f"（請確認 Chrome 已啟動且開啟 remote debugging: {self.cdp_url}）"
                    )
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue

                page = await self._context.new_page()

                try:
                    # 驗證登入狀態
                    logged_in = await self._verify_login(page)
                    if not logged_in:
                        last_error = (
                            "Google 登入狀態無效，"
                            "請在 CDP Chrome 中登入 Google 帳號"
                        )
                        continue

                    today_str = datetime.now().strftime("%Y-%m-%d")

                    # 確保 Notebook 存在
                    notebook_url = await self._ensure_notebook(page, today_str)
                    if not notebook_url:
                        last_error = "無法建立或導航到 NotebookLM Notebook"
                        continue

                    # 上傳摘要文字
                    text_uploaded = await self._upload_text_source(
                        page, markdown_content, title
                    )
                    if not text_uploaded:
                        logger.warning("文字 source 上傳失敗")

                    # 確保頁面還在 notebook（上傳後可能跳轉到 source 詳情）
                    current_url = page.url
                    if not current_url.startswith(notebook_url.split("?")[0]):
                        logger.info(f"文字上傳後頁面跳轉，導航回 notebook: {notebook_url}")
                        await page.goto(notebook_url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(3000)

                    # 上傳媒體檔案（如果啟用且有檔案）
                    if self.upload_video and media_paths:
                        valid_paths = [p for p in media_paths if p and p.exists()]
                        if valid_paths:
                            await self._upload_files_source(page, valid_paths, notebook_url)

                    # 更新 DB 中的 source 計數
                    notebook_title = f"IG Content - {today_str}"
                    await save_or_update_notebook(
                        date_str=today_str,
                        notebook_url=notebook_url,
                        notebook_title=notebook_title,
                        increment_source=True,
                    )

                    return NotebookLMResult(
                        success=True,
                        notebook_url=notebook_url,
                        notebook_title=notebook_title,
                    )

                finally:
                    await page.close()

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"NotebookLM 上傳嘗試 {attempt}/{MAX_RETRIES} 失敗: {e}"
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)

            finally:
                await self._close_browser()

        return NotebookLMResult(
            success=False,
            error_message=f"上傳失敗（已重試 {MAX_RETRIES} 次）: {last_error}",
        )

    async def upload_reel(
        self,
        markdown_content: str,
        video_path: Optional[Path] = None,
        title: str = "",
    ) -> NotebookLMResult:
        """
        上傳 Reel 摘要與影片到 NotebookLM

        Args:
            markdown_content: 摘要 Markdown 內容
            video_path: 影片檔案路徑
            title: Reel 標題

        Returns:
            NotebookLMResult
        """
        media_paths = [video_path] if video_path and video_path.exists() else []

        logger.info(f"開始上傳 Reel 到 NotebookLM: {title}")
        return await self._upload_with_retry(
            markdown_content=markdown_content,
            media_paths=media_paths,
            title=title,
        )

    async def upload_post(
        self,
        markdown_content: str,
        image_paths: Optional[List[Path]] = None,
        title: str = "",
    ) -> NotebookLMResult:
        """
        上傳 Post 摘要與圖片到 NotebookLM

        Args:
            markdown_content: 摘要 Markdown 內容
            image_paths: 圖片檔案路徑列表
            title: Post 標題

        Returns:
            NotebookLMResult
        """
        valid_paths = [p for p in (image_paths or []) if p and p.exists()]

        logger.info(f"開始上傳 Post 到 NotebookLM: {title} ({len(valid_paths)} 張圖片)")
        return await self._upload_with_retry(
            markdown_content=markdown_content,
            media_paths=valid_paths,
            title=title,
        )

    async def upload_threads(
        self,
        markdown_content: str,
        media_paths: Optional[List[Path]] = None,
        title: str = "",
    ) -> NotebookLMResult:
        """
        上傳 Threads 摘要與媒體到 NotebookLM

        Args:
            markdown_content: 摘要 Markdown 內容
            media_paths: 媒體檔案路徑列表（可選）
            title: Threads 標題

        Returns:
            NotebookLMResult
        """
        valid_paths = [p for p in (media_paths or []) if p and p.exists()]

        logger.info(f"開始上傳 Threads 到 NotebookLM: {title}")
        return await self._upload_with_retry(
            markdown_content=markdown_content,
            media_paths=valid_paths,
            title=title,
        )
