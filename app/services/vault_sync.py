"""摘要整併知識庫（F14，取代 NotebookLM）。規格：docs/prd/vault-sync.md。

寫入 Obsidian vault 的 clippings/，圖片進 assets/clippings/（hash 檔名），
同步 clippings/INDEX.md（vault 強制規則 #1），可選 LLM 連結 pass
（LLM 只產文字、Python 驗證後才寫入，LLM 永遠不直接改檔）。
"""

import asyncio
import hashlib
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# 可注入的 LLM 呼叫（prompt -> 回覆文字），predictable 測試用
RunLLM = Callable[[str], Awaitable[str]]

INDEX_SOURCES = ("knowledge", "learning", "projects")
LINK_LINE = re.compile(r"^- \[\[.+\]\]")

LINK_PROMPT = """你是知識庫的連結整理員。以下是一篇新收錄的摘要筆記，以及知識庫三個資料夾的索引。
任務：從索引中找出與這篇筆記「語義相關」的既有筆記，輸出 0 到 5 行，每行格式嚴格為：
- [[筆記檔名不含副檔名]] — 一句話說明為什麼相關

規則：
1. 只輸出上述格式的行，不要任何其他文字、開場白、說明
2. 沒有真正相關的就只輸出一行：NONE
3. 寧缺勿濫——主題確實重疊才算相關

=== 新筆記 ===
{note}

=== 知識庫索引 ===
{indexes}
"""


@dataclass
class VaultSyncResult:
    """vault 寫入結果（介面形狀對齊 NotebookLMResult）"""

    success: bool
    note_path: Optional[str] = None
    note_name: Optional[str] = None
    error_message: Optional[str] = None


