import asyncio

from posts import generate_tags, get_mastodon_posts, get_airtable_posts


async def main() -> None:    
    print('[*] Fetching started')
    async for post in get_airtable_posts():
        print('[-]', post)
    print('[*] Airtable fetched')
    async for post in get_mastodon_posts():
        print('[-]', post)
    print('[*] Mastodon fetched')
    await generate_tags()
    print('[*] Tags generated')


if __name__ == "__main__":
    asyncio.run(main())