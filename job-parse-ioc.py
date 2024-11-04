import asyncio

from db import get_db
from ioc import parse_iocs


async def main() -> None:
    db = await get_db()
    posts = await db.post.find_many(where={'is_hidden': False})
    for i, post in enumerate(posts):
        print(f'[*] {i+1}/{len(posts)}', post.content_txt)
        async for ioc in parse_iocs(post):
            print(f'  [+] {ioc}')


if __name__ == "__main__":
    asyncio.run(main())
