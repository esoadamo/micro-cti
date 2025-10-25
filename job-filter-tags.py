import asyncio
from typing import Dict, Set, AsyncIterable, List

from fuzzywuzzy import fuzz
from prisma import Prisma
from prisma.bases import BasePost
from prisma.models import Tag

from db import DBConnector


class PostId(BasePost):
    id: int


async def get_tags(db: Prisma, max_tag_id: int, step: int) -> AsyncIterable[List[Tag]]:
    for tag_id_min_curr in range(0, max_tag_id, step):
        tags = await db.tag.find_many(skip=tag_id_min_curr, take=step, order={'id': 'asc'})
        if tags:
            yield tags


async def main() -> int:
    print('[*] Process started')
    async with DBConnector.get() as db:
        step = 500

        print('[*] Loading tags')
        max_tag_id = await db.tag.find_first(order={'id': 'desc'})

        print('[*] Deleting tags with short or long name')
        to_delete: Set[int] = set()
        page_i = 0
        async for tags in get_tags(max_tag_id.id, step):
            page_i += 1
            for tag in tags:
                print(f'[*] {tag.id}/{max_tag_id.id} (page {page_i})', end='\r')
                if len(tag.name) < 5 or len(tag.name) > 50:
                    to_delete.add(tag.id)
        for tag_id in to_delete:
            print(f'[*] Deleting tag {tag_id}')
            await db.tag.delete(where={'id': tag_id})
        print('[*] Tags with short or long name deleted')

        combine: Dict[int, Set[int]] = {}
        ignore: Set[int] = set()

        print('[*] Processing subtags')

        page_i = 0
        async for tags in get_tags(max_tag_id.id, step):
            page_i += 1
            print(f'[*] Processing tags from {tags[0].id} to {tags[-1].id} (page {page_i})')

            subpage_i = 0
            async for subtags in get_tags(max_tag_id.id, step):
                subpage_i += 1

                if subtags[-1].id < tags[0].id:
                    continue

                for i, tag in enumerate(tags):
                    # Print percentage and carriage return to rewrite the line
                    print(f'[*] {tag.id}/{max_tag_id.id} (subpage {subpage_i})', end='\r')
                    if tag.id in ignore:
                        continue

                    for j, tag2 in enumerate(subtags):
                        if tag2.id in ignore or tag2.id <= tag.id:
                            continue
                        if tag.name.lower().startswith(tag2.name.lower()):
                            combine.setdefault(tag2.id, set()).add(tag.id)
                            ignore.update((tag.id, tag2.id))
                            break
                        elif tag2.name.lower().startswith(tag.name.lower()):
                            combine.setdefault(tag.id, set()).add(tag2.id)
                            ignore.update((tag.id, tag2.id))
                            break
                        elif fuzz.ratio(tag.name.lower(), tag2.name.lower()) > 90:
                            combine.setdefault(tag.id, set()).add(tag2.id)
                            ignore.update((tag.id, tag2.id))
                            break

                for main_tag_id, subtags_ids in combine.items():
                    for subtag_id in subtags_ids:
                        print(f'[*] Merging {subtag_id} into {main_tag_id}')
                        subtag_posts = await PostId.prisma(client=db).find_many(
                            where={'tags': {'some': {'id': subtag_id}}})
                        if subtag_posts:
                            for i, post in enumerate(subtag_posts):
                                print(f'[*] {i}/{len(subtag_posts)}', end='\r')
                                async with db.tx() as tx:
                                    await tx.post.update(where={'id': post.id},
                                                         data={'tags': {'connect': [{'id': main_tag_id}]}})
                                    await tx.post.update(where={'id': post.id},
                                                         data={'tags': {'disconnect': [{'id': subtag_id}]}})
                        await db.tag.delete(where={'id': subtag_id})
                combine.clear()
        print('[*] Subtags processed')

        print('[*] Processing unsued tags')
        page_i = 0
        async for tags in get_tags(max_tag_id.id, step):
            page_i += 1
            for i, tag in enumerate(tags):
                print(f'[*] {tag.id}/{max_tag_id.id} (page {page_i})', end='\r')
                posts = await db.post.find_many(where={'tags': {'some': {'id': tag.id}}})
                if len(posts) <= 1:
                    print(f'[*] Deleting tag {tag.id}')
                    await db.tag.delete(where={'id': tag.id})
        print('[*] Unused tags processed')

        print('[*] Tags processed')
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
