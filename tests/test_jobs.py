import gzip
import importlib
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from models import Post, SearchCache

job_cache_expire = importlib.import_module("job-cache-expire")
job_filter_posts = importlib.import_module("job-filter-posts")
job_tag = importlib.import_module("job-tag")
job_parse_ioc = importlib.import_module("job-parse-ioc")
job_data_export = importlib.import_module("job-data-export")
job_telegram_list_channels = importlib.import_module("job-telegram-list-channels")


class MockConnectorContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        pass


@pytest.mark.asyncio
async def test_job_cache_expire_main(tmp_path, mock_db_session):
    cache_file = tmp_path / "old_cache.pickle.gz"
    cache_file.write_bytes(b"dummy")

    expired_entry = SearchCache(
        query_hash="hash1",
        query="test",
        filepath=cache_file.name,
        expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    mock_res = MagicMock()
    mock_res.all.return_value = [expired_entry]
    mock_db_session.exec.return_value = mock_res
    mock_db_session.delete = AsyncMock()

    ctx = MockConnectorContext(mock_db_session)
    with patch.object(job_cache_expire.DBConnector, "get", new=AsyncMock(return_value=ctx)), \
         patch.object(job_cache_expire, "DIR_CACHE", tmp_path):
        await job_cache_expire.main()

    assert not cache_file.exists()
    mock_db_session.delete.assert_awaited_once_with(expired_entry)
    mock_db_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_job_filter_posts_main(mock_db_session, sample_post):
    mock_res = MagicMock()
    mock_res.all.return_value = [sample_post]
    mock_db_session.exec.return_value = mock_res

    ctx = MockConnectorContext(mock_db_session)
    with patch.object(job_filter_posts.DBConnector, "get", new=MagicMock(return_value=ctx)), \
         patch.object(job_filter_posts, "hide_post_if_not_about_cybersecurity", new=AsyncMock(return_value=False)):
        await job_filter_posts.main()


@pytest.mark.asyncio
async def test_job_tag_main(mock_db_session):
    ctx = MockConnectorContext(mock_db_session)
    with patch.object(job_tag.DBConnector, "get", new=AsyncMock(return_value=ctx)), \
         patch.object(job_tag, "ingest_posts", new=AsyncMock()) as mock_ingest, \
         patch.object(job_tag, "generate_tags", new=AsyncMock()) as mock_gen_tags:
        code = await job_tag.main()

    assert code == 0
    mock_ingest.assert_awaited_once()
    mock_gen_tags.assert_awaited_once()


@pytest.mark.asyncio
async def test_job_parse_ioc_main(mock_db_session, sample_post):
    mock_res_has_posts = MagicMock()
    mock_res_has_posts.all.return_value = [sample_post]
    mock_res_empty = MagicMock()
    mock_res_empty.all.return_value = []
    mock_db_session.exec.side_effect = [mock_res_has_posts, mock_res_empty]

    ctx = MockConnectorContext(mock_db_session)
    mock_connector = MagicMock()
    mock_connector.get = AsyncMock(return_value=ctx)

    async def fake_parse_iocs(db, ids):
        yield "ioc-result"

    with patch.object(job_parse_ioc, "DBConnector", return_value=mock_connector), \
         patch.object(job_parse_ioc, "parse_iocs", side_effect=fake_parse_iocs):
        await job_parse_ioc.main()


@pytest.mark.asyncio
async def test_job_data_export_main(tmp_path, mock_db_session, sample_post):
    mock_res_posts = MagicMock()
    mock_res_posts.all.return_value = [sample_post]
    mock_res_empty = MagicMock()
    mock_res_empty.all.return_value = []
    mock_db_session.exec.side_effect = [mock_res_posts, mock_res_empty]

    ctx = MockConnectorContext(mock_db_session)
    with patch.object(job_data_export.DBConnector, "get", new=AsyncMock(return_value=ctx)), \
         patch.object(job_data_export, "DIR_BACKUP", tmp_path):
        await job_data_export.main()

    backup_file = tmp_path / "posts.jsonl.gz"
    assert backup_file.exists()
    with gzip.open(backup_file, "rt") as f:
        lines = f.readlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["id"] == sample_post.id
    assert data["source"] == sample_post.source


@pytest.mark.asyncio
async def test_job_telegram_list_channels_main(capsys):
    mock_client = MagicMock()
    mock_dialog1 = MagicMock()
    mock_dialog1.name = "Included Channel"
    mock_dialog2 = MagicMock()
    mock_dialog2.name = "Excluded Channel"

    mock_client.get_dialogs = AsyncMock(return_value=[mock_dialog1, mock_dialog2])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock()

    with patch.object(job_telegram_list_channels, "get_telegram_instance", return_value=(mock_client, {"Included Channel"})):
        await job_telegram_list_channels.main()

    captured = capsys.readouterr()
    assert "Included Channel" in captured.out
    assert "Excluded Channel" in captured.out
