from pathlib import Path
import gzip
import asyncio
from typing import List

from prisma import Prisma
from prisma.models import Post

from db import DBConnector


async def process_post_data(db: Prisma, post_line: str, semaphore: asyncio.Semaphore) -> None:
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

            # Find existing post or create new one
            existing_post = await db.post.find_unique(where={'id': post.id})
            if not existing_post:
                db_post = await db.post.create(data=data)
            else:
                db_post = existing_post

            # Process tags if they exist
            if tags:
                for tag in tags:
                    del tag['id']
                    del tag['posts']
                    db_tag = await db.tag.upsert(
                        where={'name': tag['name']},
                        data={'create': tag, 'update': {}}
                    )
                    await db.post.update(
                        where={'id': db_post.id},
                        data={'tags': {'connect': [{'id': db_tag.id}]}}
                    )

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
