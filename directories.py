from os import environ
from pathlib import Path

DIR_LOGS = Path(environ.get("UCTI_LOG_DIR", f"{(Path(__file__).parent / 'logs').resolve()}"))
DIR_DATA = Path(environ.get("UCTI_DATA_DIR", f"{(Path(__file__).parent / "data").resolve()}"))
DIR_BACKUP = Path(environ.get("UCTI_BACKUP_DIR", f"{(Path(__file__).parent / 'backup').resolve()}"))
DIR_CACHE = Path(environ.get("UCTI_CACHE_DIR", f"{(Path(__file__).parent / 'cache').resolve()}"))
DIR_CONFIG = Path(environ.get("UCTI_CONFIG_DIR", f"{(Path(__file__).parent / 'config').resolve()}"))
FILE_CONFIG = DIR_CONFIG / 'config.toml'


DIR_DATA.mkdir(parents=True, exist_ok=True)
DIR_LOGS.mkdir(parents=True, exist_ok=True)
DIR_BACKUP.mkdir(parents=True, exist_ok=True)
DIR_CACHE.mkdir(parents=True, exist_ok=True)
DIR_CONFIG.mkdir(parents=True, exist_ok=True)
