import asyncio
import json
import tomllib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import AsyncIterable, List

import feedparser
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, desc
from models import Post

from db import json_serial
from directories import FILE_CONFIG
from .utils import read_html
from .exception import FetchError


def get_rss_feeds() -> List[dict]:
    with open(FILE_CONFIG, 'rb') as f:
        try:
            feeds = tomllib.load(f)["rss"]
            return list(feeds.values())
        except KeyError:
            return []


async def get_rss_posts(db: AsyncSession) -> AsyncIterable[Post]:
    feeds = get_rss_feeds()
    exceptions = []
    for feed in feeds:
        try:
            await asyncio.sleep(10)
            source = feed['name']
            date_now = datetime.now(tz=timezone.utc)

            stmt = select(Post).where(Post.source == source).order_by(desc(Post.created_at)).limit(1)
            res = await db.exec(stmt)
            max_post = res.first()
            if max_post and max_post.created_at:
                min_post_time = max_post.created_at.replace(tzinfo=timezone.utc) if max_post.created_at.tzinfo is None else max_post.created_at
            else:
                min_post_time = datetime.now(tz=timezone.utc) - timedelta(days=1)

            for rss_post in feedparser.parse(
                feed['url'],
                agent=f'RSS Reader {date_now.year}.{date_now.month}'
            ).entries:
                try:
                    created_at = datetime.fromisoformat(rss_post.published)
                except ValueError:
                    created_at = parsedate_to_datetime(rss_post.published)
                    assert created_at is not None
                except AttributeError:
                    continue

                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

                if created_at < min_post_time:
                    continue

                try:
                    author = rss_post.author
                    source_id = rss_post.link
                    url = rss_post.link
                    content_html = rss_post.title + " " + rss_post.summary
                except AttributeError:
                    continue
                content_txt = read_html(content_html)
                stmt = select(Post).where(Post.source == source, Post.source_id == source_id).limit(1)
                res = await db.exec(stmt)
                if len(content_txt.split()) > 3 and not res.first():
                    post = Post(
                        source=source,
                        source_id=source_id,
                        user=author,
                        url=url,
                        created_at=created_at,
                        fetched_at=datetime.now(tz=timezone.utc),
                        content_html=content_html,
                        content_txt=content_txt,
                        is_ingested=len(content_txt.split()) < 3,
                        raw=json.dumps(rss_post, default=json_serial)
                    )
                    db.add(post)
                    await db.commit()
                    await db.refresh(post)
                    yield post
        except Exception as e:
            exceptions.append(e)
    if exceptions:
        raise FetchError("Error fetching RSS feeds", exceptions)
