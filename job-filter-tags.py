import asyncio
from typing import Dict, Set, AsyncIterable, List

from fuzzywuzzy import fuzz
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, desc
from sqlalchemy.orm import selectinload
from models import Tag, Post


async def get_tags(db: AsyncSession, max_tag_id: int, step: int) -> AsyncIterable[List[Tag]]:
    for tag_id_min_curr in range(0, max_tag_id, step):
        stmt = select(Tag).offset(tag_id_min_curr).limit(step).order_by(Tag.id)
        res = await db.exec(stmt)
        tags = res.all()
        if tags:
            yield tags


async def main() -> int:
    print('[*] Process started')
    async with DBConnector.get() as db:
        step = 500

        print('[*] Loading tags')
        max_tag_id_obj = await db.exec(select(Tag).order_by(desc(Tag.id)).limit(1))
        max_tag_id_obj = max_tag_id_obj.first()
        max_tag_id = max_tag_id_obj.id if max_tag_id_obj else 0
        if not max_tag_id: return 0

        print('[*] Deleting tags with short or long name')
        to_delete: Set[int] = set()
        page_i = 0
        async for tags in get_tags(db, max_tag_id, step):
            page_i += 1
            for tag in tags:
                print(f'[*] {tag.id}/{max_tag_id} (page {page_i})', end='\r')
                if len(tag.name) < 5 or len(tag.name) > 50:
                    to_delete.add(tag.id)
        for tag_id in to_delete:
            print(f'[*] Deleting tag {tag_id}')
            tag_to_delete = await db.get(Tag, tag_id)
            if tag_to_delete: await db.delete(tag_to_delete)
        await db.commit()
        print('[*] Tags with short or long name deleted')

        combine: Dict[int, Set[int]] = {}
        ignore: Set[int] = set()

        print('[*] Processing subtags')

        page_i = 0
        async for tags in get_tags(db, max_tag_id, step):
            page_i += 1
            print(f'[*] Processing tags from {tags[0].id} to {tags[-1].id} (page {page_i})')

            subpage_i = 0
            async for subtags in get_tags(db, max_tag_id, step):
                subpage_i += 1

                if subtags[-1].id < tags[0].id:
                    continue

                for i, tag in enumerate(tags):
                    # Print percentage and carriage return to rewrite the line
                    print(f'[*] {tag.id}/{max_tag_id} (subpage {subpage_i})', end='\r')
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
                        subtag_posts_stmt = select(Post).where(Post.tags.any(Tag.id == subtag_id)).options(selectinload(Post.tags))
                        subtag_posts_res = await db.exec(subtag_posts_stmt)
                        subtag_posts = subtag_posts_res.all()
                        if subtag_posts:
                            main_tag = await db.get(Tag, main_tag_id)
                            for i, post in enumerate(subtag_posts):
                                print(f'[*] {i}/{len(subtag_posts)}', end='\r')
                                if main_tag not in post.tags:
                                    post.tags.append(main_tag)
                                post.tags = [t for t in post.tags if t.id != subtag_id]
                                db.add(post)
                            await db.commit()
                        subtag_to_delete = await db.get(Tag, subtag_id)
                        if subtag_to_delete: await db.delete(subtag_to_delete)
                        await db.commit()
                combine.clear()
        print('[*] Subtags processed')

        print('[*] Processing unsued tags')
        page_i = 0
        async for tags in get_tags(db, max_tag_id, step):
            page_i += 1
            for i, tag in enumerate(tags):
                print(f'[*] {tag.id}/{max_tag_id} (page {page_i})', end='\r')
                posts_stmt = select(Post).where(Post.tags.any(Tag.id == tag.id)).limit(2)
                posts_res = await db.exec(posts_stmt)
                posts = posts_res.all()
                if len(posts) <= 1:
                    print(f'[*] Deleting tag {tag.id}')
                    tag_to_delete = await db.get(Tag, tag.id)
                    if tag_to_delete: await db.delete(tag_to_delete)
                    await db.commit()
        print('[*] Unused tags processed')

        print('[*] Tags processed')
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
