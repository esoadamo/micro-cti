import asyncio

from db import get_db
from posts import generate_tags


async def main() -> int:
    print('[*] Fetching started')
    db = await get_db()

    print('[*] Generating tags for all posts')
    await generate_tags()
    print('[*] Tags generated')
    await db.disconnect()

    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
