import pytest
import os
import sys
import shutil
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from backup_logic import (
    validate_custom_time,
    validate_hhmm,
    backup_saves,
)


# ============================================================
#  Обработка ошибок копирования
# ============================================================

class TestBackupSavesErrorHandling:
    """Тесты обработки ошибок при копировании файлов."""

    def test_copy_error_increments_errors(self, temp_dirs):
        """Ошибка копирования увеличивает счётчик errors, остальные файлы обрабатываются."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file1.txt"), "w") as f:
            f.write("Content 1")
        with open(os.path.join(source, "file2.txt"), "w") as f:
            f.write("Content 2")

        state = {"stop_flag": False}
        call_count = [0]
        original_copy2 = shutil.copy2

        def failing_copy2(src, dst):
            call_count[0] += 1
            if call_count[0] == 1:
                raise PermissionError("Access denied")
            return original_copy2(src, dst)

        with patch("backup_logic.shutil.copy2", side_effect=failing_copy2):
            stats = backup_saves(
                source_dir=source,
                backup_dir=backup,
                skip_links=False,
                exclude_patterns_str="",
                all_sources_in_profile=[source],
                state=state,
            )

        assert stats["errors"] == 1
        assert stats["files_copied"] == 1

    def test_copy_error_logs_message(self, temp_dirs):
        """Ошибка копирования записывается в лог."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write("Content")

        state = {"stop_flag": False}
        log_messages = []

        with patch(
            "backup_logic.shutil.copy2",
            side_effect=PermissionError("Access denied"),
        ):
            stats = backup_saves(
                source_dir=source,
                backup_dir=backup,
                skip_links=False,
                exclude_patterns_str="",
                all_sources_in_profile=[source],
                state=state,
                log=log_messages.append,
            )

        assert stats["errors"] == 1
        assert any("Error copying" in msg for msg in log_messages)

    def test_all_files_fail(self, temp_dirs):
        """Если все файлы не удалось скопировать — errors == количеству файлов."""
        source, backup = temp_dirs

        for i in range(3):
            with open(os.path.join(source, f"file{i}.txt"), "w") as f:
                f.write(f"Content {i}")

        state = {"stop_flag": False}

        with patch(
            "backup_logic.shutil.copy2",
            side_effect=OSError("Disk full"),
        ):
            stats = backup_saves(
                source_dir=source,
                backup_dir=backup,
                skip_links=False,
                exclude_patterns_str="",
                all_sources_in_profile=[source],
                state=state,
            )

        assert stats["errors"] == 3
        assert stats["files_copied"] == 0
        assert stats["total_size_mb"] == 0


# ============================================================
#  Stop flag в середине бэкапа
# ============================================================

class TestBackupSavesStopFlagMidway:
    """Тесты остановки бэкапа по stop_flag в процессе."""

    def test_stop_flag_stops_mid_backup(self, temp_dirs):
        """stop_flag, установленный после первого файла, останавливает бэкап."""
        source, backup = temp_dirs

        # Все файлы в одной директории — os.walk выдаст их одним батчем
        for i in range(5):
            with open(os.path.join(source, f"file{i}.txt"), "w") as f:
                f.write(f"Content {i}")

        state = {"stop_flag": False}
        copied_so_far = []
        original_copy2 = shutil.copy2

        def copy2_then_stop(src, dst):
            result = original_copy2(src, dst)
            copied_so_far.append(src)
            # После первого скопированного файла — стоп
            state["stop_flag"] = True
            return result

        with patch("backup_logic.shutil.copy2", side_effect=copy2_then_stop):
            stats = backup_saves(
                source_dir=source,
                backup_dir=backup,
                skip_links=False,
                exclude_patterns_str="",
                all_sources_in_profile=[source],
                state=state,
            )

        # Скопирован ровно 1 файл, остальные не успели
        assert stats["files_copied"] == 1
        assert len(copied_so_far) == 1

    def test_stop_flag_before_any_file(self, temp_dirs):
        """Если stop_flag=True до начала — ничего не копируется."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write("Content")

        state = {"stop_flag": True}

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


# ============================================================
#  Нормализация паттернов исключений
# ============================================================

class TestBackupSavesPatternNormalization:
    """Тесты внутренней нормализации паттернов."""

    def test_bare_pattern_gets_wildcards(self, temp_dirs):
        """Паттерн без wildcard оборачивается в *...* и матчит подстроку."""
        source, backup = temp_dirs

        with open(os.path.join(source, "document.txt"), "w") as f:
            f.write("Doc")
        with open(os.path.join(source, "~$document.tmp"), "w") as f:
            f.write("Lock file")
        with open(os.path.join(source, "notes~$backup.txt"), "w") as f:
            f.write("Has ~$ inside")

        state = {"stop_flag": False}

        # "~$" без wildcard → нормализуется в "*~$*"
        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="~$",
            all_sources_in_profile=[source],
            state=state,
        )

        # Оба файла с ~$ в имени пропущены
        assert stats["files_skipped"] == 2
        assert stats["files_copied"] == 1

    def test_wildcard_pattern_unchanged(self, temp_dirs):
        """Паттерн с wildcard используется как есть."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write("Text")
        with open(os.path.join(source, "file.log"), "w") as f:
            f.write("Log")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="*.log",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_skipped"] == 1
        assert stats["files_copied"] == 1

    def test_question_mark_pattern(self, temp_dirs):
        """Паттерн с ? считается wildcard-паттерном и не оборачивается."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file1.txt"), "w") as f:
            f.write("1")
        with open(os.path.join(source, "file2.txt"), "w") as f:
            f.write("2")
        with open(os.path.join(source, "file10.txt"), "w") as f:
            f.write("10")

        state = {"stop_flag": False}

        # "file?.txt" — матчит file1.txt и file2.txt, но НЕ file10.txt
        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="file?.txt",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_skipped"] == 2
        assert stats["files_copied"] == 1

    def test_empty_exclude_patterns(self, temp_dirs):
        """Пустая строка исключений — ничего не пропускается."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write("Content")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_skipped"] == 0
        assert stats["files_copied"] == 1

    def test_multiple_patterns_with_spaces(self, temp_dirs):
        """Паттерны с лишними пробелами корректно парсятся."""
        source, backup = temp_dirs

        with open(os.path.join(source, "a.txt"), "w") as f:
            f.write("a")
        with open(os.path.join(source, "b.log"), "w") as f:
            f.write("b")
        with open(os.path.join(source, "c.tmp"), "w") as f:
            f.write("c")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="  *.log ,  *.tmp  ",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_skipped"] == 2
        assert stats["files_copied"] == 1


