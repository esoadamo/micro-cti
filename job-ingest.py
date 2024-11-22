import asyncio
import traceback
from typing import List

from prisma.models import Post

from db import get_db
from posts import generate_tags, get_mastodon_posts, get_airtable_posts, get_bluesky_posts, get_rss_posts, FetchError


def print_post(post: Post):
    content = post.content_txt.replace("\n", " ")
    print(f'[-]{"[-]" if post.is_hidden else "[+]"} {content} - {post.user}@{post.source}')


async def fetch_bluesky_posts() -> List[Exception]:
    exceptions: List[Exception] = []
    post_ids: List[int] = []
    try:
        async for post in get_bluesky_posts():
            print_post(post)
            post_ids.append(post.id)
        print('[*] Bluesky fetched')
    except FetchError as e:
        print(f'[!] Bluesky fetch failed: {e}')
        exceptions.append(e)
        exceptions.extend(e.source)

    print('[*] Generating Bluesky tags')
    await generate_tags(post_ids)
    print('[*] Bluesky tags generated')

    return exceptions


async def fetch_airtable_posts() -> List[Exception]:
    exceptions: List[Exception] = []
    post_ids: List[int] = []
    try:
        async for post in get_airtable_posts():
            print_post(post)
            post_ids.append(post.id)
        print('[*] Airtable fetched')
    except FetchError as e:
        print(f'[!] Airtable fetch failed: {e}')
        exceptions.append(e)
        exceptions.extend(e.source)

    print('[*] Generating Airtable tags')
    await generate_tags(post_ids)
    print('[*] Airtable tags generated')

    return exceptions


async def fetch_mastodon_posts() -> List[Exception]:
    exceptions: List[Exception] = []
    post_ids: List[int] = []
    try:
        async for post in get_mastodon_posts():
            print_post(post)
            post_ids.append(post.id)
        print('[*] Mastodon fetched')
    except FetchError as e:
        print(f'[!] Mastodon fetch failed: {e}')
        exceptions.append(e)
        exceptions.extend(e.source)

    print('[*] Generating Mastodon tags')
    await generate_tags(post_ids)
    print('[*] Mastodon tags generated')

    return exceptions


async def fetch_rss_posts() -> List[Exception]:
    exceptions: List[Exception] = []
    try:
        async for post in get_rss_posts():
            print_post(post)
        print('[*] RSS fetched')
    except FetchError as e:
        print(f'[!] RSS fetch failed: {e}')
        exceptions.append(e)
        exceptions.extend(e.source)
    return exceptions


async def main() -> int:
    print('[*] Fetching started')
    db = await get_db()

    exceptions = await asyncio.gather(
        fetch_bluesky_posts(),
        fetch_airtable_posts(),
        fetch_mastodon_posts(),
        fetch_rss_posts(),
        return_exceptions=True
    )

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
