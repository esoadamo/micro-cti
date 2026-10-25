from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import pytest

from models import Post
from post.exception import FetchError
from post.telegram import get_telegram_secrets, get_telegram_instance, get_telegram_posts


def test_get_telegram_secrets():
    toml_data = b'[telegram]\napi_id=12345\napi_hash="hash"\nchats=["CTI Channel"]\n'
    with patch("builtins.open", mock_open(read_data=toml_data)):
        secrets = get_telegram_secrets()
    assert secrets["api_id"] == 12345
    assert secrets["chats"] == ["CTI Channel"]


def test_get_telegram_secrets_missing():
    toml_data = b'[empty]\n'
    with patch("builtins.open", mock_open(read_data=toml_data)):
        secrets = get_telegram_secrets()
    assert secrets is None


def test_get_telegram_instance():
    secrets = {"api_id": 9999, "api_hash": "testhash", "chats": ["Channel 1", "Channel 2"]}
    with patch("post.telegram.get_telegram_secrets", return_value=secrets), \
         patch("post.telegram.TelegramClient") as mock_client:
        inst, chats = get_telegram_instance()
        assert chats == {"Channel 1", "Channel 2"}
        mock_client.assert_called_once()


@pytest.mark.asyncio
async def test_get_telegram_posts_unconfigured_tuple(mock_db_session):
    with patch("post.telegram.get_telegram_instance", return_value=(None, set())):
        posts = []
        async for post in get_telegram_posts(mock_db_session):
            posts.append(post)
    assert posts == []


@pytest.mark.asyncio
async def test_get_telegram_posts_unconfigured_none(mock_db_session):
    with patch("post.telegram.get_telegram_instance", return_value=None):
        with pytest.raises(TypeError):
            async for _ in get_telegram_posts(mock_db_session):
                pass


@pytest.mark.asyncio
async def test_get_telegram_posts_success(mock_db_session):
    mock_msg = MagicMock()
    mock_msg.id = 55
    mock_msg.text = "New malware IOC detected: evil.com"
    mock_msg.date = datetime(2024, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_msg.sender_id = 12345

    mock_dialog = MagicMock()
    mock_dialog.name = "Cyber Intel"
    mock_dialog.unread_count = 1
    mock_dialog.entity = MagicMock()
    mock_dialog.entity.id = 1001

    async def fake_iter_dialogs():
        yield mock_dialog

    async def fake_iter_messages(entity, limit):
        yield mock_msg

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock()
    mock_client.iter_dialogs = fake_iter_dialogs
    mock_client.iter_messages = fake_iter_messages
    mock_client.send_read_acknowledge = AsyncMock()

    mock_res = MagicMock()
    mock_res.first.return_value = None  # New post, not in DB
    mock_db_session.exec.return_value = mock_res

    with patch("post.telegram.get_telegram_instance", return_value=(mock_client, {"Cyber Intel"})):
        posts = []
        async for post in get_telegram_posts(mock_db_session):
            posts.append(post)

    assert len(posts) == 1
    p = posts[0]
    assert p.source == "telegram"
    assert p.source_id == "55"
    assert p.user == "Cyber Intel"
    assert "New malware IOC detected: evil.com" in p.content_txt
    mock_client.send_read_acknowledge.assert_awaited_once_with(mock_dialog.entity)
    mock_db_session.commit.assert_awaited()
