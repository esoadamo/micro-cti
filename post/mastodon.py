import asyncio
import json
import time
import tomllib
from datetime import datetime, timezone
from typing import AsyncIterable, Optional

from mastodon import Mastodon
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, desc
from models import Post

from db import json_serial
from directories import FILE_CONFIG
from .utils import read_html
from .exception import FetchError


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


async def get_mastodon_posts(db: AsyncSession, min_id: int = None, save: bool = True) -> AsyncIterable[Post]:
    try:
        if min_id is None:
            stmt = select(Post).where(Post.source == 'mastodon').order_by(desc(Post.created_at)).limit(1)
            res = await db.exec(stmt)
            max_post = res.first()
            min_id = int(max_post.source_id) if max_post is not None else None

        mastodon = get_mastodon_instance()
        if mastodon is None:
            return

        ended = False
        end_date = datetime(2024, 7, 1, tzinfo=timezone.utc)
        max_id = None

        while not ended:
            timeline = await asyncio.to_thread(mastodon.timeline_home, min_id=min_id, max_id=max_id)
            if not timeline:
                print('[*] Nothing more to check, exiting')
                break
            for post_item in timeline:
                if post_item['created_at'] > end_date:
                    if save:
                        content_html = post_item["content"]
                        content_text = read_html(content_html)
                        source_id = str(post_item['id'])
                        stmt = select(Post).where(Post.source == 'mastodon', Post.source_id == source_id).limit(1)
                        res = await db.exec(stmt)
                        if not res.first():
                            post = Post(
                                source='mastodon',
                                source_id=source_id,
                                user=post_item['account']['acct'],
                                url=post_item['url'] or post_item['uri'],
                                created_at=post_item['created_at'],
                                fetched_at=datetime.now(tz=timezone.utc),
                                content_html=content_html,
                                content_txt=content_text,
                                is_ingested=len(content_text.split()) < 3,
                                raw=json.dumps(post_item, default=json_serial)
                            )
                            db.add(post)
                            await db.commit()
                            await db.refresh(post)
                            yield post
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
                    await asyncio.sleep(sleep_time)
                await asyncio.sleep(1)
    except Exception as e:
        raise FetchError("Error fetching Mastodon posts", [e])
