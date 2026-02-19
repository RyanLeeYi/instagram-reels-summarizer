"""Test Googlebot SSR thread download end-to-end"""
import asyncio
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

sys.path.insert(0, ".")

from app.services.threads_downloader import ThreadsDownloader


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.threads.net/@chihua.wang.3/post/DU6uFvFASyx"

    downloader = ThreadsDownloader()

    print(f"\n{'='*60}")
    print(f"Testing Googlebot SSR: {url}")
    print(f"{'='*60}")

    # Test 1: Direct Googlebot SSR method
    print("\n--- Test 1: _download_via_googlebot_ssr ---")
    result = downloader._download_via_googlebot_ssr(url)

    if result is None:
        print("Result: None (method failed)")
        return

    print(f"Success: {result.success}")
    print(f"Content type: {result.content_type}")

    if result.content_type == "single_post" and result.post:
        post = result.post
        print(f"Author: @{post.author_username}")
        print(f"Text (first 200): {post.text_content[:200]}")
        print(f"Media count: {len(post.media)}")
        for m in post.media[:3]:
            print(f"  - {m.media_type}: {m.url[:80]}...")
        print(f"Likes: {post.like_count}, Replies: {post.reply_count}")

    elif result.content_type == "thread" and result.thread_posts:
        print(f"Thread posts: {len(result.thread_posts)}")
        for i, post in enumerate(result.thread_posts):
            print(f"\n  --- Thread post {i+1}/{len(result.thread_posts)} ---")
            print(f"  Author: @{post.author_username}")
            print(f"  Text (first 150): {post.text_content[:150]}")
            print(f"  Media count: {len(post.media)}")
            for m in post.media[:2]:
                print(f"    - {m.media_type}: {m.url[:60]}...")

    # Test 2: format_for_summary
    print(f"\n--- Test 2: format_for_summary ---")
    formatted = downloader.format_for_summary(result)
    print(f"Formatted length: {len(formatted)} chars")
    print(f"First 500 chars:\n{formatted[:500]}")

    # Test 3: get_all_media
    print(f"\n--- Test 3: get_all_media ---")
    all_media = downloader.get_all_media(result)
    print(f"Total media: {len(all_media)}")
    for i, m in enumerate(all_media[:5]):
        print(f"  {i+1}. {m.media_type}: {m.url[:60]}...")

    # Test 4: Full download flow (same as would happen in production)
    print(f"\n--- Test 4: Full download() flow ---")
    full_result = await downloader.download(url)
    print(f"Success: {full_result.success}")
    print(f"Content type: {full_result.content_type}")
    if full_result.content_type == "thread":
        print(f"Thread posts: {len(full_result.thread_posts)}")
    elif full_result.content_type == "single_post" and full_result.post:
        print(f"Single post: @{full_result.post.author_username}")
    elif full_result.error_message:
        print(f"Error: {full_result.error_message}")

    print(f"\n{'='*60}")
    print("All tests completed!")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
