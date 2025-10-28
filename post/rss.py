import json
import time
import tomllib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import AsyncIterable, List

import feedparser
from prisma import Prisma
from prisma.models import Post

from db import json_serial
from directories import FILE_CONFIG
from .utils import read_html


class FetchError(Exception):
    def __init__(self, message: str, source: list[Exception]):
        super().__init__(message)
        self.source = source


def get_rss_feeds() -> List[dict]:
    with open(FILE_CONFIG, 'rb') as f:
        try:
            feeds = tomllib.load(f)["rss"]
            return list(feeds.values())
        except KeyError:
            return []


async def get_rss_posts(db: Prisma) -> AsyncIterable[Post]:
    feeds = get_rss_feeds()
    exceptions = []
    for feed in feeds:
        # noinspection PyBroadException
        try:
            time.sleep(10)
            source = feed['name']
            date_now = datetime.now(tz=timezone.utc)

            max_post = await db.post.find_first(where={'source': source}, order={'created_at': 'desc'})
            min_post_time = max_post.created_at if max_post else datetime.now(tz=timezone.utc) - timedelta(days=1)

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
                if len(content_txt.split()) > 3 and not await db.post.find_first(where={'source': source, 'source_id': source_id}):
                    post = await db.post.create({
                        'source': source,
                        'source_id': source_id,
                        'user': author,
                        'url': url,
                        'created_at': created_at,
                        'fetched_at': datetime.now(tz=timezone.utc),
                        'content_html': content_html,
                        'content_txt': content_txt,
                        'raw': json.dumps(rss_post, default=json_serial)
                    })
                    yield await db.post.find_unique(where={'id': post.id})
        except Exception as e:
            exceptions.append(e)
    if exceptions:
        raise FetchError("Error fetching RSS feeds", exceptions)
