"""
清除 NotebookLM 中的測試筆記本

使用方式:
  python scripts/cleanup_notebooklm.py

會自動搜尋並刪除:
  - "Untitled notebook" (未命名的筆記本)
  - 包含 "TEST" 或 "Test" 的筆記本
  - 今日的測試筆記本 "Instagram Reels - 2026-02-17"
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 要刪除的筆記本標題（精確匹配或包含）
TITLES_TO_DELETE = [
    "Untitled notebook",
    "Test Summary - Python Tips",
    "Python 列表推導式技巧",
    "Instagram Reels - 2026-02-17",
]


async def cleanup_notebooks():
    """清除測試時建立的 NotebookLM 筆記本"""
    from app.services.notebooklm_sync import NotebookLMSyncService

    service = NotebookLMSyncService()

    launched = await service._launch_browser()
    if not launched:
        print("❌ 無法連接到 Chrome CDP，請先執行 scripts/start_chrome_cdp.bat")
        return

    try:
        page = await service._context.new_page()

        logged_in = await service._verify_login(page)
        if not logged_in:
            print("❌ Google 尚未登入，請在 CDP Chrome 中登入 Google 帳號")
            return

        print("✅ 登入成功，正在掃描筆記本...")
        await page.wait_for_timeout(5000)

        deleted_count = 0

        # 重複刪除直到沒有匹配項
        for _round in range(20):
            # 找到要刪除的筆記本卡片
            target_index = await page.evaluate(
                """(titles) => {
                    const cards = document.querySelectorAll(
                        'mat-card, [class*="notebook"], [class*="card"]'
                    );
                    for (let i = 0; i < cards.length; i++) {
                        const titleEl = cards[i].querySelector('.project-button-title');
                        if (!titleEl) continue;
                        const title = titleEl.textContent.trim();
                        for (const t of titles) {
                            if (title === t || title.includes(t)) {
                                return i;
                            }
                        }
                    }
                    return -1;
                }""",
                TITLES_TO_DELETE,
            )

            if target_index < 0:
                break

            # 取得標題名（便於 log）
            target_title = await page.evaluate(
                """(idx) => {
                    const cards = document.querySelectorAll(
                        'mat-card, [class*="notebook"], [class*="card"]'
                    );
                    const titleEl = cards[idx]?.querySelector('.project-button-title');
                    return titleEl ? titleEl.textContent.trim() : '(unknown)';
                }""",
                target_index,
            )
            print(f"🗑️  正在刪除: {target_title}")

            # 點擊該筆記本卡片內的「專案動作選單」按鈕
            clicked_menu = await page.evaluate(
                """(idx) => {
                    const cards = document.querySelectorAll(
                        'mat-card, [class*="notebook"], [class*="card"]'
                    );
                    const card = cards[idx];
                    if (!card) return false;
                    const menuBtn = card.querySelector(
                        'button[aria-label="專案動作選單"]'
                    );
                    if (!menuBtn) return false;
                    menuBtn.click();
                    return true;
                }""",
                target_index,
            )

            if not clicked_menu:
                print(f"  ⚠️ 找不到選單按鈕，跳過")
                break

            await page.wait_for_timeout(1500)

            # 點擊選單中的「移至垃圾桶」/「刪除」選項
            delete_btn = page.locator(
                'button:has-text("移至垃圾桶"), '
                'button:has-text("刪除"), '
                'button:has-text("Delete"), '
                'button:has-text("Move to Trash")'
            )

            if await delete_btn.count() > 0:
                await delete_btn.first.click(force=True)
                await page.wait_for_timeout(1500)

                # 可能有確認對話框 — 使用 JS 點擊避免 CDK overlay 攔截
                confirmed = await page.evaluate("""() => {
                    // 尋找確認按鈕
                    const selectors = [
                        'button[aria-label="確認刪除"]',
                        'button:has(.mdc-button__label)',
                    ];
                    for (const sel of selectors) {
                        const btns = document.querySelectorAll(sel);
                        for (const btn of btns) {
                            const text = btn.textContent.trim();
                            if (text.includes('移至垃圾桶') || text.includes('刪除') ||
                                text.includes('Delete') || text.includes('確認')) {
                                btn.click();
                                return text;
                            }
                        }
                    }
                    return null;
                }""")
                if confirmed:
                    await page.wait_for_timeout(2000)
                    print(f"  ✅ 已確認刪除 ('{confirmed}')")
                else:
                    await page.wait_for_timeout(1000)

                deleted_count += 1
                print(f"  ✅ 已刪除: {target_title}")
            else:
                # 列出選單中有哪些選項
                menu_items = await page.evaluate("""() => {
                    const items = document.querySelectorAll(
                        '[role="menuitem"], [role="option"], .mat-mdc-menu-item'
                    );
                    return Array.from(items).map(i => i.textContent.trim().substring(0, 60));
                }""")
                print(f"  ⚠️ 選單中找不到刪除選項。可用選項: {menu_items}")
                # 按 Escape 關閉選單
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(500)
                break

            # 等待頁面更新
            await page.wait_for_timeout(2000)

        print(f"\n🎉 清除完成！共刪除 {deleted_count} 個測試筆記本")

        # 截圖最終狀態
        await page.screenshot(path="temp_videos/notebooklm_after_cleanup.png")
        print("📸 已截圖到 temp_videos/notebooklm_after_cleanup.png")

        await page.close()

    finally:
        await service._close_browser()

    # 清除 DB 中的測試記錄
    from app.database.models import init_db

    await init_db()

    import aiosqlite

    db_path = Path("data/instagram_reels.db")
    if db_path.exists():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("DELETE FROM notebooklm_notebooks")
            await db.commit()
        print("🗄️  已清除 DB 中的 NotebookLM 記錄")


if __name__ == "__main__":
    asyncio.run(cleanup_notebooks())
