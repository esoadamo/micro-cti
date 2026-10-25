from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import pytest

from models import Post
from post.exception import FetchError
from post.airtable import get_airtable_secrets, get_airtable_instance, get_airtable_posts


def test_get_airtable_secrets():
    toml_data = b'[airtable]\napi_key="key"\nbase_id="base"\ntable_id="tbl"\n'
    with patch("builtins.open", mock_open(read_data=toml_data)):
        secrets = get_airtable_secrets()
    assert secrets["api_key"] == "key"
    assert secrets["base_id"] == "base"


def test_get_airtable_instance():
    secrets = {"api_key": "k", "base_id": "b", "table_id": "t"}
    with patch("post.airtable.get_airtable_secrets", return_value=secrets), \
         patch("pyairtable.Api") as mock_api:
        table = get_airtable_instance()
        mock_api.assert_called_once_with("k")


@pytest.mark.asyncio
async def test_get_airtable_posts_unconfigured(mock_db_session):
    with patch("post.airtable.get_airtable_instance", return_value=None):
        posts = []
        async for post in get_airtable_posts(mock_db_session):
            posts.append(post)
    assert posts == []


@pytest.mark.asyncio
async def test_get_airtable_posts_success(mock_db_session):
    mock_table = MagicMock()
    mock_record = {
        "id": "rec123",
        "createdTime": "2024-08-25T14:30:00Z",
        "fields": {
            "Account": "threat_analyst",
            "Content": "Suspicious domain seen resolving to known bulletproof host",
            "Link": "https://threat.example/report/1",
            "Source": "airtable_queue",
            "Id": 1001,
        },
    }
    mock_table.all.return_value = [mock_record]
    mock_table.delete = MagicMock()

    mock_res = MagicMock()
    mock_res.first.return_value = None
    mock_db_session.exec.return_value = mock_res

    with patch("post.airtable.get_airtable_instance", return_value=mock_table):
        posts = []
        async for post in get_airtable_posts(mock_db_session):
            posts.append(post)

    assert len(posts) == 1
    p = posts[0]
    assert p.source == "airtable_queue"
    assert p.source_id == "1001"
    assert p.user == "threat_analyst"
    assert "Suspicious domain" in p.content_txt
    mock_table.delete.assert_called_once_with("rec123")
    mock_db_session.commit.assert_awaited()
