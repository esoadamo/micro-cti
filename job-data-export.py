from pathlib import Path
import gzip
import asyncio
from os import environ

from db import get_db


async def main() -> None:
    print('[*] Process started')
    db = await get_db()
    print('[*] Database connected')
    step = 1000
    curr_id = 0
    file_backup = Path(environ.get('UCTI_BACKUP_FILE', 'posts.jsonl.gz'))

    with gzip.open(file_backup, 'wt') as f:
        while True:
            print(f'[*] Next batch starting from id: {curr_id}\r', end='', flush=True)
            posts = await db.post.find_many(
                where={'OR': [{'is_hidden': False}, {'is_ingested': False}], 'id': {'gt': curr_id}},
                take=step,
                order={'id': 'asc'},
                include={'tags': True}
            )
            if not posts:
                break
            curr_id = posts[-1].id

            for post in posts:
                f.write(post.model_dump_json() + '\n')

    print(f'[*] Backup saved to {file_backup}')
    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
