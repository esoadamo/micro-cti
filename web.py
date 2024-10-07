from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from posts import search_posts, get_latest_ingestion_time

app = FastAPI()
templates = Jinja2Templates(directory="templates")


def render_template(filename, request, **context):
    return templates.TemplateResponse(
        request=request, name=filename, context=context
    )


@app.get("/", response_class=HTMLResponse)
async def app_search(request: Request) -> str:
    search_term = request.query_params.get('search', '')
    posts = []

    if search_term:
        posts = await search_posts(search_term)

    return render_template('search.html', request, posts=posts, search_term=search_term, latest_ingestion_time=await get_latest_ingestion_time())


@app.get("/favicon.svg", response_class=FileResponse)
async def favicon() -> FileResponse:
    return FileResponse('favicon.svg')
