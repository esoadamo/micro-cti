from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import pytest

from models import Post
from post.exception import FetchError
from post.bluesky import get_bluesky_secrets, get_bluesky_instance, get_bluesky_posts


class BskyItem(dict):
    def __init__(self, post):
        super().__init__()
        self.post = post


def test_get_bluesky_secrets():
    toml_data = b'[bluesky]\nhandle="user.bsky.social"\napp_password="secret"\nfeeds=["feed1"]\n'
    with patch("builtins.open", mock_open(read_data=toml_data)):
        secrets = get_bluesky_secrets()
    assert secrets["handle"] == "user.bsky.social"
    assert secrets["feeds"] == ["feed1"]


def test_get_bluesky_secrets_missing():
    with patch("builtins.open", mock_open(read_data=b"[empty]\n")):
        assert get_bluesky_secrets() is None


@pytest.mark.asyncio
async def test_get_bluesky_instance_unconfigured():
    with patch("post.bluesky.get_bluesky_secrets", return_value=None):
        inst = await get_bluesky_instance(cache={})
    assert inst is None


@pytest.mark.asyncio
async def test_get_bluesky_instance_configured():
    secrets = {"handle": "h", "app_password": "p", "feeds": ["f1"]}
    mock_client = AsyncMock()
    mock_client.login = AsyncMock()

    with patch("post.bluesky.get_bluesky_secrets", return_value=secrets), \
         patch("atproto.AsyncClient", return_value=mock_client):
        client, feeds = await get_bluesky_instance(cache={})
        assert client is mock_client
        assert feeds == ["f1"]
        mock_client.login.assert_awaited_once_with("h", "p")


@pytest.mark.asyncio
async def test_get_bluesky_posts_success(mock_db_session):
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    mock_post_inner = MagicMock()
    mock_post_inner.author.handle = "threat_intel.bsky.social"
    mock_post_inner.record.text = "New zero-day in browser engine"
    mock_post_inner.record.created_at = now_iso
    mock_post_inner.cid = "bafytestcid123"
    mock_post_inner.uri = "at://did:plc:123/app.bsky.feed.post/rkey456"

    mock_item = BskyItem(mock_post_inner)

    # Old item to terminate the pagination loop
    mock_old_post = MagicMock()
    mock_old_post.author.handle = "threat_intel.bsky.social"
    mock_old_post.record.text = "Old post"
    mock_old_post.record.created_at = "2020-01-01T00:00:00Z"
    mock_old_post.cid = "oldcid"
    mock_old_post.uri = "at://did:plc:123/app.bsky.feed.post/old"
    old_item = BskyItem(mock_old_post)

    mock_response = MagicMock()
    mock_response.cursor = None
    mock_response.feed = [mock_item, old_item]

    mock_client = MagicMock()
    mock_client.app.bsky.feed.get_feed = AsyncMock(return_value=mock_response)

    # DB mocks
    mock_res_max = MagicMock()
    mock_res_max.first.return_value = None
    mock_res_exist = MagicMock()
    mock_res_exist.first.return_value = None
    mock_db_session.exec.side_effect = [mock_res_max, mock_res_exist]

    with patch("post.bluesky.get_bluesky_instance", new=AsyncMock(return_value=(mock_client, ["feed1"]))), \
         patch("asyncio.sleep", new=AsyncMock()):
        posts = []
        async for post in get_bluesky_posts(mock_db_session):
            posts.append(post)

    assert len(posts) == 1
    p = posts[0]
    assert p.source == "bluesky"
    assert p.source_id == "bafytestcid123"
    assert p.user == "threat_intel.bsky.social"
    assert "New zero-day in browser engine" in p.content_txt
    assert "https://bsky.app/profile/threat_intel.bsky.social/post/rkey456" == p.url
    mock_db_session.commit.assert_awaited()
