import json
from base64 import b64encode
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from db import get_db_session
from models import Post, Tag
from web import app


@pytest.fixture
def client(mock_db_session):
    async def override_get_db_session():
        yield mock_db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_healthcheck(client, mock_db_session):
    now = datetime(2024, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    with patch("web.get_latest_ingestion_time", new=AsyncMock(return_value=now)):
        response = client.get("/healthcheck")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["latest_ingestion_time"]["total"].startswith("2024-08-01T10:00:00")


def test_ioc_json_endpoint(client, mock_db_session):
    mock_iocs = [
        {
            "value": "198.51.100.1",
            "type": "ip",
            "subtype": "ipv4",
            "relevance": 95,
            "comment": "C2 Server",
            "links": ["https://mastodon.social/@sec/123"],
        }
    ]

    with patch("web.search_iocs", new=AsyncMock(return_value=mock_iocs)), \
         patch("web.get_latest_ingestion_time", new=AsyncMock(return_value=None)):
        response = client.get("/ioc/json/?q=198.51.100.1")

    assert response.status_code == 200
    data = response.json()
    assert data["search_term"] == "198.51.100.1"
    assert len(data["iocs"]) == 1
    assert data["iocs"][0]["value"] == "198.51.100.1"


def test_ioc_csv_endpoint(client, mock_db_session):
    mock_iocs = [
        {
            "value": "evil-domain.com",
            "type": "domain",
            "subtype": "",
            "relevance": 80,
            "comment": "phishing",
            "links": ["https://post.com/1", "https://post.com/2"],
        }
    ]

    with patch("web.search_iocs", new=AsyncMock(return_value=mock_iocs)):
        response = client.get("/ioc/csv/?q=evil-domain.com")

    assert response.status_code == 200
    csv_text = response.text
    assert "type,value,subtype,comment,link,relevance" in csv_text
    assert "evil-domain.com" in csv_text
    assert "https://post.com/1;https://post.com/2" in csv_text


def test_ioc_misp_redirect(client):
    response = client.get("/ioc/misp/?q=apt29", follow_redirects=False)
    assert response.status_code == 307 or response.status_code == 302
    assert "location" in response.headers
    assert "/ioc/misp/" in response.headers["location"]


def test_ioc_misp_manifest_file(client, mock_db_session):
    q_b64 = b64encode(json.dumps({"q": "test"}).encode()).decode()
    mock_feed = MagicMock()
    mock_feed.manifest = {"uuid-123": {"info": "Test Report"}}
    mock_feed.events = []

    with patch("web.search_iocs", new=AsyncMock(return_value=[])), \
         patch("web.generate_misp_feed", return_value=mock_feed):
        response = client.get(f"/ioc/misp/{q_b64}/manifest.json")

    assert response.status_code == 200
    assert response.json() == {"uuid-123": {"info": "Test Report"}}


def test_api_dynamic_queries(client):
    response = client.get("/api/dynamic-queries?q=malware !from:2024-01-01 !to:2024-01-22")
    assert response.status_code == 200
    data = response.json()
    assert "commands" in data
    assert "subqueries" in data
    assert len(data["subqueries"]) >= 1


def test_api_search(client, sample_post, mock_db_session):
    tag = Tag(name="#EXPLOIT", color="#FF0000")
    sample_post.tags = [tag]
    mock_posts = [(sample_post, {"relevancy_score": 92})]

    with patch("web.search_posts", new=AsyncMock(return_value=mock_posts)):
        response = client.get("/api/search?q=exploit")

    assert response.status_code == 200
    data = response.json()
    assert data["search_term"] == "exploit"
    assert len(data["posts"]) == 1
    post_item = data["posts"][0]
    assert post_item["source"] == "mastodon"
    assert post_item["score"] == 92
    assert len(post_item["tags"]) == 1
    assert post_item["tags"][0]["name"] == "#EXPLOIT"


def test_search_html_page(client, mock_db_session, sample_post):
    with patch("web.search_posts", new=AsyncMock(return_value=[(sample_post, {"relevancy_score": 90})])), \
         patch("web.get_latest_ingestion_time", new=AsyncMock(return_value=None)):
        response = client.get("/search/?q=trojan")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
