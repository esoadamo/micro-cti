from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel

from ai import (
    CybersecurityPostAssessment,
    BatchCybersecurityPostAssessment,
    BatchTagResult,
    get_model,
    prompt,
    prompt_tags,
    prompt_check_cybersecurity_post,
    prompt_classify_and_tag_post,
    prompt_classify_and_tag_posts_batch,
    prompt_tags_batch,
)
from models import Post


def test_cybersecurity_post_assessment_model():
    m = CybersecurityPostAssessment(is_cybersecurity=True, tags=["#malware", "#apt"])
    assert m.is_cybersecurity is True
    assert m.tags == ["#malware", "#apt"]

    m2 = CybersecurityPostAssessment(is_cybersecurity=False)
    assert m2.tags == []


def test_get_model_openai():
    fake_toml = b'[ai]\nprovider="openai"\nbase_url="http://localhost:1234/v1"\napi_key="test-key"\nmodel="gpt-4o"\n'
    with patch("builtins.open", mock_open(read_data=fake_toml)):
        model = get_model()
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "gpt-4o"


def test_get_model_mistral():
    fake_toml = b'[ai]\nprovider="mistral"\napi_key=["key1", "key2"]\nmodel="mistral-large"\n'
    with patch("builtins.open", mock_open(read_data=fake_toml)):
        model = get_model()
    assert isinstance(model, FallbackModel)


@pytest.mark.asyncio
async def test_prompt_success():
    mock_run_result = MagicMock()
    mock_run_result.output = "Test Output"

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_run_result)

    with patch("ai.Agent", return_value=mock_agent), patch("ai.get_model"):
        res = await prompt("sys", "user", str)

    assert res == "Test Output"


@pytest.mark.asyncio
async def test_prompt_retry_on_unexpected_behavior():
    mock_run_result = MagicMock()
    mock_run_result.output = "Success on retry"

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(
        side_effect=[UnexpectedModelBehavior("parsing error"), mock_run_result]
    )

    with patch("ai.Agent", return_value=mock_agent), patch("ai.get_model"), patch("asyncio.sleep", new=AsyncMock()):
        res = await prompt("sys", "user", str, retries=2)

    assert res == "Success on retry"


@pytest.mark.asyncio
async def test_prompt_exhausts_retries():
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(side_effect=RuntimeError("Permanent failure"))

    with patch("ai.Agent", return_value=mock_agent), patch("ai.get_model"), patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(RuntimeError):
            await prompt("sys", "user", str, retries=2)


@pytest.mark.asyncio
async def test_prompt_tags():
    mock_output = ["#ransomware", "#cve2024", "no_hash_tag"]
    with patch("ai.prompt", new=AsyncMock(return_value=mock_output)):
        tags = await prompt_tags("Sample alert about ransomware attack")
    # Only tags starting with # are returned by prompt_tags
    assert tags == ["#ransomware", "#cve2024"]


@pytest.mark.asyncio
async def test_prompt_check_cybersecurity_post(sample_post):
    with patch("ai.prompt", new=AsyncMock(return_value=True)):
        is_cyber = await prompt_check_cybersecurity_post(sample_post)
    assert is_cyber is True


@pytest.mark.asyncio
async def test_prompt_classify_and_tag_post(sample_post):
    assessment = CybersecurityPostAssessment(is_cybersecurity=True, tags=["#ddos"])
    with patch("ai.prompt", new=AsyncMock(return_value=assessment)):
        res = await prompt_classify_and_tag_post(sample_post, include_tags=True)
    assert res.is_cybersecurity is True
    assert res.tags == ["#ddos"]


@pytest.mark.asyncio
async def test_prompt_classify_and_tag_posts_batch():
    posts = [
        Post(id=1, source="rss", user="test", url="http://1", content_html="", content_txt="attack 1", raw=""),
        Post(id=2, source="rss", user="test", url="http://2", content_html="", content_txt="recipe for cake", raw=""),
    ]
    batch_resp = BatchCybersecurityPostAssessment(
        results=[
            CybersecurityPostAssessment(is_cybersecurity=True, tags=["#cyber"]),
            CybersecurityPostAssessment(is_cybersecurity=False, tags=[]),
        ]
    )
    with patch("ai.prompt", new=AsyncMock(return_value=batch_resp)):
        results = await prompt_classify_and_tag_posts_batch(posts, include_tags=True, batch_size=5)

    assert len(results) == 2
    assert results[0].is_cybersecurity is True
    assert results[1].is_cybersecurity is False


@pytest.mark.asyncio
async def test_prompt_tags_batch():
    texts = ["text 1 about cyber", "text 2 about vuln"]
    batch_resp = BatchTagResult(results=[["#tag1", "#tag2"], ["#tag3", "notag"]])
    with patch("ai.prompt", new=AsyncMock(return_value=batch_resp)):
        results = await prompt_tags_batch(texts, batch_size=5)

    assert len(results) == 2
    assert results[0] == ["#tag1", "#tag2"]
    # Only tags starting with # should be retained
    assert results[1] == ["#tag3"]
