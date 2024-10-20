import json
import random
import re
import time
import tomllib
from datetime import datetime, timezone, timedelta
from typing import AsyncIterable, Optional, Tuple

import atproto
import pyairtable
from bs4 import BeautifulSoup
from mastodon import Mastodon
from prisma.models import Post

from ai import prompt_tags, prompt_check_cybersecurity_post
from db import get_db, json_serial


def get_mastodon_secrets() -> dict:
    with open("config.toml", 'rb') as f:
        return tomllib.load(f)["mastodon"]


def get_airtable_secrets() -> dict:
    with open("config.toml", 'rb') as f:
        return tomllib.load(f)["airtable"]


def get_bluesky_secrets() -> dict:
    with open("config.toml", 'rb') as f:
        return tomllib.load(f)["bluesky"]


def get_mastodon_instance() -> Mastodon:
    secrets = get_mastodon_secrets()

    return Mastodon(
        client_id=secrets["client_id"],
        client_secret=secrets["client_secret"],
        access_token=secrets["access_token"],
        api_base_url=secrets["api_base_url"]
    )


def get_airtable_instance() -> pyairtable.Table:
    secrets = get_airtable_secrets()
    api = pyairtable.Api(secrets["api_key"])
    return api.table(secrets["base_id"], secrets["table_id"])


# noinspection PyDefaultArgument
def get_bluesky_instance(cache={}) -> Tuple[atproto.Client, list[str]]:
    if 'client' not in cache:
        secrets = get_bluesky_secrets()
        client = atproto.Client()
        client.login(secrets['handle'], secrets['app_password'])
        cache['client'] = client
        cache['feeds'] = secrets['feeds']
    return cache['client'], cache['feeds']


async def get_bluesky_posts() -> AsyncIterable[any]:
    client, feeds = get_bluesky_instance()
    db = await get_db()
    min_time = datetime.now(tz=timezone.utc) - timedelta(days=1)
    max_post = await db.post.find_first(where={'source': 'bluesky'}, order={'created_at': 'desc'})
    if max_post is not None:
        min_time = max_post.created_at

    for feed in feeds:
        fetch_next_page = True
        cursor = ''
        while fetch_next_page:
            data = client.app.bsky.feed.get_feed({
                'feed': feed,
                'limit': 50,
                'cursor': cursor
            }, headers={'Accept-Language': 'en'})
            time.sleep(10)
            cursor = data.cursor
            for b_post in data.feed:
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
                        'is_hidden': len(content_txt.split()) < 3,
                        'raw': json.dumps(raw, default=dict)
                    })
                    if not post.is_hidden:
                        await hide_post_if_not_about_cybersecurity(post)
                    yield await db.post.find_unique(where={'id': post.id})


async def get_airtable_posts() -> AsyncIterable[Post]:
    airtable = get_airtable_instance()
    db = await get_db()

    for record in airtable.all():
        record_id = record["id"]
        record_fields = record["fields"]
        created_at = datetime.fromisoformat(record["createdTime"])

        try:
            user = record_fields["Account"]
            content_text = content_html = record_fields["Content"]
            url = record_fields["Link"]
            source = record_fields["Source"]
            source_id = str(record_fields["Id"])
            raw = json.dumps(record_fields)
        except KeyError:
            continue

        if not await db.post.find_first(where={'source': source, 'source_id': source_id}):
            post = await db.post.create({
                'source': source,
                'source_id': source_id,
                'user': user,
                'url': url,
                'created_at': created_at,
                'fetched_at': datetime.now(tz=timezone.utc),
                'content_html': content_html,
                'content_txt': content_text,
                'is_hidden': len(content_text.split()) < 3,
                'raw': raw
            })
            if not post.is_hidden:
                await hide_post_if_not_about_cybersecurity(post)
            yield await db.post.find_unique(where={'id': post.id})
        airtable.delete(record_id)


async def get_mastodon_posts(min_id: int = None, save: bool = True) -> AsyncIterable[Post]:
    if min_id is None:
        max_post = await (await get_db()).post.find_first(where={'source': 'mastodon'}, order={'created_at': 'desc'})
        min_id = int(max_post.source_id) if max_post is not None else None

    mastodon = get_mastodon_instance()

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
                    content_text = BeautifulSoup(content_html, "html.parser").get_text(separator="", strip=True)
                    content_text = re.sub(r'#\s+(\w)', r'#\1', content_text)
                    db = await get_db()
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
                            'is_hidden': len(content_text.split()) < 3,
                            'raw': json.dumps(post, default=json_serial)
                        })
                        if not post.is_hidden:
                            await hide_post_if_not_about_cybersecurity(post)
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


async def generate_tags() -> None:
    db = await get_db()
    untagged_posts = await db.post.find_many(where={'tags_assigned': False, 'is_hidden': False})
    print(f'[*] found {len(untagged_posts)} posts to tag')

    for i, post in enumerate(untagged_posts):
        print(f'[*] tagging {i + 1}th post out of {len(untagged_posts)} total')
        post_content = post.content_txt
        print("[?]", post_content)

        tag_names = set(re.findall(r'#\w+', post_content))

        if len(post_content.split()) > 15:
            tag_names.update(set(prompt_tags(post_content)))

        tag_names = {x.upper() for x in tag_names}
        print("[-]", tag_names)

        tags = [await db.tag.upsert(where={"name": tag_name},
                                    data={'create': {"name": tag_name, "color": generate_random_color()}, 'update': {}})
                for tag_name in tag_names]
        await db.post.update(where={'id': post.id},
                             data={'tags_assigned': True, 'tags': {'connect': [{"id": tag.id} for tag in tags]}})


async def hide_post_if_not_about_cybersecurity(post: Post) -> bool:
    keywords_whitelist = {'infosec', 'cybersec', 'vuln', 'hack', 'exploit', 'deepfake', 'threat', 'leak', 'phishing',
                          'bypass', 'outage', 'steal', 'malicious', 'compromise'}
    post_content = post.content_txt.lower()
    # Remove all @usernames from the post content
    post_content = re.sub(r'@\S+', '', post_content)
    for keyword in keywords_whitelist:
        if keyword.lower() in post_content:
            return True
    db = await get_db()
    result = prompt_check_cybersecurity_post(post)
    if not result:
        await db.post.update(where={'id': post.id}, data={'is_hidden': True})
    return result


async def get_latest_ingestion_time() -> Optional[datetime]:
    db = await get_db()
    latest_fetched_post = await db.post.find_first(order={'fetched_at': 'desc'})
    return latest_fetched_post.fetched_at if latest_fetched_post else None


def generate_random_color():
    # Generate a random color in HSL format
    h = random.randint(0, 360)  # Hue: 0-360
    s = random.uniform(0.5, 1.0)  # Saturation: 0.5-1.0 (50%-100%)
    l = random.uniform(0.2, 0.6)  # Lightness: 0.2-0.6 (20%-60%)

    # Convert HSL to RGB
    r, g, b = hsl_to_rgb(h, s, l)

    # Convert RGB to hex
    return f'#{int(r):02X}{int(g):02X}{int(b):02X}'


def hsl_to_rgb(h, s, l):
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2

    if 0 <= h < 60:
        r, g, b = c, x, 0
    elif 60 <= h < 120:
        r, g, b = x, c, 0
    elif 120 <= h < 180:
        r, g, b = 0, c, x
    elif 180 <= h < 240:
        r, g, b = 0, x, c
    elif 240 <= h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    return (r + m) * 255, (g + m) * 255, (b + m) * 255