# ============================================================
#  Корректность статистики
# ============================================================

class TestBackupSavesStats:
    """Тесты корректности возвращаемой статистики."""

    def test_total_size_mb_calculation(self, temp_dirs):
        """total_size_mb соответствует реальному размеру скопированных файлов."""
        source, backup = temp_dirs

        content = "x" * 1024 * 100  # ~100 KB
        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write(content)

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["total_size_mb"] > 0
        assert 0.05 < stats["total_size_mb"] < 0.2

    def test_copied_files_contains_absolute_source_paths(self, temp_dirs):
        """copied_files содержит абсолютные пути к исходным файлам."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file1.txt"), "w") as f:
            f.write("1")
        with open(os.path.join(source, "file2.txt"), "w") as f:
            f.write("2")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert len(stats["copied_files"]) == 2
        for f in stats["copied_files"]:
            assert os.path.isabs(f)
            assert f.startswith(source)

    def test_unchanged_files_not_counted_in_size(self, temp_dirs):
        """Пропущенные (неизменённые) файлы не добавляются в total_size_mb."""
        source, backup = temp_dirs

        content = "x" * 1024 * 100
        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write(content)

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

        # Второй бэкап — файл не изменился
        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 0
        assert stats["files_skipped"] == 1
        assert stats["total_size_mb"] == 0

    def test_stats_keys_always_present(self, temp_dirs):
        """Возвращаемый словарь всегда содержит все ожидаемые ключи."""
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

        expected_keys = {"files_copied", "files_skipped", "total_size_mb", "errors", "copied_files"}
        assert expected_keys.issubset(stats.keys())


# ============================================================
#  Параметризованные тесты для валидаторов
# ============================================================

@pytest.mark.parametrize("input_val,expected_ok", [
    ("00:00", True),
    ("23:59", True),
    ("12:30", True),
    ("5:30", True),
    ("09:05", True),
    ("  12:30  ", True),
    ("24:00", False),
    ("12:60", False),
    ("abc", False),
    ("", False),
    ("   ", False),
    (":", False),
    ("-1:30", False),
    ("12:-5", False),
    ("12:30:45", False),
    ("12-30", False),
    ("12.30", False),
    ("1230", False),
])
def test_validate_hhmm_parametrized(input_val, expected_ok):
    """Параметризованный тест для validate_hhmm."""
    ok, err = validate_hhmm(input_val)
    assert ok is expected_ok
    if expected_ok:
        assert err.strip() == ""
    else:
        assert len(err.strip()) > 0


@pytest.mark.parametrize("input_val,expected_ok", [
    ("120", True),
    ("60", True),
    ("1", True),
    ("999999", True),
    ("23:59", True),
    ("00:00", True),
    ("  120  ", True),
    ("  23:59  ", True),
    ("0", False),
    ("-1", False),
    ("abc", False),
    ("", False),
    ("24:00", False),
    ("12:60", False),
    ("12:30:45", False),
    ("12-30", False),
    ("12.30", False),
    ("12 :30", False),
    ("12: 30", False),
    ("1 20", False),
])
def test_validate_custom_time_parametrized(input_val, expected_ok):
    """Параметризованный тест для validate_custom_time."""
    ok, err = validate_custom_time(input_val)
    assert ok is expected_ok
    if expected_ok:
        assert err.strip() == ""
    else:
        assert len(err.strip()) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])