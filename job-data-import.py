from pathlib import Path
import gzip
import asyncio

from prisma.models import Post

from db import get_db


async def main() -> None:
    print('[*] Process started')
    db = await get_db()
    print('[*] Database connected')
    file_backup = Path('posts.jsonl')

    with gzip.open(file_backup, 'rt') as f:
        while True:
            line = f.readline()
            if not line:
                break
            post = Post.model_validate_json(line)
            print(f'[*] Post id: {post.id}', flush=True)
            data = post.model_dump()
            del data['id']
            tags = data['tags']
            del data['tags']
            del data['iocs']
            post = await db.post.create(data=data)
            if tags:
                for tag in tags:
                    del tag['id']
                    del tag['posts']
                    tag = await db.tag.upsert(where={'name': tag['name']}, data={'create': tag, 'update': {}})
                    await db.post.update(where={'id': post.id}, data={'tags': {'connect': [{'id': tag.id}]}})

    print(f'[*] Restored data from {file_backup}')
    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
