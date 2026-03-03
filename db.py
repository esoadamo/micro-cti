import os
import ssl
import urllib.parse
from datetime import date, datetime, timedelta
from typing import AsyncIterable, Optional

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

DB_TIMEOUT = 30

DATABASE_URL = os.environ.get("DATABASE_URL", "mysql+aiomysql://root:microcti1234@127.0.0.1:3306/microcti")

if DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+aiomysql://")

# Parse and strip JDBC-style query parameters that aiomysql doesn't understand,
# then build an appropriate ssl context from them.
_parsed = urllib.parse.urlparse(DATABASE_URL)
_qs = urllib.parse.parse_qs(_parsed.query, keep_blank_values=True)

def _bool_param(qs: dict, key: str, default: bool = False) -> bool:
    val = qs.get(key, [None])[0]
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes")

_use_ssl = _bool_param(_qs, "useSSL")
_verify_cert = _bool_param(_qs, "verifyServerCertificate", default=True)

# Build ssl context only if useSSL is requested
_ssl_context = None
if _use_ssl:
    _ssl_context = ssl.create_default_context()
    if not _verify_cert:
        _ssl_context.check_hostname = False
        _ssl_context.verify_mode = ssl.CERT_NONE

# Strip all JDBC-style params — pass only what aiomysql natively accepts
_AIOMYSQL_KNOWN_PARAMS = {
    "charset", "collation", "db", "use_unicode", "client_flag",
    "autocommit", "local_infile", "auth_plugin", "program_name",
    "server_public_key", "read_default_file", "conv", "cursorclass",
}
_filtered = {k: v for k, v in _qs.items() if k.lower() in _AIOMYSQL_KNOWN_PARAMS}
_new_query = urllib.parse.urlencode(_filtered, doseq=True)
DATABASE_URL = urllib.parse.urlunparse(_parsed._replace(query=_new_query))

_connect_args: dict = {"connect_timeout": DB_TIMEOUT}
if _ssl_context is not None:
    _connect_args["ssl"] = _ssl_context


engine = create_async_engine(
    DATABASE_URL,
    pool_recycle=3600,
    connect_args=_connect_args
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=SQLModelAsyncSession,
    expire_on_commit=False,
)


class DBConnector:
    def __init__(self):
        self.session: Optional[SQLModelAsyncSession] = None

    async def __aenter__(self) -> SQLModelAsyncSession:
        self.session = AsyncSessionLocal()
        return self.session
    
    async def __aexit__(self, exc_type, exc, tb):
        if self.session:
            await self.session.close()
            self.session = None

    @classmethod
    async def get(cls) -> "DBConnector":
        return DBConnector()


async def get_db_session() -> AsyncIterable[SQLModelAsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))
