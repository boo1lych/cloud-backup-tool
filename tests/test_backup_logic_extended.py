import pytest
import os
import sys
import time
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# Добавляем корневую директорию в путь для импорта
sys.path.insert(0, str(Path(__file__).parent.parent))

from backup_logic import (
    validate_custom_time,
    validate_hhmm,
    backup_saves,
    is_reparse_point,
)


class TestBackupSavesExtended:
    """Расширенные тесты для backup_saves."""

    def test_backup_with_skip_links(self, temp_dirs):
        """Тест пропуска символических ссылок."""
        source, backup = temp_dirs

        # Создаем обычный файл
        with open(os.path.join(source, "regular.txt"), "w") as f:
            f.write("Regular file")

        # Создаем символическую ссылку (если возможно)
        link_path = os.path.join(source, "link.txt")
        try:
            os.symlink(os.path.join(source, "regular.txt"), link_path)
            link_created = True
        except (OSError, NotImplementedError):
            # Windows может не поддерживать symlink без прав администратора
            link_created = False

        state = {"stop_flag": False}

        # Тест с skip_links=True
        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        if link_created:
            # Ссылка должна быть пропущена
            assert stats["files_copied"] == 1
            assert stats["files_skipped"] == 1
            assert os.path.exists(os.path.join(backup, os.path.basename(source), "regular.txt"))
            assert not os.path.exists(os.path.join(backup, os.path.basename(source), "link.txt"))
        else:
            # Если symlink не создан, то только обычный файл
            assert stats["files_copied"] == 1

    def test_backup_empty_source_dir(self, temp_dirs):
        """Тест бэкапа из пустой директории."""
        source, backup = temp_dirs
        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 0
        assert stats["files_skipped"] == 0
        assert stats["errors"] == 0

    def test_backup_deeply_nested_structure(self, temp_dirs):
        """Тест бэкапа глубоко вложенной структуры."""
        source, backup = temp_dirs

        # Создаем глубокую вложенность
        deep_path = os.path.join(source, "level1", "level2", "level3", "level4")
        os.makedirs(deep_path)

        with open(os.path.join(deep_path, "deep_file.txt"), "w") as f:
            f.write("Deep content")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 1

        # Проверяем что файл скопирован с сохранением структуры
        dest_file = os.path.join(
            backup, os.path.basename(source),
            "level1", "level2", "level3", "level4", "deep_file.txt"
        )
        assert os.path.exists(dest_file)

    def test_backup_with_log_callback(self, temp_dirs):
        """Тест что log callback вызывается для всех событий."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file1.txt"), "w") as f:
            f.write("Content 1")

        state = {"stop_flag": False}
        log_messages = []

        def mock_log(msg):
            log_messages.append(msg)

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="*.log",
            all_sources_in_profile=[source],
            state=state,
            log=mock_log,
        )

        # Должны быть сообщения о копировании
        assert len(log_messages) > 0
        assert any("Copied" in msg for msg in log_messages)

    def test_backup_exclude_patterns_variations(self, temp_dirs):
        """Тест разных форматов паттернов исключений."""
        source, backup = temp_dirs

        # Создаем файлы с разными расширениями
        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write("Text")
        with open(os.path.join(source, "file.log"), "w") as f:
            f.write("Log")
        with open(os.path.join(source, "file.tmp"), "w") as f:
            f.write("Temp")
        with open(os.path.join(source, "file.dat"), "w") as f:
            f.write("Data")

        state = {"stop_flag": False}

        # Тест 1: паттерн без wildcard (должен добавиться *)
        stats1 = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str=".log",
            all_sources_in_profile=[source],
            state=state,
        )
        assert stats1["files_skipped"] == 1
        assert stats1["files_copied"] == 3

        # Очищаем backup
        shutil.rmtree(backup)
        os.makedirs(backup)

        # Тест 2: паттерн с wildcard
        stats2 = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="*.log, *.tmp",
            all_sources_in_profile=[source],
            state=state,
        )
        assert stats2["files_skipped"] == 2
        assert stats2["files_copied"] == 2

    def test_backup_destination_newer(self, temp_dirs):
        """Тест что файл не копируется если destination новее."""
        source, backup = temp_dirs

        src_file = os.path.join(source, "file.txt")
        with open(src_file, "w") as f:
            f.write("Old content")

        # Устанавливаем старое время модификации
        old_time = time.time() - 3600  # 1 час назад
        os.utime(src_file, (old_time, old_time))

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

        # Изменяем время destination файла на более новое
        dest_file = os.path.join(backup, os.path.basename(source), "file.txt")
        new_time = time.time() + 3600  # 1 час в будущем
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

        # Файл не должен быть скопирован
        assert stats["files_copied"] == 0
        assert stats["files_skipped"] == 1

    def test_backup_multiple_sources_integration(self, temp_dirs):
        """Интеграционный тест с несколькими источниками."""
        source, backup = temp_dirs

        # Создаем два источника
        source1 = os.path.join(source, "project1")
        source2 = os.path.join(source, "project2")
        os.makedirs(source1)
        os.makedirs(source2)

        with open(os.path.join(source1, "file1.txt"), "w") as f:
            f.write("Project 1")
        with open(os.path.join(source2, "file2.txt"), "w") as f:
            f.write("Project 2")

        state = {"stop_flag": False}
        all_sources = [source1, source2]

        # Бэкапим оба источника
        stats1 = backup_saves(
            source_dir=source1,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=all_sources,
            state=state,
        )

        stats2 = backup_saves(
            source_dir=source2,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=all_sources,
            state=state,
        )

        assert stats1["files_copied"] == 1
        assert stats2["files_copied"] == 1

        # Проверяем что оба файла на месте
        assert os.path.exists(os.path.join(backup, "project1", "file1.txt"))
        assert os.path.exists(os.path.join(backup, "project2", "file2.txt"))


class TestValidateCustomTimeExtended:
    """Расширенные тесты для validate_custom_time."""

    def test_negative_values(self):
        """Тест отрицательных значений."""
        ok, err = validate_custom_time("-1")
        assert ok is False

        ok, err = validate_custom_time("-5:30")
        assert ok is False

    def test_very_large_values(self):
        """Тест очень больших значений."""
        ok, err = validate_custom_time("999999")
        assert ok is True  # Большое количество минут валидно

        ok, err = validate_custom_time("99:99")
        assert ok is False  # Часы/минуты вне диапазона

    def test_special_characters(self):
        """Тест специальных символов."""
        ok, err = validate_custom_time("12:30:45")
        assert ok is False

        ok, err = validate_custom_time("12-30")
        assert ok is False

        ok, err = validate_custom_time("12/30")
        assert ok is False

        ok, err = validate_custom_time("12.30")
        assert ok is False

    def test_whitespace_inside(self):
        """Тест пробелов внутри строки."""
        ok, err = validate_custom_time("12 :30")
        assert ok is False

        ok, err = validate_custom_time("12: 30")
        assert ok is False

        ok, err = validate_custom_time("1 20")
        assert ok is False


class TestValidateHHMMExtended:
    """Расширенные тесты для validate_hhmm."""

    def test_negative_values(self):
        """Тест отрицательных значений."""
        ok, err = validate_hhmm("-1:30")
        assert ok is False

        ok, err = validate_hhmm("12:-5")
        assert ok is False

    def test_single_digit(self):
        """Тест однозначных чисел."""
        ok, err = validate_hhmm("5:30")
        assert ok is True

        ok, err = validate_hhmm("09:05")
        assert ok is True

    def test_special_characters(self):
        """Тест специальных символов."""
        ok, err = validate_hhmm("12:30:45")
        assert ok is False

        ok, err = validate_hhmm("12-30")
        assert ok is False

        ok, err = validate_hhmm("12.30")
        assert ok is False

    def test_empty_and_whitespace(self):
        """Тест пустых строк и пробелов."""
        ok, err = validate_hhmm("")
        assert ok is False

        ok, err = validate_hhmm("   ")
        assert ok is False

        ok, err = validate_hhmm(":")
        assert ok is False


class TestIsReparsePointExtended:
    """Расширенные тесты для is_reparse_point."""

    def test_with_unicode_paths(self, temp_dirs):
        """Тест с Unicode путями."""
        source, _ = temp_dirs

        # Создаем файл с Unicode именем
        unicode_file = os.path.join(source, "файл_тест.txt")
        with open(unicode_file, "w", encoding="utf-8") as f:
            f.write("Unicode content")

        assert is_reparse_point(unicode_file) is False

    def test_with_long_paths(self, temp_dirs):
        """Тест с длинными путями."""
        source, _ = temp_dirs

        # Создаем длинный путь
        long_path = source
        for i in range(10):
            long_path = os.path.join(long_path, f"level_{i}")
        os.makedirs(long_path)

        long_file = os.path.join(long_path, "file.txt")
        with open(long_file, "w") as f:
            f.write("Long path content")

        assert is_reparse_point(long_file) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])