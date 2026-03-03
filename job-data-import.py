from pathlib import Path
import gzip
import asyncio
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload
from models import Post, Tag

from db import DBConnector


async def process_post_data(db: AsyncSession, post_line: str, semaphore: asyncio.Semaphore) -> None:
    """Process a single post with semaphore-controlled concurrency"""
    async with semaphore:
        try:
            post = Post.model_validate_json(post_line)
            print(f'[*] Processing post id: {post.id}', flush=True)

            data = post.model_dump()
            del data['id']
            tags = data['tags']
            del data['tags']
            del data['iocs']

            existing_post = await db.get(Post, post.id)
            if not existing_post:
                db_post = Post(**data)
                db.add(db_post)
                await db.commit()
                await db.refresh(db_post)
            else:
                db_post = existing_post

            # Process tags if they exist
            if tags:
                stmt_post = select(Post).where(Post.id == db_post.id).options(selectinload(Post.tags))
                res_post = await db.exec(stmt_post)
                db_post = res_post.one()
                
                for tag in tags:
                    tag_name = tag['name']
                    stmt = select(Tag).where(Tag.name == tag_name).limit(1)
                    res = await db.exec(stmt)
                    db_tag = res.first()
                    if not db_tag:
                        db_tag = Tag(name=tag_name)
                        db.add(db_tag)
                        await db.commit()
                        await db.refresh(db_tag)
                        
                    if db_tag not in db_post.tags:
                        db_post.tags.append(db_tag)
                        db.add(db_post)
                await db.commit()

        except Exception as e:
            print(f'[!] Error processing post: {e}', flush=True)


async def main() -> None:
    print('[*] Process started')
    async with (await DBConnector.get()) as db:
        file_backup = Path('/tmp/posts.jsonl.gz')

        # Read all lines first
        print('[*] Reading file and preparing work queue...')
        post_lines: List[str] = []
        with gzip.open(file_backup, 'rt') as f:
            while True:
                line = f.readline()
                if not line:
                    break
                post_lines.append(line.strip())

        print(f'[*] Found {len(post_lines)} posts to process')

        # Create semaphore to limit concurrency to 16
        semaphore = asyncio.Semaphore(16)

        # Create tasks for all posts
        tasks = []
        for post_line in post_lines:
            if post_line:  # Skip empty lines
                task = asyncio.create_task(process_post_data(db, post_line, semaphore))
                tasks.append(task)

        # Wait for all tasks to complete
        print(f'[*] Starting parallel processing with 16 workers...')
        await asyncio.gather(*tasks, return_exceptions=True)

        print(f'[*] Restored data from {file_backup}')



if __name__ == "__main__":
    asyncio.run(main())
