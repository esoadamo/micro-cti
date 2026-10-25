from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from models import Post, Tag
from post import (
    _should_generate_ai_tags,
    ingest_posts,
    generate_tags,
    hide_post_if_not_about_cybersecurity,
    get_latest_ingestion_time,
    FetchError,
)
from ai import CybersecurityPostAssessment


def test_should_generate_ai_tags():
    # Content too short (< 15 words)
    short_content = "This is a short post about hacking."
    assert _should_generate_ai_tags(short_content) is False

    # Content long enough, but already has 3 or more hashtags
    content_with_tags = (
        "Here is a longer threat intelligence report explaining a complex attack vector "
        "affecting multiple critical infrastructure servers across the globe #cyber #malware #apt"
    )
    assert _should_generate_ai_tags(content_with_tags) is False

    # Content long enough with fewer than 3 hashtags -> needs AI tags
    content_needing_tags = (
        "Here is a longer threat intelligence report explaining a complex attack vector "
        "affecting multiple critical infrastructure servers across the globe #cyber"
    )
    assert _should_generate_ai_tags(content_needing_tags) is True


@pytest.mark.asyncio
async def test_ingest_posts_keyword_match(mock_db_session):
    # Post containing 'phishing' whitelist keyword
    post = Post(
        id=1,
        source="rss",
        user="test",
        created_at=datetime.now(tz=timezone.utc),
        fetched_at=datetime.now(tz=timezone.utc),
        url="http://example.com/1",
        content_html="Phishing campaign detected",
        content_txt="Phishing campaign detected targeting financial institutions",
        raw="{}",
        is_ingested=False,
        is_hidden=True,
    )
    mock_res = MagicMock()
    mock_res.all.return_value = [post]
    mock_db_session.exec.return_value = mock_res

    with patch("post.format_post_for_search", new=AsyncMock()):
        await ingest_posts(mock_db_session, ids=[1])

    assert post.is_ingested is True
    assert post.is_hidden is False  # Marked visible because of keyword match
    mock_db_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_ingest_posts_ai_classification(mock_db_session):
    # Post with no whitelist keyword
    post = Post(
        id=2,
        source="mastodon",
        user="test",
        created_at=datetime.now(tz=timezone.utc),
        fetched_at=datetime.now(tz=timezone.utc),
        url="http://example.com/2",
        content_html="Random non-keyword text",
        content_txt="We observed unusual network anomalies on port 443 with beaconing",
        raw="{}",
        is_ingested=False,
        is_hidden=True,
    )
    mock_res = MagicMock()
    mock_res.all.return_value = [post]
    mock_db_session.exec.return_value = mock_res

    ai_assessment = CybersecurityPostAssessment(is_cybersecurity=True, tags=["#beaconing"])

    with patch("post.prompt_classify_and_tag_posts_batch", new=AsyncMock(return_value=[ai_assessment])), \
         patch("post.format_post_for_search", new=AsyncMock()):
        precomputed = {}
        await ingest_posts(mock_db_session, ids=[2], precomputed_tags=precomputed)

    assert post.is_ingested is True
    assert post.is_hidden is False


@pytest.mark.asyncio
async def test_generate_tags_with_precomputed(mock_db_session):
    post = Post(
        id=10,
        source="rss",
        user="test",
        created_at=datetime.now(tz=timezone.utc),
        fetched_at=datetime.now(tz=timezone.utc),
        url="http://example.com/10",
        content_html="text",
        content_txt="Word " * 20 + "#native_tag",
        raw="{}",
        tags_assigned=False,
        is_hidden=False,
        tags=[],
    )
    mock_res = MagicMock()
    mock_res.all.return_value = [post]

    # When querying Tag by name: return None (new tag)
    tag_res = MagicMock()
    tag_res.first.return_value = None

    mock_db_session.exec.side_effect = [mock_res, tag_res, tag_res]

    precomputed = {10: ["#AI_TAG"]}
    with patch("post.format_post_for_search", new=AsyncMock()):
        await generate_tags(mock_db_session, ids=[10], precomputed_tags=precomputed)

    assert post.tags_assigned is True
    assert len(post.tags) >= 1
    mock_db_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_hide_post_if_not_about_cybersecurity_keyword(mock_db_session, sample_post):
    sample_post.content_txt = "New vulnerability patched in web server"
    sample_post.is_hidden = True

    visible = await hide_post_if_not_about_cybersecurity(sample_post, mock_db_session, force_ai=False)
    assert visible is True
    assert sample_post.is_hidden is False


@pytest.mark.asyncio
async def test_hide_post_if_not_about_cybersecurity_ai(mock_db_session, sample_post):
    sample_post.content_txt = "Delicious apple pie recipe for the weekend"
    sample_post.is_hidden = False

    with patch("post.prompt_check_cybersecurity_post", new=AsyncMock(return_value=False)):
        visible = await hide_post_if_not_about_cybersecurity(sample_post, mock_db_session, force_ai=True)

    assert visible is False
    assert sample_post.is_hidden is True


@pytest.mark.asyncio
async def test_get_latest_ingestion_time(mock_db_session, sample_post):
    mock_res = MagicMock()
    mock_res.first.return_value = sample_post
    mock_db_session.exec.return_value = mock_res

    latest_time = await get_latest_ingestion_time(mock_db_session, source="mastodon")
    assert latest_time == sample_post.fetched_at


@pytest.mark.asyncio
async def test_get_latest_ingestion_time_none(mock_db_session):
    mock_res = MagicMock()
    mock_res.first.return_value = None
    mock_db_session.exec.return_value = mock_res

    latest_time = await get_latest_ingestion_time(mock_db_session)
    assert latest_time is None
