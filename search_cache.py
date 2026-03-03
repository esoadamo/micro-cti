import gzip
import pickle
from hashlib import sha256
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import Post, SearchCache

from directories import DIR_CACHE


def _cache_query_hash(query: str) -> str:
    return sha256(query.encode('utf8')).hexdigest()


async def cache_fetch(query: str, db: AsyncSession, max_expiration: datetime = datetime.now(tz=timezone.utc)) -> Optional[List[Tuple[Post, any]]]:
    stmt = select(SearchCache).where(SearchCache.query_hash == _cache_query_hash(query)).limit(1)
    res = await db.exec(stmt)
    existing_cache = res.first()
    if existing_cache and existing_cache.expires_at.replace(tzinfo=timezone.utc) > max_expiration:
        path_cache = DIR_CACHE.joinpath(existing_cache.filepath)
        if path_cache.exists():
            with gzip.open(path_cache, 'rb') as f:
                return pickle.load(f)
    return None


async def cache_save(query: str, posts: List[Tuple[Post, int]], expiration: datetime, db: AsyncSession) -> None:
    stmt = select(SearchCache).where(SearchCache.query_hash == _cache_query_hash(query)).limit(1)
    res = await db.exec(stmt)
    existing = res.first()
    if existing:
        return

    query_hash = _cache_query_hash(query)
    path_cache = DIR_CACHE.joinpath(f'{expiration.timestamp()}_{query_hash}.pickle.gz')
    path_cache.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path_cache, 'wb') as f:
        f.write(pickle.dumps(posts))
        
    db.add(SearchCache(
        query_hash=query_hash,
        expires_at=expiration,
        filepath=path_cache.name,
        query=query,
    ))
    await db.commit()
