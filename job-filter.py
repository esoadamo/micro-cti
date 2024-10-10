import asyncio

from db import get_db
from posts import hide_post_if_not_about_cybersecurity


async def main() -> None:
    db = await get_db()
    for post in await db.post.find_many(where={'is_hidden': False}):
        print('[?]', post.content_txt)
        if not await hide_post_if_not_about_cybersecurity(post):
            print('[HIDDEN]', post.content_txt)
        else:
            print('[KEEP]', post.content_txt)


if __name__ == "__main__":
    asyncio.run(main())
