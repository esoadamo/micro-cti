import asyncio

from db import DBConnector
from post import hide_post_if_not_about_cybersecurity
from sqlmodel import select
from models import Post


async def main() -> None:
    async with DBConnector.get() as db:
        stmt = select(Post).where(Post.is_hidden == False)
        res = await db.exec(stmt)
        posts = res.all()
        for i, post in enumerate(posts):
            print(f'[*] {i + 1}/{len(posts)}', post.content_txt)
            if not await hide_post_if_not_about_cybersecurity(post, db, force_ai=True):
                print('[HIDDEN]', post.content_txt)
            else:
                print('[KEEP]', post.content_txt)

if __name__ == "__main__":
    asyncio.run(main())
