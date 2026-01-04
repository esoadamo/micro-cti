import ipaddress
import re
from typing import AsyncIterable, List, Optional, TypedDict, Dict
from enum import Enum

from prisma import Prisma
from prisma.models import Post, IoC
from pydantic import BaseModel, Field

from ai import prompt
from search import search_posts
from post.exception import FetchError


class AIOicType(Enum):
    ip = 'ip'
    domain = 'domain'
    hash = 'hash'
    url = 'url'
    email = 'email'
    external_report_link = 'external-report-link'
    browser_extension_id = 'browser-extension-id'
    vulnerability = 'vulnerability'
    username = 'username'
    threat_actor = 'threat-actor'
    filename = 'filename'
    command = 'command'


class AIIoC(BaseModel):
    value: str
    type: AIOicType
    comment: Optional[str] = Field(default=None)


class ParsedIoC(TypedDict):
    ioc: str
    type_main: str
    type_secondary: Optional[str]
    comment: Optional[str]


class IoCLink(TypedDict):
    value: str
    type: str
    subtype: Optional[str]
    relevance: int
    comment: Optional[str]
    links: List[str]


async def parse_iocs(db: Prisma, ids: Optional[List[int]] = None) -> AsyncIterable[IoC]:
    errors = []

    try:
        if not ids and ids is not None:
            return  # Nothing to tag
        posts_where_filter = {'iocs_assigned': False, 'is_hidden': False}
        if ids:
            assert ids is not None  # Pyright
            posts_where_filter['id'] = {'in': ids}
        posts_to_process = await db.post.find_many(
            where=posts_where_filter,
            order={'id': 'desc'}
        )
        print(f'[*] found {len(posts_to_process)} posts to parse IoCs from')
        for i, post in enumerate(posts_to_process):
            try:
                print(f'[*] parsing IoCs from {i + 1}th post out of {len(posts_to_process)} total')
                async for ioc in parse_iocs_from_post(post, db):
                    print(f'  [+] {ioc}')
                    yield ioc
                await db.post.update(where={'id': post.id}, data={'iocs_assigned': True})
            except Exception as e:
                errors.append(FetchError(f"Error parsing IoCs from post {post.id}", [e]))
    except Exception as e:
        errors.append(FetchError("Error parsing IoCs from posts", [e]))

    if errors:
        raise FetchError("Error parsing IoCs from posts", errors)


async def parse_iocs_from_post(post: Post, db: Prisma) -> AsyncIterable[IoC]:
    # Truncate content to 2000 chars (enough for most IoCs)
    content = post.content_txt[:2000]
    response: List[AIIoC] = await prompt(
        system_prompt=(
            "Extract IoCs from text. Return JSON array with 'value', 'type', 'comment'. "
            "Types: ip, domain, hash, url, email, external-report-link, browser-extension-id, vulnerability, username. "
            "Restore defanged IoCs (hxxp→http, [.]→.). Empty array if none found."
        ),
        user_prompt=content,
        output_type=List[AIIoC]
    )
    response.append(AIIoC(value=post.url, type=AIOicType.external_report_link, comment="Link to the post"))

    iocs: Dict[str, ParsedIoC] = {}
    for ioc in response:
        if not ioc.value or not ioc.type:
            continue

        ioc_key = f"{ioc.type.value}:{ioc.value}"
        type_main = ioc.type.value
        type_secondary = None
        ioc.comment = ioc.comment.strip() if ioc.comment else None
        is_valid = True

        match ioc.type:
            case AIOicType.ip:
                type_main = 'ip'
                try:
                    ip_obj = ipaddress.ip_address(ioc.value)
                    type_secondary = 'ipv4' if ip_obj.version == 4 else 'ipv6'
                except ValueError:
                    is_valid = False
            case AIOicType.hash:
                hash_len = len(ioc.value)
                if hash_len == 32:
                    type_secondary = 'md5'
                elif hash_len == 40:
                    type_secondary = 'sha1'
                elif hash_len == 64:
                    type_secondary = 'sha256'
                elif hash_len == 128:
                    type_secondary = 'sha512'
                else:
                    is_valid = False
            case AIOicType.domain:
                is_valid = re.fullmatch(r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$', ioc.value) is not None
            case AIOicType.url:
                is_valid = re.fullmatch(r'^\S+://[^\s/$.?#].\S*$', ioc.value) is not None
            case AIOicType.external_report_link:
                is_valid = re.fullmatch(r'^\S+://[^\s/$.?#].\S*$', ioc.value) is not None
                type_secondary = 'post-link' if ioc.value == post.url else 'external-article'
            case AIOicType.email:
                is_valid = re.fullmatch(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', ioc.value) is not None
            case AIOicType.vulnerability:
                is_valid = re.fullmatch(r'^(CVE|GHSA)-\d{4}-\d{4,}$', ioc.value) is not None

        if is_valid:
            iocs[ioc_key] = {'ioc': ioc.value, 'type_main': type_main, 'type_secondary': type_secondary, 'comment': ioc.comment}

    for ioc in iocs.values():
        ioc = await db.ioc.create(
            data={'value': ioc['ioc'], 'type': ioc['type_main'], 'subtype': ioc['type_secondary'], 'comment': ioc['comment']}
        )
        await db.post.update(where={'id': post.id}, data={'iocs': {'connect': [{'id': ioc.id}]}})
        yield ioc


async def search_iocs(search_term: str, db: Prisma) -> List[IoCLink]:
    posts_search = await search_posts(search_term, db)
    post_scores = {post.id: score['relevancy_score'] for post, score in posts_search}
    post_ids: List[int] = list(post_scores.keys())
    iocs = await db.ioc.find_many(where={'posts': {'some': {'id': {'in': post_ids}}}}, include={'posts': True})

    iocs_link: List[IoCLink] = []
    for ioc in iocs:
        relevance = max(post_scores[post.id] for post in ioc.posts)
        iocs_link.append({
            'value': ioc.value,
            'type': ioc.type,
            'subtype': ioc.subtype,
            'relevance': relevance,
            'comment': ioc.comment,
            'links': [post.url for post in ioc.posts]
        })

    iocs_link.sort(key=lambda x: x['relevance'], reverse=True)
    return iocs_link
