"""
Post module - handles fetching and processing posts from various sources.

This module is organized into submodules by platform:
- mastodon: Mastodon social network integration
- baserow: Baserow database integration
- airtable: Airtable database integration
- bluesky: Bluesky social network integration
- rss: RSS feed processing
- telegram: Telegram messaging platform integration
- utils: Utility functions for content processing
"""

import re
from datetime import datetime
from typing import Optional, List

from prisma import Prisma
from prisma.models import Post

from ai import prompt_tags, prompt_check_cybersecurity_post
from search import format_post_for_search
from .airtable import (
    get_airtable_secrets,
    get_airtable_instance,
    get_airtable_posts,
)
from .baserow import (
    get_baserow_secrets,
    get_baserow_posts,
)
from .bluesky import (
    get_bluesky_secrets,
    get_bluesky_instance,
    get_bluesky_posts,
)
from .exception import FetchError
# Import platform-specific modules
from .mastodon import (
    get_mastodon_secrets,
    get_mastodon_instance,
    get_mastodon_posts,
)
from .rss import (
    get_rss_feeds,
    get_rss_posts,
)
from .telegram import (
    get_telegram_secrets,
    get_telegram_instance,
    get_telegram_posts,
)
from .utils import (
    read_html,
    read_markdown,
    generate_random_color,
    hsl_to_rgb
)


async def ingest_posts(db: Prisma, ids: Optional[List[int]] = None) -> None:
    errors = []

    try:
        if not ids and ids is not None:
            return  # Nothing to ingest
        posts_where_filter = {'is_ingested': False}
        if ids:
            assert ids is not None  # Pyright
            posts_where_filter['id'] = {'in': ids}
        uningested_posts = await db.post.find_many(where=posts_where_filter)
        print(f'[*] found {len(uningested_posts)} posts to ingest')

        for i, post in enumerate(uningested_posts):
            try:
                print(f'[*] ingesting {i + 1}th post out of {len(uningested_posts)} total')
                visible = await hide_post_if_not_about_cybersecurity(post, db)
                if visible:
                    await format_post_for_search(post, db, regenerate=True)
                print(f'[-] post {"hidden" if not visible else "kept"} after ingestion')
                await db.post.update(where={'id': post.id}, data={'is_ingested': True})
            except Exception as e:
                errors.append(FetchError(f"Error ingesting {post.id}", [e]))
    except Exception as e:
        errors.append(FetchError("Error ingesting posts", [e]))

    if errors:
        raise FetchError("Error ingesting posts", errors)


async def generate_tags(db: Prisma, ids: Optional[List[int]] = None) -> None:
    errors = []

    try:
        if not ids and ids is not None:
            return  # Nothing to tag
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
                    tag_names.update(sorted(set(await prompt_tags(post_content)), key=len)[:7])

                tag_names = {x.upper() for x in tag_names}
                print("[-]", tag_names)

                tags = [await db.tag.upsert(where={"name": tag_name},
                                            data={'create': {"name": tag_name, "color": generate_random_color()},
                                                  'update': {}})
                        for tag_name in tag_names]
                await db.post.update(where={'id': post.id},
                                     data={'tags_assigned': True,
                                           'tags': {'connect': [{"id": tag.id} for tag in tags]}})
                await format_post_for_search(post, db, regenerate=True)
            except Exception as e:
                errors.append(FetchError(f"Error generating tags for {post.id}", [e]))
    except Exception as e:
        errors.append(FetchError("Error generating tags", [e]))

    if errors:
        raise FetchError("Error generating tags", errors)


async def hide_post_if_not_about_cybersecurity(post: Post, db, force_ai: bool = False) -> bool:
    keywords_whitelist = {'infosec', 'cybersec', 'vuln', 'hack', 'exploit', 'deepfake', 'threat', 'leak', 'phishing',
                          'bypass', 'outage', 'steal', 'malicious', 'compromise'}
    post_content = post.content_txt.lower()
    # Remove all @usernames from the post content
    post_content = re.sub(r'@\S+', '', post_content)
    if not force_ai and any(keyword.lower() in post_content for keyword in keywords_whitelist):
        visible = True
    else:
        visible = await prompt_check_cybersecurity_post(post)
    if visible == post.is_hidden:
        await db.post.update(where={'id': post.id}, data={'is_hidden': not visible})
    return visible


async def get_latest_ingestion_time(db: Prisma, source: Optional[str] = None) -> Optional[datetime]:
    latest_fetched_post = await db.post.find_first(
        where={'is_hidden': False, **({'source': source} if source else {})},
        order={'fetched_at': 'desc'}
    )
    return latest_fetched_post.fetched_at if latest_fetched_post else None


# Export all public APIs
__all__ = [
    # Main error class
    'FetchError',
    
    # Utility functions
    'read_html',
    'read_markdown',
    'generate_random_color',
    'hsl_to_rgb',
    
    # Mastodon
    'get_mastodon_secrets',
    'get_mastodon_instance',
    'get_mastodon_posts',
    
    # Baserow
    'get_baserow_secrets',
    'get_baserow_posts',
    
    # Airtable
    'get_airtable_secrets',
    'get_airtable_instance',
    'get_airtable_posts',
    
    # Bluesky
    'get_bluesky_secrets',
    'get_bluesky_instance',
    'get_bluesky_posts',
    
    # RSS
    'get_rss_feeds',
    'get_rss_posts',
    
    # Telegram
    'get_telegram_secrets',
    'get_telegram_instance',
    'get_telegram_posts',
    
    # Post processing functions
    'ingest_posts',
    'generate_tags',
    'hide_post_if_not_about_cybersecurity',
    'get_latest_ingestion_time',
]
