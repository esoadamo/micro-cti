import asyncio
import traceback

from prisma.models import Post

from db import get_db
from posts import generate_tags, get_mastodon_posts, get_airtable_posts, get_bluesky_posts, get_rss_posts, FetchError


def print_post(post: Post):
    content = post.content_txt.replace("\n", " ")
    print(f'[-]{"[-]" if post.is_hidden else "[+]"} {content} - {post.user}@{post.source}')


async def main() -> int:
    exceptions = []
    print('[*] Fetching started')
    db = await get_db()

    try:
        async for post in get_rss_posts():
            print_post(post)
        print('[*] RSS fetched')
    except FetchError as e:
        print(f'[!] RSS fetch failed: {e}')
        exceptions.append(e)
        exceptions.extend(e.source)

    try:
        async for post in get_bluesky_posts():
            print_post(post)
        print('[*] Bluesky fetched')
    except FetchError as e:
        print(f'[!] Bluesky fetch failed: {e}')
        exceptions.append(e)
        exceptions.extend(e.source)

    try:
        async for post in get_airtable_posts():
            print_post(post)
        print('[*] Airtable fetched')
    except FetchError as e:
        print(f'[!] Airtable fetch failed: {e}')
        exceptions.append(e)
        exceptions.extend(e.source)

    try:
        async for post in get_mastodon_posts():
            print_post(post)
        print('[*] Mastodon fetched')
    except FetchError as e:
        print(f'[!] Mastodon fetch failed: {e}')
        exceptions.append(e)
        exceptions.extend(e.source)

    try:
        await generate_tags()
        print('[*] Tags generated')
    except FetchError as e:
        print(f'[!] Tag generation failed: {e}')
        exceptions.append(e)
        exceptions.extend(e.source)

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
