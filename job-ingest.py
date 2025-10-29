import asyncio
import sys
import traceback
from itertools import chain
from collections.abc import Callable
from typing import List, AsyncIterable

from prisma import Prisma
from prisma.models import Post

from db import DBConnector
from post import generate_tags, get_mastodon_posts, get_airtable_posts, get_bluesky_posts, get_rss_posts, FetchError, \
    get_telegram_posts, get_baserow_posts, ingest_posts
from ioc import parse_iocs


def print_post(post: Post):
    content = post.content_txt.replace("\n", " ")
    print(f'[-]{"[-]" if post.is_hidden else "[+]"} {content} - {post.user}@{post.source}')


async def fetch_posts(prefix: str, function: Callable[[Prisma], AsyncIterable[Post]], db: Prisma) -> List[Exception]:
    exceptions: List[Exception] = []
    post_ids: List[int] = []
    print(f'[*] {prefix} fetching')
    try:
        async for post in function(db):
            print_post(post)
            post_ids.append(post.id)
        print(f'[*] {prefix} fetched')
    except Exception as e:
        print(f'[!] {prefix} fetch failed: {e}')
        exceptions.append(e)

    try:
        print(f'[*] {prefix} ingesting posts')
        await ingest_posts(db, post_ids)
    except Exception as e:
        print(f'[!] {prefix} ingestion failed: {e}')
        exceptions.append(e)

    try:
        print(f'[*] {prefix} generating tags')
        await generate_tags(db, post_ids)
        print(f'[*] {prefix} tags generated')
    except Exception as e:
        print(f'[!] {prefix} tag generation failed: {e}')
        exceptions.append(e)

    try:
        print(f'[*] {prefix} parsing IoCs')
        await parse_iocs(db, post_ids)
        print(f'[*] {prefix} IoCs parsed')
    except Exception as e:
        print(f'[!] {prefix} IoC parsing failed: {e}')
        exceptions.append(e)

    if exceptions:
        print(f'[!] {prefix} completed with errors')
    else:
        print(f'[*] {prefix} completed successfully')

    return exceptions


async def main() -> int:
    exceptions = []

    if '--no-fetch' in sys.argv:
        print('[*] Ingesting uningested posts')
        async with DBConnector() as db:
            try:
                await ingest_posts(db)
                print('[*] Ingesting posts successfully')
            except Exception as e:
                print('[!] Error ingesting posts')
                exceptions.append(e)
            print('[*] Generating tags for untagged posts')
            try:
                await generate_tags(db)
                print('[*] Generating tags successfully')
            except Exception as e:
                print('[!] Error generating tags')
                exceptions.append(e)
            print('[*] Parsing IoCs for unprocessed posts')
            try:
                await parse_iocs(db)
                print('[*] Parsing IoCs for processed posts successfully')
            except Exception as e:
                print('[!] Error parsing IoCs')
                exceptions.append(e)
        print('[*] All done')
    else:
        print('[*] Fetching started')
        async with (await DBConnector.get()) as db:
            exceptions_2d = await asyncio.gather(
                fetch_posts('Telegram', get_telegram_posts, db),
                fetch_posts('RSS', get_rss_posts, db),
                fetch_posts('Mastodon', get_mastodon_posts, db),
                fetch_posts('Airtable', get_airtable_posts, db),
                fetch_posts('Baserow', get_baserow_posts, db),
                fetch_posts('Bluesky', get_bluesky_posts, db)
            )
        exceptions = list(chain(*exceptions_2d))
        print('[*] Fetching finished')

    if exceptions:
        print('[!] Some errors were encountered:')
        while exceptions:
            e = exceptions.pop(0)
            if isinstance(e, FetchError):
                exceptions = e.source + exceptions
            print(f'[!] ERROR', e)
            traceback.print_exception(type(e), e, e.__traceback__, file=sys.stdout)
        return 1
    print('[*] No errors encoutered, exiting')
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
