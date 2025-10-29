import json
import time
import tomllib
from datetime import datetime, timezone, timedelta
from typing import AsyncIterable, Optional, Tuple

import atproto
from prisma import Prisma

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


async def get_bluesky_posts(db: Prisma) -> AsyncIterable[any]:
    try:
        client, feeds = get_bluesky_instance()
        if client is None:
            return
        min_time = datetime.now(tz=timezone.utc) - timedelta(days=1)
        max_post = await db.post.find_first(where={'source': 'bluesky'}, order={'created_at': 'desc'})
        if max_post is not None:
            min_time = max_post.created_at
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
                    source = "bluesky"
                    source_id = b_post.post.cid
                    url = f"https://bsky.app/profile/{user}/post/{b_post.post.uri.split('/')[-1]}"
                    raw = dict(b_post)
                    raw["$feed"] = feed

                    if created_at < min_time:
                        fetch_next_page = False
                        break

                    if not await db.post.find_first(where={'source': source, 'source_id': source_id}):
                        # noinspection PyTypeChecker
                        post = await db.post.create({
                            'source': source,
                            'source_id': source_id,
                            'user': user,
                            'url': url,
                            'created_at': created_at,
                            'fetched_at': datetime.now(tz=timezone.utc),
                            'content_html': content_txt,
                            'content_txt': content_txt,
                            'is_ingested': len(content_txt.split()) < 3,
                            'raw': json.dumps(raw, default=dict)
                        })
                        yield await db.post.find_unique(where={'id': post.id})
        except Exception as e:
            exceptions.append(e)
    if exceptions:
        raise FetchError("Error fetching Bluesky feeds", exceptions)
