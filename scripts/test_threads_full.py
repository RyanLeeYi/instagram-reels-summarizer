"""Test script: Full Threads pipeline (Download → Analyze → Summarize → NLM → Roam)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.threads_downloader import ThreadsDownloader
from app.services.visual_analyzer import VideoVisualAnalyzer
from app.services.copilot_summarizer import CopilotCLISummarizer
from app.services.notebooklm_sync import NotebookLMSyncService
from app.services.roam_sync import RoamSyncService


async def main():
    url = "https://www.threads.com/@chihua.wang.3/post/DU6uFvFASyx"
    downloader = ThreadsDownloader()
    visual_analyzer = VideoVisualAnalyzer()
    summarizer = CopilotCLISummarizer()
    nlm = NotebookLMSyncService()
    roam = RoamSyncService()

    # Step 1: Download
    print("=" * 60)
    print("Step 1: Download Threads post")
    print("=" * 60)
    result = await downloader.download(url)
    if not result.success:
        print(f"FAIL: {result.error_message}")
        return

    post = result.post
    author = post.author_username if post else "unknown"
    all_media = downloader.get_all_media(result)
    print(f"Author: @{author}")
    print(f"Text: {len(post.text_content)} chars")
    print(f"Media: {len(all_media)} items")
    for i, m in enumerate(all_media):
        print(f"  [{i}] {m.media_type}: {m.url[:80]}...")

    # Step 2: Download & analyze media
    print("\n" + "=" * 60)
    print("Step 2: Download & analyze media")
    print("=" * 60)
    visual_description = None
    media_download_result = None

    if all_media:
        media_download_result = await downloader.download_media(all_media)
        if media_download_result.success:
            print(f"Images: {len(media_download_result.image_paths)}")
            print(f"Videos: {len(media_download_result.video_paths)}")

            if media_download_result.image_paths:
                print("Analyzing images...")
                img_result = await visual_analyzer.analyze_images(
                    media_download_result.image_paths
                )
                if img_result.success and img_result.overall_visual_summary:
                    visual_description = "【圖片內容】\n" + img_result.overall_visual_summary
                    print(f"Visual summary: {len(visual_description)} chars")
                    print(visual_description[:200] + "...")
                else:
                    print(f"Image analysis failed: {img_result.error_message}")
        else:
            print(f"Media download failed: {media_download_result.error_message}")
    else:
        print("No media to download")

    # Step 3: Summarize
    print("\n" + "=" * 60)
    print("Step 3: Generate note")
    print("=" * 60)
    formatted_content = downloader.format_for_summary(result)
    note_result = await summarizer.generate_threads_note(
        url=url,
        author=author,
        content=formatted_content,
        visual_description=visual_description,
    )
    if not note_result.success:
        print(f"FAIL: {note_result.error_message}")
        return
    print(f"Summary: {note_result.summary[:100]}...")
    print(f"Markdown: {len(note_result.markdown_content)} chars")

    # Step 4: Upload to NotebookLM
    print("\n" + "=" * 60)
    print("Step 4: Upload to NotebookLM")
    print("=" * 60)
    media_paths = []
    if media_download_result:
        media_paths.extend(media_download_result.image_paths or [])
        media_paths.extend(media_download_result.video_paths or [])
    nlm_result = await nlm.upload_threads(
        markdown_content=note_result.markdown_content,
        media_paths=media_paths if media_paths else None,
        title=f"@{author}",
    )
    print(f"NLM success: {nlm_result.success}")
    if not nlm_result.success:
        print(f"NLM error: {nlm_result.error_message}")

    # Step 5: Save to Roam
    print("\n" + "=" * 60)
    print("Step 5: Save to Roam")
    print("=" * 60)
    roam_result = await roam.save_threads_note(
        author=author,
        markdown_content=note_result.markdown_content,
        original_url=url,
    )
    print(f"Roam success: {roam_result.success}")
    if roam_result.success:
        print(f"Roam page: {roam_result.page_title}")
    else:
        print(f"Roam error: {roam_result.error_message}")

    # Cleanup
    if media_download_result:
        downloader.cleanup_media(media_download_result)

    print("\n" + "=" * 60)
    print("DONE - Full pipeline completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
