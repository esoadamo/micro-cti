import json
import time
import tomllib
from datetime import datetime, timezone
from typing import AsyncIterable, Optional

from mastodon import Mastodon
from prisma import Prisma
from prisma.models import Post

from db import json_serial
from directories import FILE_CONFIG
from .utils import read_html


class FetchError(Exception):
    def __init__(self, message: str, source: list[Exception]):
        super().__init__(message)
        self.source = source


def get_mastodon_secrets() -> Optional[dict]:
    try:
        with open(FILE_CONFIG, 'rb') as f:
            return tomllib.load(f)["mastodon"]
    except KeyError:
        return None


def get_mastodon_instance() -> Optional[Mastodon]:
    secrets = get_mastodon_secrets()
    if secrets is None:
        return None

    return Mastodon(
        client_id=secrets["client_id"],
        client_secret=secrets["client_secret"],
        access_token=secrets["access_token"],
        api_base_url=secrets["api_base_url"]
    )


async def get_mastodon_posts(db: Prisma, min_id: int = None, save: bool = True) -> AsyncIterable[Post]:
    try:
        if min_id is None:
            max_post = await db.post.find_first(where={'source': 'mastodon'},
                                                              order={'created_at': 'desc'})
            min_id = int(max_post.source_id) if max_post is not None else None

        mastodon = get_mastodon_instance()
        if mastodon is None:
            return

        ended = False
        end_date = datetime(2024, 7, 1, tzinfo=timezone.utc)
        max_id = None

        while not ended:
            timeline = mastodon.timeline_home(min_id=min_id, max_id=max_id)
            if not timeline:
                print('[*] Nothing more to check, exiting')
                break
            for post in timeline:
                if post['created_at'] > end_date:
                    if save:
                        content_html = post["content"]
                        content_text = read_html(content_html)
                        source_id = str(post['id'])
                        if not await db.post.find_first(where={'source': 'mastodon', 'source_id': source_id}):
                            post = await db.post.create({
                                'source': 'mastodon',
                                'source_id': source_id,
                                'user': post['account']['acct'],
                                'url': post['url'] or post['uri'],
                                'created_at': post['created_at'],
                                'fetched_at': datetime.now(tz=timezone.utc),
                                'content_html': content_html,
                                'content_txt': content_text,
                                'is_ingested': len(content_text.split()) < 3,
                                'raw': json.dumps(post, default=json_serial)
                            })
                            yield await db.post.find_unique(where={'id': post.id})
                else:
                    ended = True
                    print('[*] Selected end time reached, exiting')
                    break

            max_id = timeline[-1]['id']
            if not ended:
                print('[*] Fetched posts up to', timeline[-1]['created_at'],
                      f'got {mastodon.ratelimit_remaining} requests left')
                if mastodon.ratelimit_remaining <= 1:
                    sleep_time = max(0, mastodon.ratelimit_reset - time.time())
                    print(f'[*] Ratelimit reached, sleeping for {sleep_time} s until {mastodon.ratelimit_reset}')
                    time.sleep(sleep_time)
                time.sleep(1)
    except Exception as e:
        raise FetchError("Error fetching Mastodon posts", [e])
