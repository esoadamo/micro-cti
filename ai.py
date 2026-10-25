import asyncio
import tomllib
from http.client import responses
from random import choice
from typing import TypeVar, List, Union
from os import environ
from pydantic import BaseModel, Field

import mistralai
from models import Post
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.mistral import MistralModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.mistral import MistralProvider
from pydantic_ai.providers.openai import OpenAIProvider

from directories import FILE_CONFIG

T = TypeVar("T")


class CybersecurityPostAssessment(BaseModel):
    is_cybersecurity: bool
    tags: list[str] = Field(default_factory=list)


class BatchCybersecurityPostAssessment(BaseModel):
    """Batch classification results. One entry per post, in order."""
    results: list[CybersecurityPostAssessment]


class BatchTagResult(BaseModel):
    """Batch tag generation results. One list of hashtags per post, in order."""
    results: list[list[str]]


def get_model() -> Model:
    with open(FILE_CONFIG, 'rb') as f:
        config = tomllib.load(f)["ai"]

    api_keys: Union[str, List[str]] = config["api_key"]
    if isinstance(api_keys, str):
        api_keys = [api_keys]
    assert isinstance(api_keys, list)

    if config.get("provider") == "mistral":
        models = [MistralModel(config["model"], provider=MistralProvider(api_key=x)) for x in api_keys]
        return FallbackModel(*models)

    # noinspection PyTypeChecker
    return OpenAIChatModel(
        model_name=config["model"],
        provider=OpenAIProvider(base_url=config["base_url"], api_key=choice(api_keys)),
    )


async def prompt(system_prompt: str, user_prompt: str, output_type: type[T], retries: int = 3) -> T:
    exception = ValueError("Failed to get a valid response after multiple retries")

    for _ in range(retries):
        try:
            try:
                agent = Agent(
                    get_model(),
                    output_type=output_type,
                    system_prompt=system_prompt,
                    retries=2,
                )
                return (await agent.run(user_prompt)).output
            except UnexpectedModelBehavior as e:
                print(f"[!] Unexpected model behavior: {e}, retrying...")
                await asyncio.sleep(1)
            except (ModelHTTPError, mistralai.models.sdkerror.SDKError) as e:
                if e.status_code == 429:
                    print("[!] Rate limited, retrying...")
                    await asyncio.sleep(5)
                if e.status_code == 500:
                    print("[!] Server error, retrying...")
                    await asyncio.sleep(5)
                else:
                    print(f"[!] HTTP Error {e.status_code}: {responses.get(e.status_code, 'Unknown error')}")
                    raise
        except Exception as e:
            exception = e
            print(f"[!] Error during prompting: {e}, retrying...")
            await asyncio.sleep(3)

    raise exception


async def prompt_tags(text: str) -> list[str]:
    # Truncate text to max 400 chars to save input tokens
    truncated_text = text[:400].replace("\n", " ")
    
    response = await prompt(
        environ.get(
            "SYSTEM_PROMPT_GENERATE_TAGS",
            "Generate max 7 cybersecurity hashtags in camelCase English. Format: #HashtagName per line."
        ),
        truncated_text,
        list[str]
    )

    return [x for x in response if x.startswith('#')]


async def prompt_check_cybersecurity_post(post: Post) -> bool:
    # Truncate to first 500 chars for classification (enough context)
    truncated_content = post.content_txt[:500].replace("\n", " ")
    
    return await prompt(
        environ.get(
            "SYSTEM_PROMPT_CLASSIFY_POST",
            "Is this post in English about cybersecurity (tools, attacks, vulnerabilities, threats, exploits, hacks)? Answer True/False."
        ),
        truncated_content,
        bool
    )


async def prompt_classify_and_tag_post(post: Post, include_tags: bool) -> CybersecurityPostAssessment:
    truncated_content = post.content_txt[:500].replace("\n", " ")
    system_prompt = environ.get(
        "SYSTEM_PROMPT_CLASSIFY_AND_TAG_POST",
        (
            f"{environ.get('SYSTEM_PROMPT_CLASSIFY_POST', 'Determine whether this post is in English and about cybersecurity (tools, attacks, vulnerabilities, threats, exploits, or hacks).')} "
            "Return whether the post is about cybersecurity in the is_cybersecurity field. "
            "Do not respond with a standalone True or False. "
            "If it is about cybersecurity, then return up to 7 English cybersecurity "
            "hashtags in camelCase, each starting with #, in the tags field. Otherwise, return an empty tags list."
        ),
    )
    if not include_tags:
        system_prompt += " Tag generation is not requested for this post; return an empty tags list."

    return await prompt(
        system_prompt,
        truncated_content,
        CybersecurityPostAssessment,
    )


async def prompt_classify_and_tag_posts_batch(
    posts: List[Post], include_tags: bool, batch_size: int = 10
) -> List[CybersecurityPostAssessment]:
    """Classify and tag multiple posts in batched API calls to save system prompt tokens."""
    if not posts:
        return []
    all_results: List[CybersecurityPostAssessment] = []
    for i in range(0, len(posts), batch_size):
        batch = posts[i:i + batch_size]
        user_prompt = "\n---\n".join(
            f"POST {j + 1}:\n{post.content_txt[:500].replace(chr(10), ' ')}"
            for j, post in enumerate(batch)
        )
        base_classify = environ.get(
            'SYSTEM_PROMPT_CLASSIFY_POST',
            'Determine whether each post is in English and about cybersecurity '
            '(tools, attacks, vulnerabilities, threats, exploits, or hacks).'
        )
        system_prompt = (
            f"You will receive {len(batch)} posts separated by '---'. "
            f"{base_classify} "
            "Return a 'results' array with one entry per post in the same order. "
            "Each entry must have 'is_cybersecurity' (bool) and 'tags' (list). "
        )
        if include_tags:
            system_prompt += (
                "If a post is about cybersecurity, return up to 7 English cybersecurity "
                "hashtags in camelCase, each starting with #, in its tags field. "
                "Otherwise, return an empty tags list."
            )
        else:
            system_prompt += "Return empty tags lists for all posts."

        batch_result = await prompt(system_prompt, user_prompt, BatchCybersecurityPostAssessment)
        results = batch_result.results[:len(batch)]
        # Pad with safe defaults if model returned fewer results than expected
        while len(results) < len(batch):
            results.append(CybersecurityPostAssessment(is_cybersecurity=False, tags=[]))
        all_results.extend(results)
    return all_results


async def prompt_tags_batch(texts: List[str], batch_size: int = 10) -> List[List[str]]:
    """Generate tags for multiple texts in batched API calls to save system prompt tokens."""
    if not texts:
        return []
    all_results: List[List[str]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        user_prompt = "\n---\n".join(
            f"POST {j + 1}:\n{text[:400].replace(chr(10), ' ')}"
            for j, text in enumerate(batch)
        )
        system_prompt = environ.get(
            "SYSTEM_PROMPT_BATCH_GENERATE_TAGS",
            f"You will receive {len(batch)} posts separated by '---'. "
            "For each post, generate max 7 cybersecurity hashtags in camelCase English, "
            "each starting with #. Return a 'results' array with one list of hashtags per "
            "post in the same order.",
        )
        batch_result = await prompt(system_prompt, user_prompt, BatchTagResult)
        results = batch_result.results[:len(batch)]
        while len(results) < len(batch):
            results.append([])
        all_results.extend([[x for x in tags if x.startswith('#')] for tags in results])
    return all_results


if __name__ == "__main__":
    async def test():
        for _ in range(100):
            print(await prompt_tags("I found a new vulnerability in Windows 10."))

    asyncio.run(test())
