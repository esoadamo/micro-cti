import asyncio

from posts import generate_tags, get_mastodon_posts, generate_random_color


async def main() -> None:
    async for _ in get_mastodon_posts():
        pass
    await generate_tags()


if __name__ == "__main__":
    asyncio.run(main())
