import json
import time
import tomllib
from datetime import datetime, timezone, timedelta
from typing import AsyncIterable, Optional, Tuple

import atproto
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, desc
from models import Post

from directories import FILE_CONFIG
from .exception import FetchError

def get_bluesky_secrets() -> Optional[dict]:
    try:
        with open(FILE_CONFIG, 'rb') as f:
            return tomllib.load(f)["bluesky"]
    except KeyError:
        return None


# noinspection PyDefaultArgument
def get_bluesky_instance(cache={}) -> Optional[Tuple[atproto.Client, list[str]]]:
    if 'client' not in cache:
        secrets = get_bluesky_secrets()
        if secrets is None:
            return None
        client = atproto.Client()
        client.login(secrets['handle'], secrets['app_password'])
        cache['client'] = client
        cache['feeds'] = secrets['feeds']
    return cache['client'], cache['feeds']


async def get_bluesky_posts(db: AsyncSession) -> AsyncIterable[any]:
    try:
        client, feeds = get_bluesky_instance()
        if client is None:
            return
        min_time = datetime.now(tz=timezone.utc) - timedelta(days=1)
        stmt = select(Post).where(Post.source == 'bluesky').order_by(desc(Post.created_at)).limit(1)
        res = await db.exec(stmt)
        max_post = res.first()
        if max_post is not None:
            min_time = max_post.created_at.replace(tzinfo=timezone.utc) if max_post.created_at.tzinfo is None else max_post.created_at
    except Exception as e:
        raise FetchError("Error fetching Bluesky config", [e])

    exceptions = []

    for feed in feeds:
        try:
            fetch_next_page = True
            cursor = ''
            while fetch_next_page:
                response = client.app.bsky.feed.get_feed({
                    'feed': feed,
                    'limit': 50,
                    'cursor': cursor
                }, headers={'Accept-Language': 'en'})
                time.sleep(10)
                cursor = response.cursor
                for b_post in response.feed:
                    user = b_post.post.author.handle
                    content_txt = b_post.post.record.text
                    created_at = datetime.fromisoformat(b_post.post.record.created_at)
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    source = "bluesky"
                    source_id = b_post.post.cid
                    url = f"https://bsky.app/profile/{user}/post/{b_post.post.uri.split('/')[-1]}"
                    raw = dict(b_post)
                    raw["$feed"] = feed

                    if created_at < min_time:
                        fetch_next_page = False
                        break

                    stmt = select(Post).where(Post.source == source, Post.source_id == source_id).limit(1)
                    res = await db.exec(stmt)
                    if not res.first():
                        post = Post(
                            source=source,
                            source_id=source_id,
                            user=user,
                            url=url,
                            created_at=created_at,
                            fetched_at=datetime.now(tz=timezone.utc),
                            content_html=content_txt,
                            content_txt=content_txt,
                            is_ingested=len(content_txt.split()) < 3,
                            raw=json.dumps(raw, default=dict)
                        )
                        db.add(post)
                        await db.commit()
                        await db.refresh(post)
                        yield post
        except Exception as e:
            exceptions.append(e)
    if exceptions:
        raise FetchError("Error fetching Bluesky feeds", exceptions)
