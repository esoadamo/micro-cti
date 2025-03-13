import asyncio

from db import get_db
from posts import generate_tags, ingest_posts


async def main() -> int:
    print('[*] Fetching started')
    db = await get_db()

    print('[*] Ingesting all posts')
    await ingest_posts()
    print('[*] Generating tags for all posts')
    await generate_tags()
    print('[*] Tags generated')
    await db.disconnect()

    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
