import pytest
import os
import sys
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import CloudBackupTool

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================
#  Тесты log_exit_or_crash
# ============================================================

class TestLogExitOrCrash:
    """Тесты функции логирования крашей."""

    def test_log_exit_or_crash_writes_to_file(self, tmp_path):
        """log_exit_or_crash записывает сообщение в файл."""
        # Мокируем путь к лог-файлу
        crash_log = tmp_path / "crash.log"

        # Импортируем функцию
        with patch("CloudBackupTool.CRASH_LOG_FILE", str(crash_log)):
            from CloudBackupTool import log_exit_or_crash
            log_exit_or_crash("Test crash reason")

        assert crash_log.exists()
        content = crash_log.read_text(encoding="utf-8")
        assert "Test crash reason" in content
        assert "[CRITICAL]" in content

    def test_log_exit_or_crash_with_exception(self, tmp_path):
        """log_exit_or_crash записывает traceback при наличии exc_info."""
        crash_log = tmp_path / "crash.log"

        try:
            raise ValueError("Test exception")
        except ValueError:
            exc_info = sys.exc_info()

            with patch("CloudBackupTool.CRASH_LOG_FILE", str(crash_log)):
                from CloudBackupTool import log_exit_or_crash
                log_exit_or_crash("Exception occurred", exc_info)

        content = crash_log.read_text(encoding="utf-8")
        assert "ValueError" in content
        assert "Test exception" in content
        assert "Traceback" in content

    def test_log_exit_or_crash_handles_write_error(self, tmp_path):
        """log_exit_or_crash не падает если нельзя записать в файл."""
        # Путь в несуществующую директорию
        bad_path = tmp_path / "nonexistent" / "crash.log"

        with patch("CloudBackupTool.CRASH_LOG_FILE", str(bad_path)):
            from CloudBackupTool import log_exit_or_crash
            # Не должно вызвать исключение
            log_exit_or_crash("Test reason")


# ============================================================
#  Тесты миграции конфига
# ============================================================

