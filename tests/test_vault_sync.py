"""F14：摘要整併知識庫（vault_sync）。規格見 docs/prd/vault-sync.md。"""
from pathlib import Path

import pytest

from app.services.vault_sync import VaultSyncService

SAMPLE_MD = """# 測試筆記

## 摘要

這是一段測試摘要的第一行。
第二行不該進 summary。

## 重點整理

- 重點一
"""


@pytest.fixture
def vault(tmp_path):
    """最小假 vault：clippings 兩子資料夾 + INDEX + 三份來源 INDEX。"""
    (tmp_path / "clippings" / "ig-reels").mkdir(parents=True)
    (tmp_path / "clippings" / "threads").mkdir(parents=True)
    (tmp_path / "clippings" / "INDEX.md").write_text(
        "---\nupdated: 2026-07-06\ntags: [index, clippings]\nsummary: x\n---\n"
        "# clippings — INDEX\n\n"
        "- articles/舊文章 (highlights).md\n"
        "- ig-reels/IG Reels - 2026-02-23 090039 - Video by old.md\n"
        "- threads/Threads - 2026-02-21 132725 - @boris_cherny.md\n",
        encoding="utf-8",
    )
    for folder in ("knowledge", "learning", "projects"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "INDEX.md").write_text(
            f"# {folder} INDEX\n- 某筆記.md — 描述\n", encoding="utf-8"
        )
    (tmp_path / "assets").mkdir()
    return tmp_path


def make_service(vault, enrich=False, run_llm=None):
    return VaultSyncService(vault_path=vault, link_enrich=enrich, run_llm=run_llm)


class TestSaveReel:
    @pytest.mark.asyncio
    async def test_writes_note_with_frontmatter_and_naming(self, vault):
        svc = make_service(vault)
        r = await svc.upload_reel(SAMPLE_MD, title="Video by tester",
                                  source_url="https://www.instagram.com/reel/ABC")
        assert r.success
        note = Path(r.note_path)
        assert note.parent == vault / "clippings" / "ig-reels"
        assert note.name.startswith("IG Reels - ") and note.name.endswith(" - Video by tester.md")
        text = note.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "tags: [clipping, ig-reels]" in text
        assert "summary: 這是一段測試摘要的第一行。" in text
        assert "source: https://www.instagram.com/reel/ABC" in text
        assert "## 重點整理" in text  # 本體原樣保留

    @pytest.mark.asyncio
    async def test_appends_index_entry_in_group(self, vault):
        svc = make_service(vault)
        r = await svc.upload_reel(SAMPLE_MD, title="Video by tester", source_url="u")
        index = (vault / "clippings" / "INDEX.md").read_text(encoding="utf-8")
        lines = index.splitlines()
        new_line = next(line for line in lines if "Video by tester" in line)
        assert new_line.startswith("- ig-reels/")
        assert " — " in new_line
        # 插在 ig-reels 組尾：舊 ig-reels 條目之後、threads 條目之前
        assert lines.index(new_line) == lines.index(
            "- ig-reels/IG Reels - 2026-02-23 090039 - Video by old.md") + 1
        # INDEX frontmatter 日期有更新
        assert "updated: 2026-07-06" not in index

    @pytest.mark.asyncio
    async def test_vault_missing_returns_failure_not_raise(self, tmp_path):
        svc = VaultSyncService(vault_path=tmp_path / "no-such-vault", link_enrich=False)
        r = await svc.upload_reel(SAMPLE_MD, title="x", source_url="u")
        assert r.success is False
        assert r.error_message


class TestSavePostImages:
    @pytest.mark.asyncio
    async def test_images_copied_by_hash_and_linked(self, vault, tmp_path):
        img = tmp_path / "img_01.jpg"
        img.write_bytes(b"fake-jpeg-data")
        svc = make_service(vault)
        r = await svc.upload_post(SAMPLE_MD, image_paths=[img], title="Post by tester",
                                  source_url="https://www.instagram.com/p/XYZ")
        assert r.success
        copies = list((vault / "assets" / "clippings").glob("*.jpg"))
        assert len(copies) == 1
        assert len(copies[0].stem) == 12  # sha256 前 12 碼
        text = Path(r.note_path).read_text(encoding="utf-8")
        assert f"![](../../assets/clippings/{copies[0].name})" in text

    @pytest.mark.asyncio
    async def test_missing_image_skipped_note_still_written(self, vault, tmp_path):
        svc = make_service(vault)
        r = await svc.upload_post(SAMPLE_MD, image_paths=[tmp_path / "ghost.jpg"],
                                  title="Post by tester", source_url="u")
        assert r.success
        assert not list((vault / "assets" / "clippings").glob("*"))


class TestSaveThreads:
    @pytest.mark.asyncio
    async def test_threads_naming_and_folder(self, vault):
        svc = make_service(vault)
        r = await svc.upload_threads(SAMPLE_MD, title="@some_author",
                                     source_url="https://www.threads.com/@some_author/post/A")
        note = Path(r.note_path)
        assert note.parent == vault / "clippings" / "threads"
        assert " - @some_author.md" in note.name  # @ 要保留


class TestLinkEnrich:
    @pytest.mark.asyncio
    async def test_valid_llm_output_appended(self, vault):
        async def fake_llm(prompt):
            assert "knowledge" in prompt  # INDEX 有餵進去
            return "- [[某筆記]] — 主題相關\n- [[另一筆記]] — 技術重疊"

        svc = make_service(vault, enrich=True, run_llm=fake_llm)
        r = await svc.upload_reel(SAMPLE_MD, title="t", source_url="u")
        text = Path(r.note_path).read_text(encoding="utf-8")
        assert "## 相關筆記" in text
        assert "- [[某筆記]] — 主題相關" in text

    @pytest.mark.asyncio
    async def test_none_output_no_section(self, vault):
        async def fake_llm(prompt):
            return "NONE"

        svc = make_service(vault, enrich=True, run_llm=fake_llm)
        r = await svc.upload_reel(SAMPLE_MD, title="t", source_url="u")
        assert "## 相關筆記" not in Path(r.note_path).read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_garbage_output_filtered(self, vault):
        async def fake_llm(prompt):
            return "好的，以下是相關筆記：\n- [[真連結]] — ok\n順帶一提我覺得..."

        svc = make_service(vault, enrich=True, run_llm=fake_llm)
        r = await svc.upload_reel(SAMPLE_MD, title="t", source_url="u")
        text = Path(r.note_path).read_text(encoding="utf-8")
        assert "- [[真連結]] — ok" in text
        assert "好的" not in text
        assert "順帶一提" not in text

    @pytest.mark.asyncio
    async def test_llm_failure_note_survives(self, vault):
        async def fake_llm(prompt):
            raise RuntimeError("CLI 掛了")

        svc = make_service(vault, enrich=True, run_llm=fake_llm)
        r = await svc.upload_reel(SAMPLE_MD, title="t", source_url="u")
        assert r.success  # 筆記照樣落地
        assert Path(r.note_path).exists()
