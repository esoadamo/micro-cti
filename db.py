from datetime import date, datetime
from prisma import Prisma


async def get_db(cache = {}) -> Prisma:
    if "db" not in cache:
        cache["db"] = Prisma()
        await cache["db"].connect()
        print('[*] database connection estabilished successfuly')
    return cache["db"]



def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))
