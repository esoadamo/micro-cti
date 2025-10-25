from datetime import date, datetime
from typing import AsyncIterable, Optional

from prisma import Prisma
from asyncio import Lock


class DBConnector:
    instance: Optional["DBConnector"] = None
    instance_lock = Lock()

    def __init__(self):
        self.__conn_lock = Lock()
        self.__clients_count = 0
        self.__conn: Optional[Prisma] = None

    async def __aenter__(self) -> Prisma:
        async with self.__conn_lock:
            self.__clients_count += 1
            if self.__conn is not None:
                return self.__conn
            conn = Prisma()
            await conn.connect()
            print('[*] Database connection estabilished successfuly')
            self.__conn = conn
            return self.__conn
    
    async def __aexit__(self, exc_type, exc, tb):
        async with self.__conn_lock:
            self.__clients_count -= 1
            assert self.__clients_count >= 0
            if self.__clients_count == 0:
                await self.__conn.disconnect()
                print("[*] Database disconnected")
                self.__conn = None

    @classmethod
    async def get(cls) -> "DBConnector":
        if cls.instance is not None:
            return cls.instance

        async with cls.instance_lock:
            if cls.instance is not None:
                return cls.instance
            cls.instance = DBConnector()
            return cls.instance


async def get_db_session() -> AsyncIterable[Prisma]:
    async with (await DBConnector.get()) as conn:
        yield conn


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))
