import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure mistralai compatibility if version doesn't expose models.sdkerror
import mistralai
class DummySDKError(Exception):
    status_code = 500

DummyModels = type("models", (), {"sdkerror": type("sdkerror", (), {"SDKError": DummySDKError})})
mistralai.models = DummyModels

from models import Post, Tag, IoC, SearchCache


@pytest.fixture
def sample_post():
    return Post(
        id=1,
        source_id="12345",
        source="mastodon",
        user="threat_hunter",
        created_at=datetime(2024, 7, 10, 12, 0, 0, tzinfo=timezone.utc),
        fetched_at=datetime(2024, 7, 10, 12, 5, 0, tzinfo=timezone.utc),
        url="https://mastodon.social/@threat_hunter/12345",
        content_html="<p>Observed malicious campaign from 198.51.100.1</p>",
        content_txt="Observed malicious campaign from 198.51.100.1 #malware #c2",
        content_search="Observed malicious campaign from 198.51.100.1 malware c2 mastodon:mastodon source:mastodon user:threat_hunter 2024-07-10T12:00:00+00:00",
        raw='{"id": "12345"}',
        tags_assigned=False,
        iocs_assigned=False,
        is_hidden=False,
        is_ingested=False,
        tags=[],
        iocs=[],
    )


@pytest.fixture
def sample_tag():
    return Tag(
        id=1,
        name="MALWARE",
        color="#E02424",
    )


@pytest.fixture
def sample_ioc():
    return IoC(
        id=1,
        type="ip",
        subtype="ipv4",
        value="198.51.100.1",
        comment="Malicious C2 IP",
    )


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    
    mock_res = MagicMock()
    mock_res.first.return_value = None
    mock_res.all.return_value = []
    session.exec = AsyncMock(return_value=mock_res)
    return session


@pytest.fixture
def sample_config_dict():
    return {
        "mastodon": {
            "api_base_url": "https://mastodon.example.com",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "access_token": "test_access_token",
        },
        "bluesky": {
            "handle": "threatintel.bsky.social",
            "app_password": "app-test-password",
            "feeds": ["at://did:plc:123/app.bsky.feed.generator/testfeed"],
        },
        "telegram": {
            "api_id": 123456,
            "api_hash": "abcdef1234567890",
            "chats": ["Test Threat Intel Channel"],
        },
        "rss": {
            "reddit_cyber": {
                "name": "reddit/r/cybersecurity",
                "url": "https://www.reddit.com/r/cybersecurity.rss",
            }
        },
        "airtable": {
            "api_key": "pat_test_key",
            "base_id": "appTestBase123",
            "table_id": "tblTestTable456",
        },
        "baserow": {
            "api_key": "jwt_baserow_token",
            "base_url": "https://api.baserow.io/api",
            "table_id": "789",
        },
        "ai": {
            "provider": "openai",
            "base_url": "http://127.0.0.1:1234/v1",
            "api_key": "test-ai-key",
            "model": "gpt-4o-mini",
        },
        "misp-org": {
            "name": "Test Security Org",
            "uuid": "123e4567-e89b-12d3-a456-426614174000",
            "email": "soc@testorg.example.com",
        },
    }
