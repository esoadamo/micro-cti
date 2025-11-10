import json
import re
import time
from csv import DictWriter
from datetime import datetime, timedelta
from email.utils import format_datetime as format_rfc2822
from hashlib import md5
from io import StringIO
from typing import List, Optional, Annotated, Dict
from base64 import b64encode, b64decode

from fastapi import FastAPI, Request, Depends
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, JSONResponse, RedirectResponse
from fastapi.exceptions import HTTPException
from fastapi.templating import Jinja2Templates
from lark import ParseError
from prisma import Prisma
# noinspection PyPackageRequirements,PyProtectedMember
from starlette.templating import _TemplateResponse
from typing_extensions import TypedDict

from db import get_db_session
from ioc import search_iocs, IoCLink
from post import get_latest_ingestion_time
from search import search_posts, parse_search_commands, SearchCommands
from misp_feed import generate_misp_feed

app = FastAPI()
templates = Jinja2Templates(directory="templates")


class IoCSearchResponse(TypedDict):
    search_term: str
    iocs: List[IoCLink]
    latest_ingestion_time: Optional[datetime]


class PostSearchTags(TypedDict):
    name: str
    color: str


class PostSearch(TypedDict):
    user: str
    source: str
    excerpt: str
    created: datetime
    url: str
    score: float
    uid: str
    tags: List[PostSearchTags]


class PostSearchResponse(TypedDict):
    search_term: str
    posts: List[PostSearch]


class ApiDynamicQueriesResponse(TypedDict):
    query: str
    commands: SearchCommands
    subqueries: List[str]


def render_template(filename, request, headers=None, **context):
    return templates.TemplateResponse(
        request=request, name=filename, context=context,
        headers=headers
    )


DBDeps = Annotated[Prisma, Depends(get_db_session)]


@app.get("/", response_class=HTMLResponse)
@app.get("/search/", response_class=HTMLResponse)
async def app_search(request: Request, db: DBDeps, q: str = "") -> _TemplateResponse:
    time_start = time.time()
    search_term = q
    posts = []
    search_back_data = {}
    error = ""
    latest_ingestion_time = None

    if search_term:
        try:
            posts = await search_posts(search_term, db, back_data=search_back_data)
            latest_ingestion_time = await get_latest_ingestion_time(db)
        except ParseError as e:
            error = str(e)

    time_delta_ms = int(1000 * (time.time() - time_start))
    return render_template(
        'search_posts.html',
        request,
        results=posts,
        search_term=search_back_data.get('query', search_term),
        latest_ingestion_time=latest_ingestion_time,
        error=error,
        time_render=time_delta_ms,
        search_count=search_back_data.get('cnt_search', 0),
        commands=search_back_data.get('search_commands', {})
    )


@app.get("/search/dynamic/", response_class=HTMLResponse)
async def app_search(request: Request, q: str = "") -> _TemplateResponse:
    search_term = q
    return render_template(
        'search_posts_dynamic.html',
        request,
        search_term=search_term,
        latest_ingestion_time=None,
        time_render=0
    )


@app.get("/ioc/json/")
async def app_ioc_json(q: str, db: DBDeps) -> IoCSearchResponse:
    search_term = q
    iocs = await search_iocs(search_term, db)
    return {
        'search_term': search_term,
        'iocs': iocs,
        'latest_ingestion_time': await get_latest_ingestion_time(db),
    }


@app.get("/ioc/csv/", response_class=PlainTextResponse)
async def app_ioc_csv(q: str, db: DBDeps) -> str:
    search_term = q
    iocs = await search_iocs(search_term, db)
    output = StringIO()

    writer = DictWriter(output, fieldnames=['type', 'value', 'subtype', 'comment', 'link', 'relevance'])
    writer.writeheader()
    for ioc in iocs:
        writer.writerow({
            'type': ioc['type'],
            'subtype': ioc.get('subtype', ''),
            'value': ioc['value'],
            'comment': ioc.get('comment', ''),
            'link': ';'.join(map(lambda x: x.replace('|', '&#124;'), ioc['links'])),
            'relevance': ioc['relevance']
        })

    return output.getvalue()


