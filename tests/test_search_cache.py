import gzip
import pickle
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from models import SearchCache
from search_cache import _cache_query_hash, cache_fetch, cache_save


def test_cache_query_hash():
    h1 = _cache_query_hash("malware")
    h2 = _cache_query_hash("malware")
    h3 = _cache_query_hash("phishing")

    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256 hex string


@pytest.mark.asyncio
async def test_cache_fetch_hit(tmp_path, sample_post):
    query = "ransomware"
    now = datetime.now(tz=timezone.utc)
    future = now + timedelta(hours=2)

    cached_data = [(sample_post, {"relevancy_score": 95})]
    filename = "test_cache.pickle.gz"
    cache_file = tmp_path / filename

    with gzip.open(cache_file, "wb") as f:
        pickle.dump(cached_data, f)

    db_cache_entry = SearchCache(
        query_hash=_cache_query_hash(query),
        query=query,
        filepath=filename,
        expires_at=future,
    )

    mock_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.first.return_value = db_cache_entry
    mock_db.exec.return_value = mock_res

    with patch("search_cache.DIR_CACHE", tmp_path):
        result = await cache_fetch(query, mock_db, max_expiration=now)

    assert result is not None
    assert len(result) == 1
    assert result[0][0].id == sample_post.id
    assert result[0][1]["relevancy_score"] == 95


@pytest.mark.asyncio
async def test_cache_fetch_expired(tmp_path):
    query = "apt29"
    now = datetime.now(tz=timezone.utc)
    past = now - timedelta(hours=1)

    db_cache_entry = SearchCache(
        query_hash=_cache_query_hash(query),
        query=query,
        filepath="expired.pickle.gz",
        expires_at=past,
    )

    mock_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.first.return_value = db_cache_entry
    mock_db.exec.return_value = mock_res

    with patch("search_cache.DIR_CACHE", tmp_path):
        result = await cache_fetch(query, mock_db, max_expiration=now)

    assert result is None


@pytest.mark.asyncio
async def test_cache_fetch_miss():
    mock_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.first.return_value = None
    mock_db.exec.return_value = mock_res

    result = await cache_fetch("unknown query", mock_db)
    assert result is None


@pytest.mark.asyncio
async def test_cache_fetch_file_missing(tmp_path):
    query = "cve-2024"
    future = datetime.now(tz=timezone.utc) + timedelta(hours=1)

    db_cache_entry = SearchCache(
        query_hash=_cache_query_hash(query),
        query=query,
        filepath="nonexistent.pickle.gz",
        expires_at=future,
    )

    mock_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.first.return_value = db_cache_entry
    mock_db.exec.return_value = mock_res

    with patch("search_cache.DIR_CACHE", tmp_path):
        result = await cache_fetch(query, mock_db)

    assert result is None


@pytest.mark.asyncio
async def test_cache_save_new_entry(tmp_path, sample_post):
    query = "zero-day"
    expiration = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    posts = [(sample_post, 90)]

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_res = MagicMock()
    mock_res.first.return_value = None  # Not existing
    mock_db.exec.return_value = mock_res

    with patch("search_cache.DIR_CACHE", tmp_path):
        await cache_save(query, posts, expiration, mock_db)

    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()

    # Check that file on disk was created and contains the gzipped pickled data
    added_entry = mock_db.add.call_args[0][0]
    assert isinstance(added_entry, SearchCache)
    assert added_entry.query_hash == _cache_query_hash(query)
    saved_file = tmp_path / added_entry.filepath
    assert saved_file.exists()

    with gzip.open(saved_file, "rb") as f:
        loaded = pickle.load(f)
    assert len(loaded) == 1
    assert loaded[0][0].id == sample_post.id


@pytest.mark.asyncio
async def test_cache_save_existing_entry(tmp_path, sample_post):
    query = "already_cached"
    expiration = datetime.now(tz=timezone.utc) + timedelta(hours=1)

    mock_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.first.return_value = SearchCache(
        query_hash=_cache_query_hash(query),
        query=query,
        filepath="existing.pickle.gz",
        expires_at=expiration,
    )
    mock_db.exec.return_value = mock_res

    with patch("search_cache.DIR_CACHE", tmp_path):
        await cache_save(query, [(sample_post, 80)], expiration, mock_db)

    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_awaited()
