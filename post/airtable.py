import json
import tomllib
from datetime import datetime, timezone
from typing import AsyncIterable, Optional

import pyairtable
from prisma import Prisma
from prisma.models import Post

from directories import FILE_CONFIG


class FetchError(Exception):
    def __init__(self, message: str, source: list[Exception]):
        super().__init__(message)
        self.source = source


def get_airtable_secrets() -> Optional[dict]:
    try:
        with open(FILE_CONFIG, 'rb') as f:
            return tomllib.load(f)["airtable"]
    except KeyError:
        return None


def get_airtable_instance() -> Optional[pyairtable.Table]:
    secrets = get_airtable_secrets()
    if secrets is None:
        return None
    api = pyairtable.Api(secrets["api_key"])
    return api.table(secrets["base_id"], secrets["table_id"])


async def get_airtable_posts(db: Prisma) -> AsyncIterable[Post]:
    try:
        airtable = get_airtable_instance()
        if airtable is None:
            return

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
