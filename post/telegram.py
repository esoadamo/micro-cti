import json
import tomllib
from datetime import datetime, timezone
from typing import AsyncIterable, Optional, Tuple, Set

from prisma import Prisma
from telethon import TelegramClient

from db import json_serial
from directories import DIR_DATA, FILE_CONFIG
from .utils import read_markdown
from .exception import FetchError


def get_telegram_secrets() -> Optional[dict]:
    try:
        with open(FILE_CONFIG, 'rb') as f:
            return tomllib.load(f)["telegram"]
    except KeyError:
        return None


def get_telegram_instance() -> Optional[Tuple[TelegramClient, Set[str]]]:
    secrets = get_telegram_secrets()
    if secrets is None:
        return None
    file_session = DIR_DATA / 'telegram'
    return TelegramClient(f"{file_session.absolute()}", secrets['api_id'], secrets['api_hash']), set(secrets['chats'])


async def get_telegram_posts(db: Prisma) -> AsyncIterable[any]:
    errors = []
    try:
        telegram, chats = get_telegram_instance()
        if telegram is None:
            return
        async with telegram as client:
            async for dialog in client.iter_dialogs():
                if dialog.name not in chats:
                    continue
                messages_to_fetch = dialog.unread_count
                if dialog.unread_count > 0:  # Check for unread messages
                    await client.send_read_acknowledge(dialog.entity)
                    async for message in client.iter_messages(dialog.entity, limit=messages_to_fetch):
                        try:
                            url = f"https://t.me/c/{dialog.entity.id}/{message.id}"
                            content_html = message.text
                            content_txt = read_markdown(content_html)
                            created_at = message.date
                            source = "telegram"
                            source_id = str(message.id)
                            raw = {'url': url, 'content': content_html, 'created_at': created_at, 'source': source,
                                   'sender_id': message.sender_id}
                            if not await db.post.find_first(where={'source': source, 'source_id': source_id}):
                                post = await db.post.create({
                                    'source': source,
                                    'source_id': source_id,
                                    'user': dialog.name,
                                    'url': url,
                                    'created_at': created_at,
                                    'fetched_at': datetime.now(tz=timezone.utc),
                                    'content_html': content_html,
                                    'content_txt': content_txt,
                                    'is_ingested': len(content_txt.split()) < 3,
                                    'raw': json.dumps(raw, default=json_serial)
                                })
                                yield await db.post.find_unique(where={'id': post.id})
                        except Exception as e:
                            errors.append(e)
    except AssertionError as e:
        errors.append(e)
    if errors:
        raise FetchError("Error fetching Telegram posts", errors)
