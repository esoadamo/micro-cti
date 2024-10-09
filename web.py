import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from lark import ParseError
from starlette.templating import _TemplateResponse

from posts import get_latest_ingestion_time
from search import search_posts

app = FastAPI()
templates = Jinja2Templates(directory="templates")


def render_template(filename, request, **context):
    return templates.TemplateResponse(
        request=request, name=filename, context=context
    )


@app.get("/", response_class=HTMLResponse)
async def app_search(request: Request) -> _TemplateResponse:
    time_start = time.time()
    search_term = request.query_params.get('search', '')
    posts = []
    error = ""

    if search_term:
        try:
            posts = await search_posts(search_term)
        except ParseError as e:
            error = str(e)

    time_delta_ms = int(1000 * (time.time() - time_start))
    return render_template(
        'search.html',
        request,
        posts=posts,
        search_term=search_term,
        latest_ingestion_time=await get_latest_ingestion_time(),
        error=error,
        time_render=time_delta_ms
    )


@app.get("/favicon.svg", response_class=FileResponse)
async def favicon() -> FileResponse:
    return FileResponse('favicon.svg')
