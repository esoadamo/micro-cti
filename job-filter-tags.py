import asyncio
from typing import Dict, Set, AsyncIterable, List

from fuzzywuzzy import fuzz
from prisma.models import Tag

from db import get_db


async def get_tags(max_tag_id: int, step: int) -> AsyncIterable[List[Tag]]:
    db = await get_db()

    for tag_id_min_curr in range(0, max_tag_id, step):
        yield await db.tag.find_many(skip=tag_id_min_curr, take=step, order={'id': 'asc'})


async def main() -> int:
    print('[*] Process started')
    db = await get_db()
    
    step = 75000

    print('[*] Loading tags')
    max_tag_id = await db.tag.find_first(order={'id': 'desc'})

    print('[*] Deleting tags with short name')
    to_delete: Set[int] = set()
    async for tags in get_tags(max_tag_id.id, step):
        for tag in tags:
            print(f'[*] {tag.id}/{max_tag_id.id}', end='\r')
            if len(tag.name) < 5:
                to_delete.add(tag.id)
    for tag_id in to_delete:
        print(f'[*] Deleting tag {tag_id}')
        await db.tag.delete(where={'id': tag_id})
    print('[*] Tags with short name deleted')

    combine: Dict[int, Set[int]] = {}
    ignore: Set[int] = set()

    print('[*] Processing subtags')

    all_pages = []
    async for subtags in get_tags(max_tag_id.id, step):
        all_pages.append(subtags)

    for tag_id_min_curr in range(0, max_tag_id.id, step):
        print(f'[*] Processing tags from {tag_id_min_curr} to {tag_id_min_curr + step}')
        tags = await db.tag.find_many(skip=tag_id_min_curr, take=step)
        # Get tags that are extension of other tags
        for i, tag in enumerate(tags):
            # Print percentage and carriage return to rewrite the line
            if tag.id in ignore:
                continue
            page_num = 0
            for subtags in all_pages:
                print(f'[*] {i - tag_id_min_curr:04d}/{step} (page {page_num})', end='\r')
                page_num += 1

                if subtags[-1].id < tag.id:
                    continue

                for j, tag2 in enumerate(subtags):
                    if j in ignore or tag2.id < tag.id:
                        continue
                    if tag.name.lower().startswith(tag2.name.lower()):
                        combine.setdefault(tag2.id, set()).add(tag.id)
                        ignore.update((tag.id, tag2.id))
                    elif tag2.name.lower().startswith(tag.name.lower()):
                        combine.setdefault(tag.id, set()).add(tag2.id)
                        ignore.update((tag.id, tag2.id))
                    # Check their levenstein distance
                    elif fuzz.ratio(tag.name.lower(), tag2.name.lower()) > 90:
                        combine.setdefault(tag.id, set()).add(tag2.id)
                        ignore.update((tag.id, tag2.id))

    for main_tag_id, subtags_ids in combine.items():
        for subtag_id in subtags_ids:
            print(f'[*] Merging {subtag_id} into {main_tag_id}')
            subtag_posts = await db.tag.find_first(where={'id': subtag_id}, include={'posts': True})
            if subtag_posts:
                for i, post in enumerate(subtag_posts.posts):
                    print(f'[*] {i}/{len(subtag_posts.posts)}', end='\r')
                    async with db.tx() as tx:
                        await tx.post.update(where={'id': post.id},
                                             data={'tags': {'connect': [{'id': main_tag_id}]}})
                        await tx.post.update(where={'id': post.id},
                                             data={'tags': {'disconnect': [{'id': subtag_id}]}})
            await db.tag.delete(where={'id': subtag_id})
    print('[*] Subtags processed')

    print('[*] Processing unsued tags')
    for tag_id_min_curr in range(0, max_tag_id.id, step):
        print(f'[*] Processing tags from {tag_id_min_curr} to {tag_id_min_curr + step}')
        tags = await db.tag.find_many(skip=tag_id_min_curr, take=step)
        for i, tag in enumerate(tags):
            print(f'[*] {i - tag_id_min_curr:04d}/{step}', end='\r')
            posts = await db.post.find_many(where={'tags': {'some': {'id': tag.id}}})
            if len(posts) <= 1:
                print(f'[*] Deleting tag {tag.id}')
                await db.tag.delete(where={'id': tag.id})
    print('[*] Unused tags processed')

    print('[*] Tags processed')
    await db.disconnect()
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
