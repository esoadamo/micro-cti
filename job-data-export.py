import gzip
import asyncio

from db import DBConnector
from directories import DIR_BACKUP
from models import Post
from sqlmodel import select, or_
from sqlalchemy.orm import selectinload


async def main() -> None:
    print('[*] Process started')
    async with (await DBConnector.get()) as db:
        step = 1000
        curr_id = 0
        file_backup = DIR_BACKUP / "posts.jsonl.gz"

        with gzip.open(file_backup, 'wt') as f:
            while True:
                print(f'[*] Next batch starting from id: {curr_id}\r', end='', flush=True)
                stmt = select(Post).where(or_(Post.is_hidden == False, Post.is_ingested == False), Post.id > curr_id).order_by(Post.id).limit(step).options(selectinload(Post.tags))
                res = await db.exec(stmt)
                posts = res.all()
                if not posts:
                    break
                curr_id = posts[-1].id

                for post in posts:
                    f.write(post.model_dump_json() + '\n')

        print(f'[*] Backup saved to {file_backup}')


if __name__ == "__main__":
    asyncio.run(main())
