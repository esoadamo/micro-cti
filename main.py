import asyncio

from posts import generate_tags, get_mastodon_posts, get_airtable_posts


async def main() -> None:
    print('[*] Fetching started')
    async for _ in get_airtable_posts():
        pass
    print('[*] Airtable fetched')
    async for _ in get_mastodon_posts():
        pass
    print('[*] Mastodon fetched')
    await generate_tags()
    print('[*] Tags generated')


if __name__ == "__main__":
    asyncio.run(main())
