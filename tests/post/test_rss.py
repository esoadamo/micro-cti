from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import pytest

from models import Post
from post.exception import FetchError
from post.rss import get_rss_feeds, get_rss_posts


class FeedEntry(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def test_get_rss_feeds_success():
    toml_data = b'[rss.reddit]\nname="reddit_sec"\nurl="https://reddit.com/r/netsec.rss"\n'
    with patch("builtins.open", mock_open(read_data=toml_data)):
        feeds = get_rss_feeds()
    assert len(feeds) == 1
    assert feeds[0]["name"] == "reddit_sec"
    assert feeds[0]["url"] == "https://reddit.com/r/netsec.rss"


def test_get_rss_feeds_empty():
    toml_data = b'[other_section]\n'
    with patch("builtins.open", mock_open(read_data=toml_data)):
        feeds = get_rss_feeds()
    assert feeds == []


@pytest.mark.asyncio
async def test_get_rss_posts_success(mock_db_session):
    feed_config = [{"name": "reddit_sec", "url": "https://reddit.com/r/netsec.rss"}]

    mock_entry = FeedEntry({
        "published": datetime.now(tz=timezone.utc).isoformat(),
        "author": "reddit_user",
        "link": "https://reddit.com/r/netsec/comments/123",
        "title": "Critical RCE Analysis",
        "summary": "Full writeup on remote code execution in open source library.",
    })

    mock_feed_data = MagicMock()
    mock_feed_data.entries = [mock_entry]

    # DB mocks
    mock_res_max = MagicMock()
    mock_res_max.first.return_value = None
    mock_res_exist = MagicMock()
    mock_res_exist.first.return_value = None
    mock_db_session.exec.side_effect = [mock_res_max, mock_res_exist]

    with patch("post.rss.get_rss_feeds", return_value=feed_config), \
         patch("feedparser.parse", return_value=mock_feed_data), \
         patch("asyncio.sleep", new=AsyncMock()):
        posts = []
        async for post in get_rss_posts(mock_db_session):
            posts.append(post)

    assert len(posts) == 1
    p = posts[0]
    assert p.source == "reddit_sec"
    assert p.source_id == "https://reddit.com/r/netsec/comments/123"
    assert p.user == "reddit_user"
    assert "Critical RCE Analysis" in p.content_txt
    mock_db_session.commit.assert_awaited()
