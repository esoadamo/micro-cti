import time
from datetime import datetime
from email.utils import format_datetime as format_rfc2822
from typing import List, Optional
from typing_extensions import TypedDict

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from lark import ParseError
# noinspection PyPackageRequirements,PyProtectedMember
from starlette.templating import _TemplateResponse

from ioc import search_iocs, IoCLink
from posts import get_latest_ingestion_time
from search import search_posts

app = FastAPI()
templates = Jinja2Templates(directory="templates")


class IoCSearchResponse(TypedDict):
    search_term: str
    iocs: List[IoCLink]
    latest_ingestion_time: Optional[datetime]


def render_template(filename, request, headers=None, **context):
    return templates.TemplateResponse(
        request=request, name=filename, context=context,
        headers=headers
    )


@app.get("/", response_class=HTMLResponse)
@app.get("/search/", response_class=HTMLResponse)
async def app_search(request: Request, q: str = "") -> _TemplateResponse:
    time_start = time.time()
    search_term = q
    posts = []
    search_back_data = {}
    error = ""

    if search_term:
        try:
            posts = await search_posts(search_term, back_data=search_back_data)
        except ParseError as e:
            error = str(e)

    time_delta_ms = int(1000 * (time.time() - time_start))
    return render_template(
        'search_posts.html',
        request,
        results=posts,
        search_term=search_term,
        latest_ingestion_time=await get_latest_ingestion_time(),
        error=error,
        time_render=time_delta_ms,
        search_count=search_back_data.get('cnt_search', 0)
    )


@app.get("/ioc/search/")
async def app_search(q: str) -> IoCSearchResponse:
    search_term = q
    iocs = await search_iocs(search_term)
    return {
        'search_term': search_term,
        'iocs': iocs,
        'latest_ingestion_time': await get_latest_ingestion_time(),
    }


@app.get("/rss/", response_class=PlainTextResponse)
async def app_search(request: Request, q: str = "") -> _TemplateResponse:
    search_term = q
    posts = []

    if search_term:
        posts = await search_posts(search_term)

    return render_template(
        'rss.xml',
        request,
        headers={"Content-Type": "application/rss+xml"},
        posts=posts,
        search_term=search_term,
        url=request.url,
        latest_ingestion_time=await get_latest_ingestion_time(),
        format_rfc2822=format_rfc2822
    )


@app.get("/favicon.svg", response_class=FileResponse)
async def favicon() -> FileResponse:
    return FileResponse('favicon.svg')
