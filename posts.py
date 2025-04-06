import json
import random
import re
import time
import tomllib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import AsyncIterable, Optional, Tuple, List, Set

import atproto
import feedparser
import pyairtable
from bs4 import BeautifulSoup
from markdown import markdown
from mastodon import Mastodon
from prisma.models import Post
from telethon import TelegramClient

from ai import prompt_tags, prompt_check_cybersecurity_post
from db import get_db, json_serial
from search import format_post_for_search


class FetchError(Exception):
    def __init__(self, message: str, source: List[Exception]):
        super().__init__(message)
        self.source = source


def get_mastodon_secrets() -> dict:
    with open("config.toml", 'rb') as f:
        return tomllib.load(f)["mastodon"]


def get_airtable_secrets() -> dict:
    with open("config.toml", 'rb') as f:
        return tomllib.load(f)["airtable"]


def get_bluesky_secrets() -> dict:
    with open("config.toml", 'rb') as f:
        return tomllib.load(f)["bluesky"]


def get_telegram_secrets() -> dict:
    with open("config.toml", 'rb') as f:
        return tomllib.load(f)["telegram"]


def get_rss_feeds() -> List[dict]:
    with open("config.toml", 'rb') as f:
        try:
            feeds = tomllib.load(f)["rss"]
            return list(feeds.values())
        except KeyError:
            return []


def get_telegram_instance() -> Tuple[TelegramClient, Set[str]]:
    secrets = get_telegram_secrets()
    return TelegramClient('telegram', secrets['api_id'], secrets['api_hash']), set(secrets['chats'])


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


def read_html(content: str) -> str:
    parser = BeautifulSoup(content, "html.parser")
    text = parser.get_text(separator=" ", strip=True)
    for img in parser.find_all('img'):
        text += ' ' + img.get('alt', '')
    text = re.sub(r'\s+', ' ', text)
    # Fix links where there is space between http and ://, e.g. "http ://example.com"
    text = re.sub(r'(https?)\s*:\s*//', r'\1://', text)
    # Fix spaces before hashtags
    text = re.sub(r'#\s+(\w)', r'#\1', text)
    return text.strip()


def read_markdown(content: str) -> str:
    html = markdown(content)
    return read_html(html)


async def get_rss_posts() -> AsyncIterable[Post]:
    feeds = get_rss_feeds()
    exceptions = []
    for feed in feeds:
        # noinspection PyBroadException
        try:
            time.sleep(10)
            source = feed['name']
            date_now = datetime.now(tz=timezone.utc)

            max_post = await (await get_db()).post.find_first(where={'source': source}, order={'created_at': 'desc'})
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
                db = await get_db()
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


async def get_telegram_posts() -> AsyncIterable[Post]:
    errors = []
    try:
        telegram, chats = get_telegram_instance()
        db = await get_db()
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


async def get_bluesky_posts() -> AsyncIterable[any]:
    try:
        client, feeds = get_bluesky_instance()
        db = await get_db()
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


async def get_airtable_posts() -> AsyncIterable[Post]:
    try:
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
                    'is_ingested': len(content_text.split()) < 3,
                    'raw': raw
                })
                yield await db.post.find_unique(where={'id': post.id})
            airtable.delete(record_id)
    except Exception as e:
        raise FetchError("Error fetching Airtable posts", [e])


async def get_mastodon_posts(min_id: int = None, save: bool = True) -> AsyncIterable[Post]:
    try:
        if min_id is None:
            max_post = await (await get_db()).post.find_first(where={'source': 'mastodon'},
                                                              order={'created_at': 'desc'})
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
                        content_text = read_html(content_html)
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


async def ingest_posts(ids: Optional[List[int]] = None) -> None:
    errors = []

    try:
        if not ids and ids is not None:
            return  # Nothing to ingest
        db = await get_db()
        posts_where_filter = {'is_ingested': False}
        if ids:
            assert ids is not None  # Pyright
            posts_where_filter['id'] = {'in': ids}
        uningested_posts = await db.post.find_many(where=posts_where_filter)
        print(f'[*] found {len(uningested_posts)} posts to ingest')

        for i, post in enumerate(uningested_posts):
            try:
                print(f'[*] ingesting {i + 1}th post out of {len(uningested_posts)} total')
                hidden = await hide_post_if_not_about_cybersecurity(post)
                if not hidden:
                    await format_post_for_search(post, regenerate=True)
                await db.post.update(where={'id': post.id}, data={'is_ingested': True})
            except Exception as e:
                errors.append(FetchError(f"Error ingesting {post.id}", [e]))
    except Exception as e:
        errors.append(FetchError("Error ingesting posts", [e]))

    if errors:
        raise FetchError("Error ingesting posts", errors)


async def generate_tags(ids: Optional[List[int]] = None) -> None:
    errors = []

    try:
        if not ids and ids is not None:
            return  # Nothing to tag
        db = await get_db()
        posts_where_filter = {'tags_assigned': False, 'is_hidden': False}
        if ids:
            assert ids is not None  # Pyright
            posts_where_filter['id'] = {'in': ids}
        untagged_posts = await db.post.find_many(
            where=posts_where_filter,
            order={'id': 'desc'}
        )
        print(f'[*] found {len(untagged_posts)} posts to tag')

        for i, post in enumerate(untagged_posts):
            try:
                print(f'[*] tagging {i + 1}th post out of {len(untagged_posts)} total')
                post_content = post.content_txt[:1000]
                print("[?]", post_content.replace('\n', ' '))

                tag_names = set(re.findall(r'#\w+', post_content))

                if len(post_content.split()) > 15:
                    tag_names.update(sorted(set(prompt_tags(post_content)), key=len)[:7])

                tag_names = {x.upper() for x in tag_names}
                print("[-]", tag_names)

                tags = [await db.tag.upsert(where={"name": tag_name},
                                            data={'create': {"name": tag_name, "color": generate_random_color()},
                                                  'update': {}})
                        for tag_name in tag_names]
                await db.post.update(where={'id': post.id},
                                     data={'tags_assigned': True,
                                           'tags': {'connect': [{"id": tag.id} for tag in tags]}})
                await format_post_for_search(post, regenerate=True)
            except Exception as e:
                errors.append(FetchError(f"Error generating tags for {post.id}", [e]))
    except Exception as e:
        errors.append(FetchError("Error generating tags", [e]))

    if errors:
        raise FetchError("Error generating tags", errors)


async def hide_post_if_not_about_cybersecurity(post: Post, force_ai: bool = False) -> bool:
    keywords_whitelist = {'infosec', 'cybersec', 'vuln', 'hack', 'exploit', 'deepfake', 'threat', 'leak', 'phishing',
                          'bypass', 'outage', 'steal', 'malicious', 'compromise'}
    post_content = post.content_txt.lower()
    # Remove all @usernames from the post content
    post_content = re.sub(r'@\S+', '', post_content)
    if not force_ai and any(keyword.lower() in post_content for keyword in keywords_whitelist):
        visible = True
    else:
        visible = prompt_check_cybersecurity_post(post)
    if visible == post.is_hidden:
        db = await get_db()
        await db.post.update(where={'id': post.id}, data={'is_hidden': not visible})
    return visible


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
