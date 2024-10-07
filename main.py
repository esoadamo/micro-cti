import asyncio

from posts import generate_tags, get_mastodon_posts, generate_random_color


async def main() -> None:
    posts = get_mastodon_posts()
    async for _ in posts:
        pass
    await generate_tags()


if __name__ == "__main__":
    asyncio.run(main())
