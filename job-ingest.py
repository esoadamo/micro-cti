import asyncio
import traceback
from collections.abc import Callable
from typing import List, AsyncIterable

from prisma.models import Post

from db import get_db
from posts import generate_tags, get_mastodon_posts, get_airtable_posts, get_bluesky_posts, get_rss_posts, FetchError


def print_post(post: Post):
    content = post.content_txt.replace("\n", " ")
    print(f'[-]{"[-]" if post.is_hidden else "[+]"} {content} - {post.user}@{post.source}')


async def fetch_posts(prefix: str, function: Callable[[], AsyncIterable[Post]]) -> List[Exception]:
    exceptions: List[Exception] = []
    post_ids: List[int] = []
    try:
        async for post in function():
            print_post(post)
            post_ids.append(post.id)
        print(f'[*] {prefix} fetched')
    except FetchError as e:
        print(f'[!] {prefix} fetch failed: {e}')
        exceptions.append(e)
        exceptions.extend(e.source)

    print(f'[*] {prefix} Bluesky tags')
    await generate_tags(post_ids)
    print(f'[*] {prefix} tags generated')

    return exceptions


async def main() -> int:
    print('[*] Fetching started')
    db = await get_db()

    exceptions = await asyncio.gather(
        fetch_posts('RSS', get_rss_posts),
        fetch_posts('Mastodon', get_mastodon_posts),
        fetch_posts('Airtable', get_airtable_posts),
        fetch_posts('Bluesky', get_bluesky_posts),
        return_exceptions=True
    )

    print('[*] Fetching finished')
    print('[*] Generating tags for all posts')
    await generate_tags()
    print('[*] Tags generated')

    await db.disconnect()
    if exceptions:
        print('[!] Some errors were encountered:')
        for i, e in enumerate(exceptions):
            print(f'[!{i + 1}/{len(exceptions)}] ERROR', e)
            traceback.print_exception(type(e), e, e.__traceback__)
        return 1
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
