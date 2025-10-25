import gzip
import pickle
from hashlib import sha256
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from prisma import Prisma
from prisma.models import Post

from directories import DIR_CACHE


def _cache_query_hash(query: str) -> str:
    return sha256(query.encode('utf8')).hexdigest()


async def cache_fetch(query: str, db: Prisma, max_expiration: datetime = datetime.now(tz=timezone.utc)) -> Optional[List[Tuple[Post, any]]]:
    existing_cache = await db.searchcache.find_unique(where={'query_hash': _cache_query_hash(query)})
    if existing_cache and existing_cache.expires_at > max_expiration:
        path_cache = DIR_CACHE.joinpath(existing_cache.filepath)
        if path_cache.exists():
            with gzip.open(path_cache, 'rb') as f:
                return pickle.load(f)
    return None


async def cache_save(query: str, posts: List[Tuple[Post, int]], expiration: datetime, db: Prisma) -> None:
    existing = await db.searchcache.find_unique(where={'query_hash': _cache_query_hash(query)})
    if existing:
        return

    query_hash = _cache_query_hash(query)
    path_cache = DIR_CACHE.joinpath(f'{expiration.timestamp()}_{query_hash}.pickle.gz')
    path_cache.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path_cache, 'wb') as f:
        f.write(pickle.dumps(posts))
    await db.searchcache.create(data={
        'query_hash': query_hash,
        'expires_at': expiration,
        'filepath': path_cache.name,
        'query': query,
    })
