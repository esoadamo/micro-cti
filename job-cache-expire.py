import asyncio
from datetime import datetime, timezone

from db import get_db
from prisma import SearchCacheMeta

from directories import DIR_CACHE


async def main() -> None:
    db = await get_db()
    expired = await SearchCacheMeta.prisma(client=db).find_many(where={'expires_at': {'lt': datetime.now(tz=timezone.utc)}})
    for i, cache in enumerate(expired):
        print(f'[*] {i+1}/{len(expired)}', cache)
        path_cache = DIR_CACHE / cache.filepath
        path_cache.unlink(missing_ok=True)
        await db.searchcache.delete(where={'id': cache.id})
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
