import re
from datetime import datetime
from typing import AsyncIterable, List, Tuple, Optional
from typing_extensions import TypedDict

from prisma.models import Post, IoC

from db import get_db
from search import format_post_for_search, search_posts


class IoCLink(TypedDict):
    value: str
    type: str
    subtype: Optional[str]
    relevance: int
    links: List[str]


async def parse_iocs(post: Post) -> AsyncIterable[IoC]:
    content = post.content_search
    if content is None:
        content = await format_post_for_search(post)

    iocs: List[Tuple[str, str, str]] = []
    # IPv4
    for match in re.finditer(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', content):
        iocs.append((match.group(), 'ip', 'ipv4'))
    # IPv6
    for match in re.finditer(r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b', content):
        iocs.append((match.group(), 'ip', 'ipv6'))
    # md5
    for match in re.finditer(r'\b[a-f0-9]{32}\b', content):
        iocs.append((match.group(), 'hash', 'md5'))
    # sha1
    for match in re.finditer(r'\b[a-f0-9]{40}\b', content):
        iocs.append((match.group(), 'hash', 'sha1'))
    # sha256
    for match in re.finditer(r'\b[a-f0-9]{64}\b', content):
        iocs.append((match.group(), 'hash', 'sha256'))
    # sha512
    for match in re.finditer(r'\b[a-f0-9]{128}\b', content):
        iocs.append((match.group(), 'hash', 'sha512'))
    # domain
    for match in re.finditer(r'\b(?:[a-z0-9-]{1,63}\[\.]){1,10}[a-z]{2,63}\b', content):
        iocs.append((match.group(), 'domain', 'fqdn'))

    db = await get_db()
    for ioc, type_main, type_secondary in iocs:
        ioc = await db.ioc.upsert(
            where={'type_subtype_value': {'value': ioc, 'type': type_main, 'subtype': type_secondary}},
            data={'create': {'value': ioc, 'type': type_main, 'subtype': type_secondary}, 'update': {}}
        )
        await db.post.update(where={'id': post.id}, data={'iocs': {'connect': [{'id': ioc.id}]}})
        yield ioc


async def search_iocs(search_term: str) -> List[IoCLink]:
    db = await get_db()
    posts_search = await search_posts(search_term)
    post_scores = {post.id: score['relevancy_score'] for post, score in posts_search}
    iocs = await db.ioc.find_many(where={'posts': {'some': {'id': {'in': list(post_scores.keys())}}}}, include={'posts': True})

    iocs_link: List[IoCLink] = []
    for ioc in iocs:
        relevance = max(post_scores[post.id] for post in ioc.posts)
        iocs_link.append({
            'value': ioc.value,
            'type': ioc.type,
            'subtype': ioc.subtype,
            'relevance': relevance,
            'links': [post.url for post in ioc.posts]
        })

    iocs_link.sort(key=lambda x: x['relevance'], reverse=True)
    return iocs_link
