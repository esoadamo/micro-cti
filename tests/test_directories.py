import os
from pathlib import Path
from unittest.mock import patch
import directories


def test_directory_constants_exist():
    assert directories.DIR_LOGS.exists()
    assert directories.DIR_DATA.exists()
    assert directories.DIR_BACKUP.exists()
    assert directories.DIR_CACHE.exists()
    assert directories.DIR_CONFIG.exists()
    assert directories.FILE_CONFIG == directories.DIR_CONFIG / "config.toml"


def test_directories_custom_env_paths(tmp_path):
    custom_logs = tmp_path / "custom_logs"
    custom_data = tmp_path / "custom_data"
    custom_backup = tmp_path / "custom_backup"
    custom_cache = tmp_path / "custom_cache"
    custom_config = tmp_path / "custom_config"

    env_vars = {
        "UCTI_LOG_DIR": str(custom_logs),
        "UCTI_DATA_DIR": str(custom_data),
        "UCTI_BACKUP_DIR": str(custom_backup),
        "UCTI_CACHE_DIR": str(custom_cache),
        "UCTI_CONFIG_DIR": str(custom_config),
    }

    with patch.dict(os.environ, env_vars):
        import importlib
        importlib.reload(directories)

        assert directories.DIR_LOGS == custom_logs
        assert directories.DIR_DATA == custom_data
        assert directories.DIR_BACKUP == custom_backup
        assert directories.DIR_CACHE == custom_cache
        assert directories.DIR_CONFIG == custom_config
        assert directories.FILE_CONFIG == custom_config / "config.toml"

        assert custom_logs.exists()
        assert custom_data.exists()
        assert custom_backup.exists()
        assert custom_cache.exists()
        assert custom_config.exists()

    # Reload again without env vars to restore original
    importlib.reload(directories)
