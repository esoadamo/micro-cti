import uuid
from unittest.mock import patch, mock_open
import pytest
from ioc import IoCLink
from misp_feed import (
    Org,
    MISPFeed,
    fake_uuid,
    _get_category_for_type,
    generate_misp_compatible_json,
    generate_misp_manifest_json,
    generate_misp_feed,
    get_org,
)


def test_fake_uuid_determinism():
    id1 = fake_uuid(b"test-input-data")
    id2 = fake_uuid(b"test-input-data")
    id3 = fake_uuid(b"different-data")

    assert id1 == id2
    assert id1 != id3
    # Verify it is a valid UUID format
    assert uuid.UUID(id1).version == 5


def test_get_category_for_type():
    # Verify categories from misp_feed mapping
    assert _get_category_for_type("ip-dst") == "Network activity"
    assert _get_category_for_type("ip-src") == "Network activity"
    assert _get_category_for_type("domain") == "Network activity"
    assert _get_category_for_type("url") == "Network activity"
    assert _get_category_for_type("email") == "Network activity"
    assert _get_category_for_type("md5") == "Artifacts dropped"
    assert _get_category_for_type("sha256") == "Artifacts dropped"
    assert _get_category_for_type("regkey") == "Persistence mechanism"
    assert _get_category_for_type("vulnerability") == "External analysis"
    assert _get_category_for_type("threat-actor") == "Attribution"
    assert _get_category_for_type("unknown_nonexistent_type") == "Other"


def test_get_org_cached():
    fake_toml = b'[misp-org]\nname="CyberSOC"\nuuid="11111111-2222-3333-4444-555555555555"\nemail="soc@cyber.org"\n'
    get_org.cache_clear()
    with patch("builtins.open", mock_open(read_data=fake_toml)):
        org = get_org()

    assert org.name == "CyberSOC"
    assert org.uuid == "11111111-2222-3333-4444-555555555555"
    assert org.email == "soc@cyber.org"
    get_org.cache_clear()


def test_generate_misp_compatible_json():
    mock_org = Org(name="Test Org", uuid="12345678-1234-5678-1234-567812345678", email="soc@test.org")
    iocs: list[IoCLink] = [
        {
            "value": "198.51.100.22",
            "type": "ip",
            "subtype": "ipv4",
            "relevance": 90,
            "comment": "Command and Control",
            "links": ["https://mastodon.social/@researcher/123"],
        }
    ]

    with patch("misp_feed.get_org", return_value=mock_org):
        event_dict = generate_misp_compatible_json("https://mastodon.social/@researcher/123", iocs)

    assert "Event" in event_dict
    event = event_dict["Event"]
    assert event["Orgc"]["name"] == "Test Org"
    assert "Attribute" in event
    # Should have 2 attributes: the IP attribute and the post URL reference attribute
    assert len(event["Attribute"]) == 2

    ip_attr = next(a for a in event["Attribute"] if a["value"] == "198.51.100.22")
    assert ip_attr["type"] == "ip"
    assert ip_attr["comment"] == "Command and Control"

    link_attr = next(a for a in event["Attribute"] if a["type"] == "link")
    assert link_attr["value"] == "https://mastodon.social/@researcher/123"
    assert link_attr["disable_correlation"] is True


def test_generate_misp_manifest_json():
    events = [
        {
            "Event": {
                "uuid": "e0000000-0000-0000-0000-000000000001",
                "info": "uCTI report",
                "date": "2024-07-15",
                "analysis": 1,
                "threat_level_id": 4,
                "timestamp": 1721044800,
                "Orgc": {"name": "TestOrg", "uuid": "org-uuid"},
                "Tag": [{"name": "tlp:white"}],
            }
        }
    ]

    manifest = generate_misp_manifest_json(events)
    assert "e0000000-0000-0000-0000-000000000001" in manifest
    entry = manifest["e0000000-0000-0000-0000-000000000001"]
    assert entry["info"] == "uCTI report"
    assert entry["date"] == "2024-07-15"
    assert entry["Orgc"]["name"] == "TestOrg"


def test_generate_misp_feed_end_to_end():
    mock_org = Org(name="FeedOrg", uuid="00000000-0000-0000-0000-000000000000", email="info@org.com")
    iocs: list[IoCLink] = [
        {
            "value": "evil.example.com",
            "type": "domain",
            "subtype": None,
            "relevance": 80,
            "comment": "phishing domain",
            "links": ["https://post1.example.com", "https://post2.example.com"],
        }
    ]

    with patch("misp_feed.get_org", return_value=mock_org):
        feed = generate_misp_feed(iocs)

    assert isinstance(feed, MISPFeed)
    # The IoC was linked to 2 posts, so 2 events should be generated
    assert len(feed.events) == 2
    assert len(feed.manifest) == 2
