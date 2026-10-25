from datetime import datetime, timezone
import pytest
from models import Post, Tag, IoC, PostTagLink, PostIoCLink, SearchCache


def test_post_tag_link_init():
    link = PostTagLink(A=10, B=20)
    assert link.A == 10
    assert link.B == 20
    assert PostTagLink.__tablename__ == "_PostTags"


def test_post_ioc_link_init():
    link = PostIoCLink(A=5, B=15)
    assert link.A == 5
    assert link.B == 15
    assert PostIoCLink.__tablename__ == "_PostIoCs"


def test_tag_defaults_and_fields():
    tag = Tag(name="RANSOMWARE")
    assert tag.id is None
    assert tag.name == "RANSOMWARE"
    assert tag.color == "#000"
    assert tag.posts == []
    assert Tag.__tablename__ == "Tag"


def test_ioc_defaults_and_fields():
    ioc = IoC(
        type="ip",
        subtype="ipv4",
        value="1.1.1.1",
        comment="DNS resolver",
    )
    assert ioc.id is None
    assert ioc.type == "ip"
    assert ioc.subtype == "ipv4"
    assert ioc.value == "1.1.1.1"
    assert ioc.comment == "DNS resolver"
    assert ioc.posts == []
    assert IoC.__tablename__ == "IoC"


def test_post_defaults():
    now = datetime.now(tz=timezone.utc)
    post = Post(
        source="telegram",
        user="test_channel",
        created_at=now,
        fetched_at=now,
        url="https://t.me/test/1",
        content_html="<p>Test</p>",
        content_txt="Test",
        raw="{}",
    )
    assert post.id is None
    assert post.source_id is None
    assert post.tags_assigned is False
    assert post.iocs_assigned is False
    assert post.is_hidden is True
    assert post.is_ingested is False
    assert post.content_search is None
    assert post.tags == []
    assert post.iocs == []
    assert Post.__tablename__ == "Post"


def test_post_relationships_append():
    post = Post(
        source="rss",
        user="reddit",
        created_at=datetime.now(tz=timezone.utc),
        fetched_at=datetime.now(tz=timezone.utc),
        url="https://reddit.com/r/netsec/1",
        content_html="Text",
        content_txt="Text",
        raw="{}",
    )
    tag = Tag(name="ZERO_DAY", color="#FF0000")
    ioc = IoC(type="cve", value="CVE-2024-9999")

    post.tags.append(tag)
    post.iocs.append(ioc)

    assert len(post.tags) == 1
    assert post.tags[0].name == "ZERO_DAY"
    assert len(post.iocs) == 1
    assert post.iocs[0].value == "CVE-2024-9999"


def test_search_cache_init():
    expires = datetime(2025, 1, 1, tzinfo=timezone.utc)
    cache = SearchCache(
        query_hash="abc123hash",
        query="malware AND ransomware",
        filepath="cache_file.pickle.gz",
        expires_at=expires,
    )
    assert cache.id is None
    assert cache.query_hash == "abc123hash"
    assert cache.query == "malware AND ransomware"
    assert cache.filepath == "cache_file.pickle.gz"
    assert cache.expires_at == expires
    assert SearchCache.__tablename__ == "SearchCache"
