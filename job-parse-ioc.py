import asyncio
import traceback

from db import DBConnector
from ioc import parse_iocs


async def main() -> None:
    async with (await DBConnector().get()) as db:
        step = 1000
        curr_id = 0
        while True:
            posts = await db.post.find_many(
                where={
                    'is_hidden': False,
                    'iocs': {'none': {}},
                    'id': {'gt': curr_id},
                },
                take=step,
                order={'id': 'asc'},
            )
            print(f"[*] Fetched {len(posts)} posts without IoCs starting from id > {curr_id}")
            if not posts:
                break
            curr_id = posts[-1].id
            for i, post in enumerate(posts):
                print(f'[*] {i + 1}/{len(posts)}', post.content_txt)
                try:
                    async for ioc in parse_iocs(db, [post.id]):
                        print(f'  [+] {ioc}')
                except Exception as e:
                    print(f'  [!] Error parsing IoCs: {e}')
                    traceback.print_exception(type(e), e, e.__traceback__)


if __name__ == "__main__":
    asyncio.run(main())
