import json
import tomllib
from datetime import datetime, timezone
from typing import AsyncIterable, Optional

import requests
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from models import Post

from directories import FILE_CONFIG

from .exception import FetchError


def get_baserow_secrets() -> Optional[dict]:
    try:
        with open(FILE_CONFIG, 'rb') as f:
            return tomllib.load(f)["baserow"]
    except KeyError:
        return None


async def get_baserow_posts(db: AsyncSession) -> AsyncIterable[Post]:
    try:
        secrets = get_baserow_secrets()
        if secrets is None:
            return
        table_id = secrets["table_id"]
        base_url = secrets["base_url"]
        api_key = secrets["api_key"]

        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json"
        }

        response = requests.get(f"{base_url}/database/rows/table/{table_id}/?user_field_names=true", headers=headers)
        response.raise_for_status()
        results = response.json()['results']

        for row in results:
            row_id = row["id"]
            created_at = datetime.fromisoformat(row["created_on"]) if "created_on" in row else datetime.now(
                tz=timezone.utc)

            try:
                user = row.get("Account", "")
                content_text = content_html = row.get("Content", "")
                url = row.get("Link", "")
                source = row.get("Source", "baserow")
                source_id = str(row.get("Id", row_id))
                raw = json.dumps(row)
            except (KeyError, TypeError):
                continue

            stmt = select(Post).where(Post.source == source, Post.source_id == source_id).limit(1)
            res = await db.exec(stmt)
            if not res.first():
                post = Post(
                    source=source,
                    source_id=source_id,
                    user=user,
                    url=url,
                    created_at=created_at,
                    fetched_at=datetime.now(tz=timezone.utc),
                    content_html=content_html,
                    content_txt=content_text,
                    is_ingested=len(content_text.split()) < 3,
                    raw=raw
                )
                db.add(post)
                await db.commit()
                await db.refresh(post)
                yield post
            # Delete the row after processing (similar to Airtable behavior)
            requests.delete(f"{base_url}/database/rows/table/{table_id}/{row_id}/", headers=headers).raise_for_status()
    except Exception as e:
        raise FetchError("Error fetching Baserow posts", [e])
