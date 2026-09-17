import pytest
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from backup_logic import (
    backup_saves,
    is_reparse_point,
)


# ============================================================
#  walk_error callback
# ============================================================

class TestBackupSavesWalkError:
    """Тесты обработки ошибок при обходе директорий."""

    def test_walk_error_is_logged(self, temp_dirs):
        """Ошибка доступа к поддиректории логируется через walk_error."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write("Content")

        state = {"stop_flag": False}
        log_messages = []

        # Мокаем os.walk чтобы он вызывал onerror
        original_walk = os.walk

        def mock_walk(top, **kwargs):
            onerror = kwargs.get("onerror")
            # Сначала возвращаем нормальные данные
            yield from original_walk(top, **{k: v for k, v in kwargs.items() if k != "onerror"})
            # Затем вызываем onerror с фейковой ошибкой
            if onerror:
                err = OSError(13, "Permission denied", "/some/path")
                onerror(err)

        with patch("backup_logic.os.walk", side_effect=mock_walk):
            stats = backup_saves(
                source_dir=source,
                backup_dir=backup,
                skip_links=False,
                exclude_patterns_str="",
                all_sources_in_profile=[source],
                state=state,
                log=log_messages.append,
            )

        assert any("Error accessing path" in msg for msg in log_messages)
        assert stats["files_copied"] == 1


# ============================================================
#  Относительные паттерны исключений
# ============================================================

class TestBackupSavesRelativePatterns:
    """Тесты паттернов с относительными путями."""

    def test_relative_pattern_matches_subdir(self, temp_dirs):
        """Паттерн 'logs/*' матчит файлы в поддиректории logs/."""
        source, backup = temp_dirs

        logs_dir = os.path.join(source, "logs")
        os.makedirs(logs_dir)

        with open(os.path.join(logs_dir, "app.log"), "w") as f:
            f.write("Log content")
        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write("Text")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="logs/*",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_skipped"] == 1
        assert stats["files_copied"] == 1

    def test_wildcard_in_subdir_pattern(self, temp_dirs):
        """Паттерн 'temp/*.tmp' матчит только .tmp в temp/."""
        source, backup = temp_dirs

        temp_dir = os.path.join(source, "temp")
        os.makedirs(temp_dir)

        with open(os.path.join(temp_dir, "file.tmp"), "w") as f:
            f.write("Temp")
        with open(os.path.join(temp_dir, "file.txt"), "w") as f:
            f.write("Text")
        with open(os.path.join(source, "file.tmp"), "w") as f:
            f.write("Root temp")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="temp/*.tmp",
            all_sources_in_profile=[source],
            state=state,
        )

        # Только temp/file.tmp пропущен
        assert stats["files_skipped"] == 1
        assert stats["files_copied"] == 2


# ============================================================
#  Двойная запятая в паттернах
# ============================================================

class TestBackupSavesPatternEdgeCases:
    """Тесты граничных случаев паттернов."""

    def test_double_comma_in_patterns(self, temp_dirs):
        """Двойная запятая '*, , *.tmp' не ломает парсинг."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file.log"), "w") as f:
            f.write("Log")
        with open(os.path.join(source, "file.tmp"), "w") as f:
            f.write("Temp")
        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write("Text")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="*.log, , *.tmp",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_skipped"] == 2
        assert stats["files_copied"] == 1

    def test_trailing_comma_in_patterns(self, temp_dirs):
        """Запятая в конце '*.log,' не создаёт пустой паттерн."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file.log"), "w") as f:
            f.write("Log")
        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write("Text")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="*.log,",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_skipped"] == 1
        assert stats["files_copied"] == 1


# ============================================================
#  Граничные случаи time_diff
# ============================================================

class TestBackupSavesTimeDiffEdgeCases:
    """Тесты граничных значений разницы времени модификации."""

    def test_time_diff_exactly_2_seconds(self, temp_dirs):
        """Разница ровно 2 секунды (source новее) — файл копируется."""
        source, backup = temp_dirs

        src_file = os.path.join(source, "file.txt")
        with open(src_file, "w") as f:
            f.write("Content")

        state = {"stop_flag": False}

        # Первый бэкап
        backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        # Устанавливаем разницу ровно 2 секунды (destination СТАРШЕ source)
        dest_file = os.path.join(backup, os.path.basename(source), "file.txt")
        src_stat = os.stat(src_file)
        new_time = src_stat.st_mtime - 2.0  # destination старше на 2 секунды
        os.utime(dest_file, (new_time, new_time))

        # Второй бэкап
        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        # time_diff = 2.0, abs(2.0) < 2.0 → False, time_diff < 0 → False
        # Поэтому файл копируется
        assert stats["files_copied"] == 1

    def test_time_diff_1_99_seconds(self, temp_dirs):
        """Разница 1.99 секунды — файл считается неизменённым."""
        source, backup = temp_dirs

        src_file = os.path.join(source, "file.txt")
        with open(src_file, "w") as f:
            f.write("Content")

        state = {"stop_flag": False}

        # Первый бэкап
        backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        # Устанавливаем разницу 1.99 секунды
        dest_file = os.path.join(backup, os.path.basename(source), "file.txt")
        src_stat = os.stat(src_file)
        new_time = src_stat.st_mtime + 1.99
        os.utime(dest_file, (new_time, new_time))

        # Второй бэкап
        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        # abs(1.99) < 2.0 → True, файл не копируется
        assert stats["files_copied"] == 0
        assert stats["files_skipped"] == 1


# ============================================================
#  is_reparse_point с моком Windows API
# ============================================================

class TestIsReparsePointMocked:
    """Тесты is_reparse_point с моком ctypes.windll."""

    def test_reparse_point_detected(self, temp_dirs):
        """Файл с атрибутом FILE_ATTRIBUTE_REPARSE_POINT определяется как reparse point."""
        source, _ = temp_dirs
        file_path = os.path.join(source, "test.txt")

        with open(file_path, "w") as f:
            f.write("test")

        FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
        FILE_ATTRIBUTE_NORMAL = 0x80

        # Мокаем GetFileAttributesW чтобы возвращать REPARSE_POINT
        with patch("backup_logic.ctypes.windll.kernel32.GetFileAttributesW") as mock_attrs:
            mock_attrs.return_value = FILE_ATTRIBUTE_REPARSE_POINT
            assert is_reparse_point(file_path) is True

    def test_normal_file_not_reparse(self, temp_dirs):
        """Обычный файл без REPARSE_POINT не определяется как reparse point."""
        source, _ = temp_dirs
        file_path = os.path.join(source, "test.txt")

        with open(file_path, "w") as f:
            f.write("test")

        FILE_ATTRIBUTE_NORMAL = 0x80

        with patch("backup_logic.ctypes.windll.kernel32.GetFileAttributesW") as mock_attrs:
            mock_attrs.return_value = FILE_ATTRIBUTE_NORMAL
            assert is_reparse_point(file_path) is False

    def test_invalid_path_returns_false(self):
        """Невалидный путь (GetFileAttributesW возвращает -1) не является reparse point."""
        with patch("backup_logic.ctypes.windll.kernel32.GetFileAttributesW") as mock_attrs:
            mock_attrs.return_value = -1
            assert is_reparse_point("/nonexistent/path") is False

    def test_exception_returns_false(self, temp_dirs):
        """Исключение при вызове GetFileAttributesW возвращает False."""
        source, _ = temp_dirs
        file_path = os.path.join(source, "test.txt")

        with open(file_path, "w") as f:
            f.write("test")

        with patch("backup_logic.ctypes.windll.kernel32.GetFileAttributesW") as mock_attrs:
            mock_attrs.side_effect = Exception("Windows API error")
            assert is_reparse_point(file_path) is False


# ============================================================
#  backup_saves с несуществующим source_dir
# ============================================================

class TestBackupSavesNonexistentSource:
    """Тесты backup_saves с несуществующей source директорией."""

    def test_nonexistent_source_logs_message(self, temp_dirs):
        """Несуществующий source логирует сообщение."""
        source, backup = temp_dirs
        nonexistent = os.path.join(source, "nonexistent")

        state = {"stop_flag": False}
        log_messages = []

        stats = backup_saves(
            source_dir=nonexistent,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[nonexistent],
            state=state,
            log=log_messages.append,
        )

        assert any("Source directory does not exist" in msg for msg in log_messages)
        assert stats["files_copied"] == 0
        assert stats["errors"] == 0


# ============================================================
#  time_diff < 0 логирует "destination is newer"
# ============================================================

class TestBackupSavesDestinationNewerLogging:
    """Тесты логирования когда destination новее source."""

    def test_destination_newer_is_logged(self, temp_dirs):
        """Когда destination новее source, логируется 'destination is newer'."""
        source, backup = temp_dirs

        src_file = os.path.join(source, "file.txt")
        with open(src_file, "w") as f:
            f.write("Old content")

        # Устанавливаем старое время
        old_time = time.time() - 3600
        os.utime(src_file, (old_time, old_time))

        state = {"stop_flag": False}
        log_messages = []

        # Первый бэкап
        backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        # Делаем destination новее
        dest_file = os.path.join(backup, os.path.basename(source), "file.txt")
        new_time = time.time() + 3600
        os.utime(dest_file, (new_time, new_time))

        # Второй бэкап с логированием
        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
            log=log_messages.append,
        )

        assert any("destination is newer" in msg for msg in log_messages)
        assert stats["files_copied"] == 0
        assert stats["files_skipped"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])