from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import pytest

from models import Post
from post.exception import FetchError
from post.mastodon import get_mastodon_secrets, get_mastodon_instance, get_mastodon_posts


def test_get_mastodon_secrets_success():
    toml_data = b'[mastodon]\nclient_id="cid"\nclient_secret="csec"\naccess_token="tok"\napi_base_url="https://mastodon.social"\n'
    with patch("builtins.open", mock_open(read_data=toml_data)):
        secrets = get_mastodon_secrets()
    assert secrets["client_id"] == "cid"
    assert secrets["api_base_url"] == "https://mastodon.social"


def test_get_mastodon_secrets_missing():
    toml_data = b'[other_section]\nfoo="bar"\n'
    with patch("builtins.open", mock_open(read_data=toml_data)):
        secrets = get_mastodon_secrets()
    assert secrets is None


def test_get_mastodon_instance_unconfigured():
    with patch("post.mastodon.get_mastodon_secrets", return_value=None):
        instance = get_mastodon_instance()
    assert instance is None


def test_get_mastodon_instance_configured():
    secrets = {
        "client_id": "cid",
        "client_secret": "csec",
        "access_token": "tok",
        "api_base_url": "https://masto.example",
    }
    with patch("post.mastodon.get_mastodon_secrets", return_value=secrets), \
         patch("post.mastodon.Mastodon") as mock_mastodon_cls:
        instance = get_mastodon_instance()
        assert instance is not None
        mock_mastodon_cls.assert_called_once_with(
            client_id="cid",
            client_secret="csec",
            access_token="tok",
            api_base_url="https://masto.example",
        )


@pytest.mark.asyncio
async def test_get_mastodon_posts_unconfigured(mock_db_session):
    with patch("post.mastodon.get_mastodon_instance", return_value=None):
        posts = []
        async for post in get_mastodon_posts(mock_db_session):
            posts.append(post)
    assert posts == []


@pytest.mark.asyncio
async def test_get_mastodon_posts_yields_new(mock_db_session):
    mock_mastodon = MagicMock()
    mock_mastodon.ratelimit_remaining = 100
    mock_status = {
        "id": 999,
        "content": "<p>Security alert on Mastodon network</p>",
        "account": {"acct": "sec_analyst"},
        "url": "https://mastodon.social/@sec_analyst/999",
        "uri": "https://mastodon.social/@sec_analyst/999",
        "created_at": datetime(2024, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
    }
    mock_mastodon.timeline_home.side_effect = [[mock_status], []]

    # DB returns None for max_post query and None for existing post query
    mock_res = MagicMock()
    mock_res.first.return_value = None
    mock_db_session.exec.return_value = mock_res

    with patch("post.mastodon.get_mastodon_instance", return_value=mock_mastodon), \
         patch("asyncio.sleep", new=AsyncMock()):
        posts = []
        async for post in get_mastodon_posts(mock_db_session, min_id=100):
            posts.append(post)

    assert len(posts) == 1
    p = posts[0]
    assert p.source == "mastodon"
    assert p.source_id == "999"
    assert p.user == "sec_analyst"
    assert "Security alert on Mastodon network" in p.content_txt
    mock_db_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_get_mastodon_posts_error_raises_fetch_error(mock_db_session):
    mock_mastodon = MagicMock()
    mock_mastodon.timeline_home.side_effect = RuntimeError("API down")

    with patch("post.mastodon.get_mastodon_instance", return_value=mock_mastodon):
        with pytest.raises(FetchError) as exc_info:
            async for _ in get_mastodon_posts(mock_db_session, min_id=1):
                pass
        assert "Error fetching Mastodon posts" in str(exc_info.value)
