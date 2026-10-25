import re
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from lark import ParseError

from models import Post, Tag
from search import (
    parse_query,
    evaluate_ast,
    parse_search_terms,
    format_post_for_search,
    post_fulltext_score,
    parse_search_commands,
    search_posts,
)


def test_parse_query_simple_word():
    ast = parse_query("malware")
    assert ast == {"term": "malware"}


def test_parse_query_quoted_phrase():
    ast = parse_query('"zero day exploit"')
    assert ast == {"exact": "zero day exploit"}


def test_parse_query_and_expression():
    ast = parse_query("malware AND ransomware")
    assert "AND" in ast
    assert {"term": "malware"} in ast["AND"]
    assert {"term": "ransomware"} in ast["AND"]


def test_parse_query_or_expression():
    ast = parse_query("malware OR phishing")
    assert "OR" in ast
    assert {"term": "malware"} in ast["OR"]
    assert {"term": "phishing"} in ast["OR"]


def test_parse_query_nested_parentheses():
    ast = parse_query('(apt28 OR apt29) AND "state sponsored"')
    assert "AND" in ast


def test_parse_query_invalid_syntax():
    with pytest.raises(ParseError):
        parse_query("((unclosed paren")


def test_evaluate_ast_exact_phrase(sample_post):
    sample_post.content_search = "new zero day exploit discovered in linux"

    ast_hit = {"exact": "zero day exploit"}
    ast_miss = {"exact": "buffer overflow"}

    # Non-strict
    assert evaluate_ast(ast_hit, sample_post, strict=False) == 1.0
    assert evaluate_ast(ast_miss, sample_post, strict=False) == 0.5

    # Strict
    assert evaluate_ast(ast_hit, sample_post, strict=True) == 1.0
    assert evaluate_ast(ast_miss, sample_post, strict=True) == 0.0


def test_evaluate_ast_user_and_source_selector(sample_post):
    sample_post.user = "cert_pl"
    sample_post.source = "mastodon"

    # User match
    ast_user_match = {"term": "user:cert"}
    ast_user_fail = {"term": "user:otheruser"}
    assert evaluate_ast(ast_user_match, sample_post) == 1.0
    assert evaluate_ast(ast_user_fail, sample_post) == 0.3
    assert evaluate_ast(ast_user_fail, sample_post, strict=True) == 0.0

    # Source match
    ast_src_match = {"term": "source:mastodon"}
    ast_src_fail = {"term": "source:bluesky"}
    assert evaluate_ast(ast_src_match, sample_post) == 1.0
    assert evaluate_ast(ast_src_fail, sample_post) == 0.3


def test_evaluate_ast_or_and_and(sample_post):
    sample_post.content_search = "critical cve-2024-1111 found"

    ast_or = {"OR": [{"exact": "cve-2024-1111"}, {"exact": "nonexistent"}]}
    assert evaluate_ast(ast_or, sample_post) == 1.0

    ast_and = {"AND": [{"exact": "cve-2024-1111"}, {"exact": "nonexistent"}]}
    assert evaluate_ast(ast_and, sample_post) == 0.5


def test_parse_search_terms():
    ast = {"AND": [{"term": "malware"}, {"exact": "zero day"}]}
    terms = list(parse_search_terms(ast))
    assert "malware zero day" in terms

    ast_or = {"OR": [{"term": "a"}, {"term": "b"}]}
    terms_or = list(parse_search_terms(ast_or))
    assert set(terms_or) == {"a", "b"}


def test_post_fulltext_score():
    post_id, score = post_fulltext_score(42, "malicious trojan dropper detected", "+trojan -phishing")
    assert post_id == 42
    assert score > 0


def test_parse_search_commands():
    query = "malware !strict !debug !count:25 !min_score:50 !distinct:85 !from:2024-01-01 !to:2024-01-10"
    commands = parse_search_commands(query)

    assert "malware" in commands["fulltext"]
    assert commands["strict_search"] is True
    assert commands["debug_mode"] is True
    assert commands["count"] == 25
    assert commands["min_score"] == 50
    assert commands["distinct_score"] == 85
    assert commands["search_earliest"] == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert commands["search_latest"] == datetime(2024, 1, 10, 0, 0, 0, tzinfo=timezone.utc)


def test_parse_search_commands_age():
    query = "ransomware !age:14"
    commands = parse_search_commands(query)

    assert "ransomware" in commands["fulltext"]
    diff = commands["search_latest"] - commands["search_earliest"]
    assert diff.days == 14


@pytest.mark.asyncio
async def test_format_post_for_search(sample_post, mock_db_session):
    tag = Tag(name="#EXPLOIT", color="#111")
    sample_post.tags = [tag]
    sample_post.content_search = None

    mock_res = MagicMock()
    mock_res.first.return_value = sample_post
    mock_db_session.exec.return_value = mock_res

    res = await format_post_for_search(sample_post, mock_db_session, regenerate=True)

    assert "EXPLOIT" in res
    assert f"source:{sample_post.source}" in res
    assert f"user:{sample_post.user}" in res
    assert sample_post.content_search == res
    mock_db_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_search_posts_cached(mock_db_session, sample_post):
    cached_result = [(sample_post, {"relevancy_score": 90, "distinct_score": 0})]

    with patch("search.cache_fetch", new=AsyncMock(return_value=cached_result)):
        results = await search_posts("malware", mock_db_session)

    assert len(results) == 1
    assert results[0][0].id == sample_post.id
    assert results[0][1]["relevancy_score"] == 90
