from datetime import date, datetime
from prisma import Prisma
from threading import Lock

DB_LOCK = Lock()


# noinspection PyDefaultArgument
async def get_db(cache={}) -> Prisma:
    if "db" not in cache:
        with DB_LOCK:
            if "db" not in cache:
                cache["db"] = Prisma()
                await cache["db"].connect()
                print('[*] Database connection estabilished successfuly')
    return cache["db"]


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))
