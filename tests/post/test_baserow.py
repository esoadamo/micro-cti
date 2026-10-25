from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import pytest

from models import Post
from post.exception import FetchError
from post.baserow import get_baserow_secrets, get_baserow_posts


def test_get_baserow_secrets():
    toml_data = b'[baserow]\nbase_url="https://api.baserow.io"\napi_key="token"\ntable_id="123"\n'
    with patch("builtins.open", mock_open(read_data=toml_data)):
        secrets = get_baserow_secrets()
    assert secrets["base_url"] == "https://api.baserow.io"
    assert secrets["api_key"] == "token"
    assert secrets["table_id"] == "123"


@pytest.mark.asyncio
async def test_get_baserow_posts_unconfigured(mock_db_session):
    with patch("post.baserow.get_baserow_secrets", return_value=None):
        posts = []
        async for post in get_baserow_posts(mock_db_session):
            posts.append(post)
    assert posts == []


@pytest.mark.asyncio
async def test_get_baserow_posts_success(mock_db_session):
    secrets = {
        "base_url": "https://baserow.example",
        "api_key": "sec_token",
        "table_id": "42",
    }
    mock_get_resp = MagicMock()
    mock_get_resp.json.return_value = {
        "results": [
            {
                "id": 99,
                "created_on": "2024-08-25T15:00:00Z",
                "Account": "baserow_reporter",
                "Content": "Discovered new phishing kit clone",
                "Link": "https://intel.local/report/99",
                "Source": "custom_feed",
                "Id": "99",
            }
        ]
    }
    mock_get_resp.raise_for_status = MagicMock()

    mock_del_resp = MagicMock()
    mock_del_resp.raise_for_status = MagicMock()

    mock_res = MagicMock()
    mock_res.first.return_value = None
    mock_db_session.exec.return_value = mock_res

    with patch("post.baserow.get_baserow_secrets", return_value=secrets), \
         patch("requests.get", return_value=mock_get_resp), \
         patch("requests.delete", return_value=mock_del_resp) as mock_delete:
        posts = []
        async for post in get_baserow_posts(mock_db_session):
            posts.append(post)

    assert len(posts) == 1
    p = posts[0]
    assert p.source == "custom_feed"
    assert p.source_id == "99"
    assert p.user == "baserow_reporter"
    assert "Discovered new phishing kit clone" in p.content_txt
    mock_delete.assert_called_once_with(
        "https://baserow.example/database/rows/table/42/99/",
        headers={"Authorization": "Token sec_token", "Content-Type": "application/json"},
    )
    mock_db_session.commit.assert_awaited()
