import json
import tomllib
from datetime import datetime, timezone
from typing import AsyncIterable, Optional, Tuple, Set

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from models import Post
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


async def get_telegram_posts(db: AsyncSession) -> AsyncIterable[any]:
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
                            if not message.text:
                                # Skip media only messages
                                continue

                            url = f"https://t.me/c/{dialog.entity.id}/{message.id}"
                            content_html = message.text
                            content_txt = read_markdown(content_html)
                            created_at = message.date
                            source = "telegram"
                            source_id = str(message.id)
                            raw = {'url': url, 'content': content_html, 'created_at': created_at, 'source': source,
                                   'sender_id': message.sender_id}
                            stmt = select(Post).where(Post.source == source, Post.source_id == source_id).limit(1)
                            res = await db.exec(stmt)
                            if not res.first():
                                post = Post(
                                    source=source,
                                    source_id=source_id,
                                    user=dialog.name,
                                    url=url,
                                    created_at=created_at,
                                    fetched_at=datetime.now(tz=timezone.utc),
                                    content_html=content_html,
                                    content_txt=content_txt,
                                    is_ingested=len(content_txt.split()) < 3,
                                    raw=json.dumps(raw, default=json_serial)
                                )
                                db.add(post)
                                await db.commit()
                                await db.refresh(post)
                                yield post
                        except Exception as e:
                            errors.append(e)
    except AssertionError as e:
        errors.append(e)
    if errors:
        raise FetchError("Error fetching Telegram posts", errors)
