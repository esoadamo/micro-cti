import gzip
import asyncio

from db import DBConnector
from directories import DIR_BACKUP


async def main() -> None:
    print('[*] Process started')
    async with (await DBConnector.get()) as db:
        step = 1000
        curr_id = 0
        file_backup = DIR_BACKUP / "posts.jsonl.gz"

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


if __name__ == "__main__":
    asyncio.run(main())
