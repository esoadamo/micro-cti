import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ioc import (
    AIOicType,
    AIIoC,
    PostIoCs,
    BatchIoCResult,
    _validate_and_collect_iocs,
    _store_iocs,
    parse_iocs_from_post,
    extract_iocs_batch,
    parse_iocs,
    search_iocs,
)
from models import Post, IoC
from post.exception import FetchError


def test_ai_ioc_types_enum():
    assert AIOicType.ip.value == "ip"
    assert AIOicType.domain.value == "domain"
    assert AIOicType.hash.value == "hash"
    assert AIOicType.url.value == "url"
    assert AIOicType.email.value == "email"
    assert AIOicType.external_report_link.value == "external-report-link"
    assert AIOicType.vulnerability.value == "vulnerability"


def test_validate_and_collect_ip_v4_and_v6(sample_post):
    items = [
        AIIoC(value="192.0.2.1", type=AIOicType.ip, comment="Bad IPv4"),
        AIIoC(value="2001:db8::1", type=AIOicType.ip, comment="Bad IPv6"),
        AIIoC(value="999.999.999.999", type=AIOicType.ip),  # Invalid
        AIIoC(value="not-an-ip", type=AIOicType.ip),  # Invalid
    ]
    result = _validate_and_collect_iocs(items, sample_post)

    assert "ip:192.0.2.1" in result
    assert result["ip:192.0.2.1"]["type_secondary"] == "ipv4"
    assert result["ip:192.0.2.1"]["comment"] == "Bad IPv4"

    assert "ip:2001:db8::1" in result
    assert result["ip:2001:db8::1"]["type_secondary"] == "ipv6"

    assert "ip:999.999.999.999" not in result
    assert "ip:not-an-ip" not in result


def test_validate_and_collect_hashes(sample_post):
    md5_hash = "d41d8cd98f00b204e9800998ecf8427e"  # 32
    sha1_hash = "da39a3ee5e6b4b0d3255bfef95601890afd80709"  # 40
    sha256_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # 64
    sha512_hash = "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e"  # 128
    invalid_hash = "12345abcdef"

    items = [
        AIIoC(value=md5_hash, type=AIOicType.hash),
        AIIoC(value=sha1_hash, type=AIOicType.hash),
        AIIoC(value=sha256_hash, type=AIOicType.hash),
        AIIoC(value=sha512_hash, type=AIOicType.hash),
        AIIoC(value=invalid_hash, type=AIOicType.hash),
    ]
    result = _validate_and_collect_iocs(items, sample_post)

    assert result[f"hash:{md5_hash}"]["type_secondary"] == "md5"
    assert result[f"hash:{sha1_hash}"]["type_secondary"] == "sha1"
    assert result[f"hash:{sha256_hash}"]["type_secondary"] == "sha256"
    assert result[f"hash:{sha512_hash}"]["type_secondary"] == "sha512"
    assert f"hash:{invalid_hash}" not in result


def test_validate_and_collect_domains(sample_post):
    items = [
        AIIoC(value="c2.evil-corp.com", type=AIOicType.domain),
        AIIoC(value="sub.domain.co.uk", type=AIOicType.domain),
        AIIoC(value="invalid_domain", type=AIOicType.domain),
        AIIoC(value="http://evil.com", type=AIOicType.domain),  # Has scheme, not bare domain
    ]
    result = _validate_and_collect_iocs(items, sample_post)

    assert "domain:c2.evil-corp.com" in result
    assert "domain:sub.domain.co.uk" in result
    assert "domain:invalid_domain" not in result
    assert "domain:http://evil.com" not in result


def test_validate_and_collect_urls(sample_post):
    items = [
        AIIoC(value="https://malicious.com/payload.exe", type=AIOicType.url),
        AIIoC(value="http://198.51.100.1:8080/c2", type=AIOicType.url),
        AIIoC(value="not-a-url", type=AIOicType.url),
    ]
    result = _validate_and_collect_iocs(items, sample_post)

    assert "url:https://malicious.com/payload.exe" in result
    assert "url:http://198.51.100.1:8080/c2" in result
    assert "url:not-a-url" not in result


def test_validate_and_collect_external_report_links(sample_post):
    items = [
        AIIoC(value=sample_post.url, type=AIOicType.external_report_link),
        AIIoC(value="https://security.blog/article", type=AIOicType.external_report_link),
    ]
    result = _validate_and_collect_iocs(items, sample_post)

    assert result[f"external-report-link:{sample_post.url}"]["type_secondary"] == "post-link"
    assert result["external-report-link:https://security.blog/article"]["type_secondary"] == "external-article"


def test_validate_and_collect_emails(sample_post):
    items = [
        AIIoC(value="attacker@phishing-zone.net", type=AIOicType.email),
        AIIoC(value="not-an-email", type=AIOicType.email),
        AIIoC(value="bad@domain", type=AIOicType.email),
    ]
    result = _validate_and_collect_iocs(items, sample_post)

    assert "email:attacker@phishing-zone.net" in result
    assert "email:not-an-email" not in result
    assert "email:bad@domain" not in result