class TestConfigMigration:
    """Тесты миграции старого формата конфига в новый."""

    def test_migration_from_legacy_format(self, tmp_path):
        """Старый формат (без profiles) мигрирует в новый."""
        config_file = tmp_path / "config.json"
        legacy_config = {
            "source_dirs": ["C:/test/source"],
            "backup_dir": "D:/backup",
            "skip_links": True,
            "backup_schedule": "Daily 23:00",
            "custom_time": "",
            "exclude_patterns": "*.tmp",
            "auto_start_backup": True,
            "start_minimized": False,
            "log_to_file": True,
        }
        config_file.write_text(json.dumps(legacy_config), encoding="utf-8")

        # Мокируем путь к конфигу
        with patch("CloudBackupTool.CONFIG_FILE", str(config_file)):
            # Создаём минимальный BackupApp без UI
            from CloudBackupTool import BackupApp
            app = MagicMock(spec=BackupApp)
            app.settings = {
                "global": {
                    "autorun": False,
                    "start_minimized": False,
                    "log_to_file": True,
                    "active_profile": "Default",
                },
                "profiles": {
                    "Default": {
                        "source_dirs": [],
                        "backup_dir": "",
                        "skip_links": True,
                        "backup_schedule": "None",
                        "custom_time": "",
                        "exclude_patterns": "",
                        "enabled": False,
                        "auto_start_backup": False,
                        "weekly_days": ["Monday"],
                        "weekly_time": "23:00",
                    }
                },
            }
            # Вызываем load_config напрямую
            BackupApp.load_config(app)

        # Проверяем что миграция произошла
        assert "profiles" in app.settings
        assert "Default" in app.settings["profiles"]
        profile = app.settings["profiles"]["Default"]
        assert profile["source_dirs"] == ["C:/test/source"]
        assert profile["backup_dir"] == "D:/backup"
        assert profile["enabled"] is True  # auto_start_backup → enabled
        assert profile["auto_start_backup"] is True

    def test_load_config_new_format(self, tmp_path):
        """Новый формат конфига загружается корректно."""
        config_file = tmp_path / "config.json"
        new_config = {
            "global": {
                "autorun": False,
                "start_minimized": True,
                "log_to_file": False,
                "active_profile": "Work",
            },
            "profiles": {
                "Default": {
                    "source_dirs": ["C:/default"],
                    "backup_dir": "D:/backup",
                    "skip_links": True,
                    "backup_schedule": "None",
                    "custom_time": "",
                    "exclude_patterns": "",
                    "enabled": False,
                    "auto_start_backup": False,
                    "weekly_days": ["Monday"],
                    "weekly_time": "23:00",
                },
                "Work": {
                    "source_dirs": ["C:/work"],
                    "backup_dir": "E:/work_backup",
                    "skip_links": False,
                    "backup_schedule": "Custom",
                    "custom_time": "120",
                    "exclude_patterns": "*.log",
                    "enabled": True,
                    "auto_start_backup": True,
                    "weekly_days": ["Monday", "Friday"],
                    "weekly_time": "18:00",
                },
            },
        }
        config_file.write_text(json.dumps(new_config), encoding="utf-8")

        with patch("CloudBackupTool.CONFIG_FILE", str(config_file)):
            from CloudBackupTool import BackupApp
            app = MagicMock(spec=BackupApp)
            app.settings = {
                "global": {
                    "autorun": False,
                    "start_minimized": False,
                    "log_to_file": True,
                    "active_profile": "Default",
                },
                "profiles": {"Default": {}},
            }
            BackupApp.load_config(app)

        assert app.settings["global"]["start_minimized"] is True
        assert app.settings["global"]["log_to_file"] is False
        assert app.settings["global"]["active_profile"] == "Work"
        assert "Work" in app.settings["profiles"]
        assert app.settings["profiles"]["Work"]["custom_time"] == "120"

    def test_load_config_missing_file(self, tmp_path):
        """Если конфиг отсутствует — используются значения по умолчанию."""
        config_file = tmp_path / "nonexistent.json"

        with patch("CloudBackupTool.CONFIG_FILE", str(config_file)):
            from CloudBackupTool import BackupApp
            app = MagicMock(spec=BackupApp)
            app.settings = {
                "global": {
                    "autorun": False,
                    "start_minimized": False,
                    "log_to_file": True,
                    "active_profile": "Default",
                },
                "profiles": {"Default": {}},
            }
            BackupApp.load_config(app)

        # Настройки не изменились
        assert app.settings["global"]["active_profile"] == "Default"

    def test_load_config_invalid_json(self, tmp_path):
        """Если конфиг битый — используются значения по умолчанию."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{invalid json", encoding="utf-8")

        with patch("CloudBackupTool.CONFIG_FILE", str(config_file)):
            from CloudBackupTool import BackupApp
            app = MagicMock(spec=BackupApp)
            app.settings = {
                "global": {
                    "autorun": False,
                    "start_minimized": False,
                    "log_to_file": True,
                    "active_profile": "Default",
                },
                "profiles": {"Default": {}},
            }
            BackupApp.load_config(app)

        # Настройки не изменились
        assert app.settings["global"]["active_profile"] == "Default"

    def test_load_config_adds_missing_fields(self, tmp_path):
        """Если в профиле отсутствуют поля enabled/weekly_days/weekly_time — они добавляются."""
        config_file = tmp_path / "config.json"
        incomplete_config = {
            "global": {
                "autorun": False,
                "start_minimized": False,
                "log_to_file": True,
                "active_profile": "Default",
            },
            "profiles": {
                "Default": {
                    "source_dirs": ["C:/test"],
                    "backup_dir": "D:/backup",
                    "auto_start_backup": True,
                    # Отсутствуют: enabled, weekly_days, weekly_time
                },
            },
        }
        config_file.write_text(json.dumps(incomplete_config), encoding="utf-8")

        with patch("CloudBackupTool.CONFIG_FILE", str(config_file)):
            from CloudBackupTool import BackupApp
            app = MagicMock(spec=BackupApp)
            app.settings = {
                "global": {
                    "autorun": False,
                    "start_minimized": False,
                    "log_to_file": True,
                    "active_profile": "Default",
                },
                "profiles": {"Default": {}},
            }
            BackupApp.load_config(app)

        profile = app.settings["profiles"]["Default"]
        assert "enabled" in profile
        assert "weekly_days" in profile
        assert "weekly_time" in profile
        assert profile["enabled"] is True  # из auto_start_backup
        assert profile["weekly_days"] == ["Monday"]
        assert profile["weekly_time"] == "23:00"


# ============================================================
#  Тесты check_backup_dir_available
# ============================================================

class TestCheckBackupDirAvailable:
    """Тесты проверки доступности директории бэкапа."""

    def test_existing_writable_dir(self, tmp_path):
        """Существующая доступная для записи директория возвращает True."""
        app = MagicMock(spec=CloudBackupTool.BackupApp)
        result = CloudBackupTool.BackupApp.check_backup_dir_available(app, str(tmp_path))
        assert result is True

    def test_nonexistent_dir(self, tmp_path):
        """Несуществующая директория возвращает False."""
        app = MagicMock(spec=CloudBackupTool.BackupApp)
        nonexistent = tmp_path / "nonexistent"
        result = CloudBackupTool.BackupApp.check_backup_dir_available(app, str(nonexistent))
        assert result is False

    def test_empty_path(self):
        """Пустой путь возвращает False."""
        app = MagicMock(spec=CloudBackupTool.BackupApp)
        result = CloudBackupTool.BackupApp.check_backup_dir_available(app, "")
        assert result is False

    def test_none_path(self):
        """None путь возвращает False."""
        app = MagicMock(spec=CloudBackupTool.BackupApp)
        result = CloudBackupTool.BackupApp.check_backup_dir_available(app, None)
        assert result is False

# ============================================================
#  Тесты _get_free_space
# ============================================================

class TestGetFreeSpace:
    """Тесты получения свободного места на диске."""

    def test_get_free_space_success(self):
        """Успешное получение свободного места."""
        with patch("CloudBackupTool.ctypes") as mock_ctypes:
            mock_free_bytes = MagicMock()
            mock_free_bytes.value = 10 * 1024 ** 3  # 10 GB
            mock_ctypes.c_ulonglong.return_value = mock_free_bytes
            mock_ctypes.pointer.return_value = MagicMock()

            from CloudBackupTool import BackupApp
            app = MagicMock(spec=BackupApp)

            result = BackupApp._get_free_space(app, "C:/")
            assert result == 10 * 1024 ** 3

    def test_get_free_space_exception(self):
        """При исключении возвращается None."""
        with patch("CloudBackupTool.ctypes") as mock_ctypes:
            mock_ctypes.windll.kernel32.GetDiskFreeSpaceExW.side_effect = Exception("Error")

            from CloudBackupTool import BackupApp
            app = MagicMock(spec=BackupApp)

            result = BackupApp._get_free_space(app, "C:/")
            assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])