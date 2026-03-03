import asyncio
from datetime import datetime, timezone

from db import DBConnector
from models import SearchCache
from sqlmodel import select

from directories import DIR_CACHE


async def main() -> None:
    async with (await DBConnector.get()) as db:
        stmt = select(SearchCache).where(SearchCache.expires_at < datetime.now(tz=timezone.utc))
        res = await db.exec(stmt)
        expired = res.all()
        for i, cache in enumerate(expired):
            print(f'[*] {i+1}/{len(expired)}', cache)
            path_cache = DIR_CACHE / cache.filepath
            path_cache.unlink(missing_ok=True)
            await db.delete(cache)
        await db.commit()

if __name__ == "__main__":
    asyncio.run(main())