class VaultSyncService:
    """把摘要寫進 Obsidian vault 並維護 INDEX 與連結。"""

    def __init__(
        self,
        vault_path: Optional[Path] = None,
        link_enrich: Optional[bool] = None,
        run_llm: Optional[RunLLM] = None,
    ):
        self.vault_path = Path(vault_path or settings.vault_path)
        self.link_enrich = settings.vault_link_enrich if link_enrich is None else link_enrich
        self._run_llm = run_llm or self._run_claude_cli

    # ---------- 公開入口（對齊 NotebookLMSyncService 的三個 upload_*） ----------

    async def upload_reel(
        self, markdown_content: str, title: str = "",
        source_url: str = "", video_path: Optional[Path] = None,
    ) -> VaultSyncResult:
        """Reel 摘要入庫（影片一律不進 vault）。"""
        return await self._save("ig-reels", "IG Reels", title, markdown_content, source_url)

    async def upload_post(
        self, markdown_content: str, image_paths: Optional[List[Path]] = None,
        title: str = "", source_url: str = "",
    ) -> VaultSyncResult:
        """圖文貼文入庫，圖片 copy 進 assets/clippings/。"""
        return await self._save(
            "ig-reels", "IG Reels", title, markdown_content, source_url,
            image_paths=image_paths or [],
        )

    async def upload_threads(
        self, markdown_content: str, title: str = "",
        source_url: str = "", media_paths: Optional[List[Path]] = None,
    ) -> VaultSyncResult:
        """Threads 串文入庫（media 中僅圖片進 vault）。"""
        images = [p for p in (media_paths or []) if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
        return await self._save("threads", "Threads", title, markdown_content, source_url,
                                image_paths=images)

    # ---------- 核心流程 ----------

    async def _save(
        self, subfolder: str, prefix: str, title: str,
        markdown_content: str, source_url: str,
        image_paths: Optional[List[Path]] = None,
    ) -> VaultSyncResult:
        try:
            target_dir = self.vault_path / "clippings" / subfolder
            if not target_dir.is_dir():
                raise FileNotFoundError(f"vault clippings 目錄不存在: {target_dir}")

            filename = self._make_filename(prefix, title)
            note_path = target_dir / filename
            summary_line = self._extract_summary_line(markdown_content) or title

            body = markdown_content
            if image_paths:
                body += self._embed_images(image_paths)

            content = self._frontmatter(subfolder, summary_line, source_url) + body
            note_path.write_text(content, encoding="utf-8")
            logger.info(f"📚 已寫入知識庫: {note_path}")

            self._append_index(subfolder, filename, summary_line)

            if self.link_enrich:
                await self._enrich_links(note_path)

            return VaultSyncResult(success=True, note_path=str(note_path), note_name=filename)

        except Exception as e:
            logger.error(f"知識庫寫入失敗: {e}")
            return VaultSyncResult(success=False, error_message=str(e))

    @staticmethod
    def _make_filename(prefix: str, title: str) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H%M%S")
        clean = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_", "@", "."))
        clean = clean.strip()[:50] or "untitled"
        return f"{prefix} - {now} - {clean}.md"

    @staticmethod
    def _extract_summary_line(markdown_content: str) -> Optional[str]:
        """取「## 摘要」段第一個非空行當一句話描述。"""
        in_summary = False
        for line in markdown_content.splitlines():
            if re.match(r"^##\s*\**摘要\**\s*$", line.strip()):
                in_summary = True
                continue
            if in_summary:
                if line.strip().startswith("#"):
                    break
                text = line.strip().lstrip("-").strip()
                if text:
                    return text[:80]
        return None

    @staticmethod
    def _frontmatter(subfolder: str, summary_line: str, source_url: str) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return (
            "---\n"
            f"updated: {today}\n"
            f"tags: [clipping, {subfolder}]\n"
            f"summary: {summary_line}\n"
            f"source: {source_url}\n"
            "---\n\n"
        )

    def _embed_images(self, image_paths: List[Path]) -> str:
        """圖片 copy 到 assets/clippings/<sha256 前 12 碼>，回傳筆記的圖片段。"""
        assets_dir = self.vault_path / "assets" / "clippings"
        links = []
        for img in image_paths:
            if not img or not Path(img).exists():
                logger.warning(f"圖片不存在，略過: {img}")
                continue
            data = Path(img).read_bytes()
            name = hashlib.sha256(data).hexdigest()[:12] + Path(img).suffix.lower()
            assets_dir.mkdir(parents=True, exist_ok=True)
            dest = assets_dir / name
            if not dest.exists():
                shutil.copyfile(img, dest)
            links.append(f"![](../../assets/clippings/{name})")
        if not links:
            return ""
        return "\n\n## 圖片\n\n" + "\n\n".join(links) + "\n"

    def _append_index(self, subfolder: str, filename: str, summary_line: str) -> None:
        """clippings/INDEX.md：同組尾插入條目 + 更新 frontmatter 日期。"""
        index_path = self.vault_path / "clippings" / "INDEX.md"
        entry = f"- {subfolder}/{filename} — {summary_line}"
        if not index_path.exists():
            index_path.write_text(f"# clippings — INDEX\n\n{entry}\n", encoding="utf-8")
            return
        lines = index_path.read_text(encoding="utf-8").splitlines()
        group_prefix = f"- {subfolder}/"
        insert_at = max(
            (i for i, line in enumerate(lines) if line.startswith(group_prefix)),
            default=len(lines) - 1,
        ) + 1
        lines.insert(insert_at, entry)
        today = datetime.now().strftime("%Y-%m-%d")
        lines = [f"updated: {today}" if line.startswith("updated:") else line for line in lines]
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------- LLM 連結 pass ----------

    async def _enrich_links(self, note_path: Path) -> None:
        """失敗只 log，不影響已落地的筆記。"""
        try:
            note = note_path.read_text(encoding="utf-8")
            indexes = []
            for folder in INDEX_SOURCES:
                p = self.vault_path / folder / "INDEX.md"
                if p.exists():
                    indexes.append(f"--- {folder}/INDEX.md ---\n{p.read_text(encoding='utf-8')}")
            if not indexes:
                return
            reply = await self._run_llm(
                LINK_PROMPT.format(note=note[:6000], indexes="\n\n".join(indexes))
            )
            links = [line.strip() for line in reply.splitlines() if LINK_LINE.match(line.strip())]
            if not links:
                logger.info("連結 pass：無相關筆記")
                return
            note_path.write_text(
                note + "\n## 相關筆記\n\n" + "\n".join(links[:5]) + "\n", encoding="utf-8"
            )
            logger.info(f"連結 pass：加入 {len(links[:5])} 個 [[連結]]")
        except Exception as e:
            logger.warning(f"連結 pass 失敗（筆記不受影響）: {e}")

    async def _run_claude_cli(self, prompt: str) -> str:
        """headless claude -p，stdin 進 prompt、stdout 出結果（同 roam_sync 模式）。"""
        import platform
        import shutil as _shutil

        claude_path = _shutil.which("claude")
        if not claude_path and platform.system() == "Windows":
            npm_path = Path.home() / "AppData" / "Roaming" / "npm"
            for ext in (".cmd", ".ps1", ""):
                candidate = npm_path / f"claude{ext}"
                if candidate.exists():
                    claude_path = str(candidate)
                    break
        if not claude_path:
            raise FileNotFoundError("找不到 claude CLI")

        if platform.system() == "Windows":
            process = await asyncio.create_subprocess_shell(
                f'"{claude_path}" -p',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            process = await asyncio.create_subprocess_exec(
                claude_path, "-p",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        stdout, stderr = await process.communicate(input=prompt.encode("utf-8"))
        if process.returncode != 0:
            raise RuntimeError(f"claude CLI exit {process.returncode}: {stderr.decode('utf-8', errors='ignore')[:200]}")
        return stdout.decode("utf-8", errors="ignore")
