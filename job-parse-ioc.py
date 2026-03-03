import asyncio
import traceback

from db import DBConnector
from ioc import parse_iocs
from sqlmodel import select
from models import Post


async def main() -> None:
    async with (await DBConnector().get()) as db:
        step = 1000
        curr_id = 0
        while True:
            stmt = select(Post).where(Post.is_hidden == False, ~Post.iocs.any(), Post.id > curr_id).order_by(Post.id).limit(step)
            res = await db.exec(stmt)
            posts = res.all()
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
