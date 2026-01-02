import asyncio
import tomllib
from http.client import responses
from random import choice
from typing import TypeVar, List, Union

import mistralai
from prisma.models import Post
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
        "Generate max 7 cybersecurity hashtags in camelCase English. Format: #HashtagName per line.",
        truncated_text,
        list[str]
    )

    return [x for x in response if x.startswith('#')]


async def prompt_check_cybersecurity_post(post: Post) -> bool:
    # Truncate to first 500 chars for classification (enough context)
    truncated_content = post.content_txt[:500].replace("\n", " ")
    
    return await prompt(
        "Is this post in English about cybersecurity (tools, attacks, vulnerabilities, threats, exploits, hacks)? Answer True/False.",
        truncated_content,
        bool
    )


if __name__ == "__main__":
    async def test():
        for _ in range(100):
            print(await prompt_tags("I found a new vulnerability in Windows 10."))

    asyncio.run(test())
