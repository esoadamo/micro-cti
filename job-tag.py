import asyncio

from db import DBConnector
from post import generate_tags, ingest_posts


async def main() -> int:
    print('[*] Fetching started')

    async with (await DBConnector.get()) as db:
        print('[*] Ingesting all posts')
        precomputed_tags = {}
        await ingest_posts(db, precomputed_tags=precomputed_tags)
        print('[*] Generating tags for all posts')
        await generate_tags(db, precomputed_tags=precomputed_tags)
        print('[*] Tags generated')

    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
