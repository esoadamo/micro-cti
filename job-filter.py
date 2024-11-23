import asyncio

from db import get_db
from posts import hide_post_if_not_about_cybersecurity


async def main() -> None:
    db = await get_db()
    posts = await db.post.find_many(where={'is_hidden': False})
    for i, post in enumerate(posts):
        print(f'[*] {i+1}/{len(posts)}', post.content_txt)
        if not await hide_post_if_not_about_cybersecurity(post, force_ai=True):
            print('[HIDDEN]', post.content_txt)
        else:
            print('[KEEP]', post.content_txt)
    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
