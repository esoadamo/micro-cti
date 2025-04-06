import asyncio
import traceback
from itertools import chain
from collections.abc import Callable
from typing import List, AsyncIterable

from prisma.models import Post

from db import get_db
from posts import generate_tags, get_mastodon_posts, get_airtable_posts, get_bluesky_posts, get_rss_posts, FetchError, \
    get_telegram_posts, ingest_posts


def print_post(post: Post):
    content = post.content_txt.replace("\n", " ")
    print(f'[-]{"[-]" if post.is_hidden else "[+]"} {content} - {post.user}@{post.source}')


async def fetch_posts(prefix: str, function: Callable[[], AsyncIterable[Post]]) -> List[Exception]:
    exceptions: List[Exception] = []
    post_ids: List[int] = []
    print(f'[*] {prefix} fetching')
    try:
        async for post in function():
            print_post(post)
            post_ids.append(post.id)
        print(f'[*] {prefix} fetched')
    except Exception as e:
        print(f'[!] {prefix} fetch failed: {e}')
        exceptions.append(e)
        if isinstance(e, FetchError):
            exceptions.extend(e.source)

    try:
        print(f'[*] {prefix} ingesting posts')
        await ingest_posts(post_ids)
    except Exception as e:
        print(f'[!] {prefix} ingestion failed: {e}')
        exceptions.append(e)

    try:
        print(f'[*] {prefix} generating tags')
        await generate_tags(post_ids)
        print(f'[*] {prefix} tags generated')
    except Exception as e:
        print(f'[!] {prefix} tag generation failed: {e}')
        exceptions.append(e)

    return exceptions


async def main() -> int:
    print('[*] Fetching started')
    db = await get_db()

    exceptions_2d = await asyncio.gather(
        fetch_posts('Telegram', get_telegram_posts),
        fetch_posts('RSS', get_rss_posts),
        fetch_posts('Mastodon', get_mastodon_posts),
        fetch_posts('Airtable', get_airtable_posts),
        fetch_posts('Bluesky', get_bluesky_posts)
    )

    exceptions = list(chain(*exceptions_2d))
    print('[*] Fetching finished')

    await db.disconnect()
    print('[*] Database disconnected')
    if exceptions:
        print('[!] Some errors were encountered:')
        for i, e in enumerate(exceptions):
            print(f'[!{i + 1}/{len(exceptions)}] ERROR', e)
            traceback.print_exception(type(e), e, e.__traceback__)
        return 1
    print('[*] No errors encoutered, exiting')
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