@app.get("/ioc/misp/", response_class=RedirectResponse)
async def app_ioc_misp(q: str, request: Request) -> RedirectResponse:
    return RedirectResponse(
        request.url_for(
            'app_ioc_misp_search_file',
            search_base64=b64encode(json.dumps({'q': q}).encode()).decode(),
            filename='manifest.json'
        )
    )


@app.get('/ioc/misp/{search_base64}/{filename}', response_class=JSONResponse)
async def app_ioc_misp_search_file(search_base64: str, filename: str, db: DBDeps) -> dict:
    query = json.loads(b64decode(search_base64).decode())
    search_term = query['q']
    iocs = await search_iocs(search_term, db)
    feed = generate_misp_feed(iocs)
    if filename == 'manifest.json':
        return feed.manifest
    for event in feed.events:
        if event.get('Event', {}).get('uuid', '') + '.json' == filename:
            return event
    raise HTTPException(status_code=404, detail="Item not found")


@app.get("/rss/", response_class=PlainTextResponse)
async def app_rss(request: Request, db: DBDeps, q: str = "") -> _TemplateResponse:
    search_term = q
    posts = []

    if search_term:
        posts = await search_posts(search_term, db)

    return render_template(
        'rss.xml',
        request,
        headers={"Content-Type": "application/rss+xml"},
        posts=posts,
        search_term=search_term,
        url=request.url,
        latest_ingestion_time=await get_latest_ingestion_time(db),
        format_rfc2822=format_rfc2822
    )


@app.get("/api/search")
async def app_api_search(q: str, db: DBDeps) -> PostSearchResponse:
    search_term = q
    posts = await search_posts(search_term, db)

    posts_response: List[PostSearch] = []
    for post, metadata in posts:
        posts_response.append({
            'user': post.user,
            'source': post.source,
            'excerpt': post.content_txt[:90],
            'created': post.created_at,
            'url': post.url,
            'score': metadata['relevancy_score'],
            'tags': [{'name': tag.name, 'color': tag.color} for tag in post.tags],
            'uid': md5((post.source + post.source_id).encode()).hexdigest()
        })

    return {
        'search_term': search_term,
        'posts': posts_response
    }


@app.get('/api/dynamic-queries')
async def app_dynamic_queries(q: str) -> ApiDynamicQueriesResponse:
    commands = parse_search_commands(q)
    search_latest = commands['search_latest']
    search_earliest = commands['search_earliest']
    base_query = commands['final_query']
    queries: List[str] = []

    step = timedelta(days=7)
    while search_latest > search_earliest:
        search_earliest_curr = max(search_latest - step, search_earliest)
        query = base_query
        query = re.sub('!from:([0-9]{4}-[0-9]{2}-[0-9]{2})', f'!from:{search_earliest_curr.strftime("%Y-%m-%d")}', query)
        query = re.sub('!to:([0-9]{4}-[0-9]{2}-[0-9]{2})', f'!to:{search_latest.strftime("%Y-%m-%d")}', query)
        queries.append(query)

        search_latest -= step

    return {
        'query': base_query,
        'commands': commands,
        'subqueries': queries
    }


@app.get("/favicon.svg", response_class=FileResponse)
async def favicon() -> FileResponse:
    return FileResponse('favicon.svg')


@app.get("/healthcheck")
async def healthcheck(db: DBDeps) -> dict:
    ingestion_times = {
        'mastodon': await get_latest_ingestion_time(db, source='mastodon'),
        'twitter': await get_latest_ingestion_time(db, source='twitter.com'),
        'bluesky': await get_latest_ingestion_time(db, source='bluesky'),
        'reddit': await get_latest_ingestion_time(db, source='/r/cybersecurity'),
        'telegram': await get_latest_ingestion_time(db, source='telegram'),
    }

    return {
        'status': 'ok',
        'latest_ingestion_time': {
            'total': await get_latest_ingestion_time(db),
            'services': ingestion_times,
            'earliest': min(filter(None, ingestion_times.values())) if any(ingestion_times.values()) else None,
            'latest': max(filter(None, ingestion_times.values())) if any(ingestion_times.values()) else None,
        }
    }