def test_validate_and_collect_vulnerabilities(sample_post):
    items = [
        AIIoC(value="CVE-2024-12345", type=AIOicType.vulnerability),
        AIIoC(value="GHSA-xxxx-yyyy-zzzz", type=AIOicType.vulnerability),  # not matching GHSA-\d{4}-\d{4,}
        AIIoC(value="GHSA-2024-12345", type=AIOicType.vulnerability),
        AIIoC(value="VULN-1234", type=AIOicType.vulnerability),
    ]
    result = _validate_and_collect_iocs(items, sample_post)

    assert "vulnerability:CVE-2024-12345" in result
    assert "vulnerability:GHSA-2024-12345" in result
    assert "vulnerability:VULN-1234" not in result


def test_validate_and_collect_deduplication(sample_post):
    items = [
        AIIoC(value="1.2.3.4", type=AIOicType.ip, comment="first"),
        AIIoC(value="1.2.3.4", type=AIOicType.ip, comment="second"),
    ]
    result = _validate_and_collect_iocs(items, sample_post)
    assert len(result) == 1
    assert result["ip:1.2.3.4"]["comment"] == "second"


@pytest.mark.asyncio
async def test_store_iocs(sample_post, mock_db_session):
    iocs_data = {
        "ip:1.2.3.4": {
            "ioc": "1.2.3.4",
            "type_main": "ip",
            "type_secondary": "ipv4",
            "comment": "Test IP",
        }
    }

    stored = await _store_iocs(iocs_data, sample_post, mock_db_session)

    assert len(stored) == 1
    assert stored[0].value == "1.2.3.4"
    assert stored[0].type == "ip"
    assert stored[0].subtype == "ipv4"
    assert stored[0] in sample_post.iocs
    assert mock_db_session.add.call_count >= 2
    assert mock_db_session.commit.call_count >= 2


@pytest.mark.asyncio
async def test_extract_iocs_batch():
    posts = [
        Post(id=1, source="rss", user="test", url="http://test.com/1", content_html="", content_txt="IP 1.2.3.4", raw=""),
        Post(id=2, source="rss", user="test", url="http://test.com/2", content_html="", content_txt="No IoCs", raw=""),
    ]

    mock_batch_result = BatchIoCResult(
        results=[
            PostIoCs(iocs=[AIIoC(value="1.2.3.4", type=AIOicType.ip)]),
            PostIoCs(iocs=[]),
        ]
    )

    with patch("ioc.prompt", new=AsyncMock(return_value=mock_batch_result)):
        results = await extract_iocs_batch(posts, batch_size=5)

    assert len(results) == 2
    assert len(results[0]) == 1
    assert results[0][0].value == "1.2.3.4"
    assert len(results[1]) == 0


@pytest.mark.asyncio
async def test_extract_iocs_batch_empty():
    results = await extract_iocs_batch([])
    assert results == []


@pytest.mark.asyncio
async def test_parse_iocs_from_post(sample_post, mock_db_session):
    ai_iocs = [AIIoC(value="198.51.100.1", type=AIOicType.ip, comment="C2")]

    with patch("ioc.prompt", new=AsyncMock(return_value=ai_iocs)):
        extracted = []
        async for ioc in parse_iocs_from_post(sample_post, mock_db_session):
            extracted.append(ioc)

    # Should yield the AI IoC and the post URL external-report-link
    assert len(extracted) == 2
    values = {i.value for i in extracted}
    assert "198.51.100.1" in values
    assert sample_post.url in values


@pytest.mark.asyncio
async def test_parse_iocs_pipeline(sample_post, mock_db_session):
    mock_res = MagicMock()
    mock_res.all.return_value = [sample_post]
    mock_db_session.exec.return_value = mock_res

    batch_output = [[AIIoC(value="198.51.100.1", type=AIOicType.ip, comment="Observed")]]

    with patch("ioc.extract_iocs_batch", new=AsyncMock(return_value=batch_output)):
        yielded = []
        async for ioc in parse_iocs(mock_db_session, ids=[1]):
            yielded.append(ioc)

    assert sample_post.iocs_assigned is True
    assert len(yielded) >= 1


@pytest.mark.asyncio
async def test_parse_iocs_empty_ids(mock_db_session):
    yielded = []
    async for ioc in parse_iocs(mock_db_session, ids=[]):
        yielded.append(ioc)
    assert yielded == []
    mock_db_session.exec.assert_not_called()


@pytest.mark.asyncio
async def test_search_iocs(mock_db_session, sample_post):
    ioc1 = IoC(id=1, type="ip", subtype="ipv4", value="198.51.100.1", comment="C2")
    ioc1.posts = [sample_post]

    mock_search_posts_result = [(sample_post, {"relevancy_score": 88})]
    mock_ioc_res = MagicMock()
    mock_ioc_res.all.return_value = [ioc1]
    mock_db_session.exec.return_value = mock_ioc_res

    with patch("ioc.search_posts", new=AsyncMock(return_value=mock_search_posts_result)):
        results = await search_iocs("198.51.100.1", mock_db_session)

    assert len(results) == 1
    assert results[0]["value"] == "198.51.100.1"
    assert results[0]["type"] == "ip"
    assert results[0]["relevance"] == 88
    assert sample_post.url in results[0]["links"]
