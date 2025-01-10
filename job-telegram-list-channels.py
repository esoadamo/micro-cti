import asyncio
import tomli_w

from posts import get_telegram_instance


async def main() -> None:
    telegram, chats = get_telegram_instance()

    chats_excluded = set()

    async with telegram as client:
        for dialog in await client.get_dialogs():
            if dialog.name not in chats:
                chats_excluded.add(dialog.name)

    print(tomli_w.dumps({
        'current': sorted(chats),
        'excluded': sorted(chats_excluded),
    }, indent=1))


if __name__ == '__main__':
    asyncio.run(main())
