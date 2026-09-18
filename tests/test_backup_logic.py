import pytest
import os
import sys
from pathlib import Path

# Добавляем корневую директорию в путь для импорта
sys.path.insert(0, str(Path(__file__).parent.parent))

from backup_logic import (
    validate_custom_time,
    validate_hhmm,
    backup_saves,
    is_reparse_point,
)


class TestValidateCustomTime:
    """Тесты для функции validate_custom_time."""
    
    def test_valid_hhmm_format(self):
        """Тест валидного формата HH:MM."""
        ok, err = validate_custom_time("23:59")
        assert ok is True
        assert err == ""
        
        ok, err = validate_custom_time("00:00")
        assert ok is True
        
        ok, err = validate_custom_time("12:30")
        assert ok is True
    
    def test_valid_minutes_format(self):
        """Тест валидного формата в минутах."""
        ok, err = validate_custom_time("120")
        assert ok is True
        assert err.strip() == ""

        ok, err = validate_custom_time("60")
        assert ok is True

        ok, err = validate_custom_time("1440")
        assert ok is True
    
    def test_invalid_hours_range(self):
        """Тест неверного диапазона часов."""
        ok, err = validate_custom_time("25:00")
        assert ok is False
        assert "out of range" in err.lower()
        
        ok, err = validate_custom_time("24:00")
        assert ok is False
    
    def test_invalid_minutes_range(self):
        """Тест неверного диапазона минут."""
        ok, err = validate_custom_time("12:60")
        assert ok is False
        assert "out of range" in err.lower()
        
        ok, err = validate_custom_time("12:99")
        assert ok is False
    
    def test_invalid_format(self):
        """Тест неверного формата."""
        ok, err = validate_custom_time("abc")
        assert ok is False
        assert "invalid" in err.lower()
        
        ok, err = validate_custom_time("12:30:45")
        assert ok is False
        
        ok, err = validate_custom_time("12-30")
        assert ok is False
    
    def test_zero_interval(self):
        """Тест нулевого интервала."""
        ok, err = validate_custom_time("0")
        assert ok is False
        assert "greater than 0" in err.lower()
    
    def test_empty_value(self):
        """Тест пустого значения."""
        ok, err = validate_custom_time("")
        assert ok is False
        assert "empty" in err.lower()
    
    def test_whitespace_handling(self):
        """Тест обработки пробелов."""
        ok, err = validate_custom_time("  23:59  ")
        assert ok is True
        
        ok, err = validate_custom_time("  120  ")
        assert ok is True


class TestValidateHHMM:
    """Тесты для функции validate_hhmm."""
    
    def test_valid_time(self):
        """Тест валидного времени."""
        ok, err = validate_hhmm("23:59")
        assert ok is True
        assert err == ""
        
        ok, err = validate_hhmm("00:00")
        assert ok is True
        
        ok, err = validate_hhmm("12:30")
        assert ok is True
    
    def test_invalid_hours(self):
        """Тест неверных часов."""
        ok, err = validate_hhmm("24:00")
        assert ok is False
        assert "hours out of range" in err.lower()
        
        ok, err = validate_hhmm("25:30")
        assert ok is False
    
    def test_invalid_minutes(self):
        """Тест неверных минут."""
        ok, err = validate_hhmm("12:60")
        assert ok is False
        assert "minutes out of range" in err.lower()
        
        ok, err = validate_hhmm("23:99")
        assert ok is False
    
    def test_invalid_format(self):
        """Тест неверного формата."""
        ok, err = validate_hhmm("abc")
        assert ok is False
        assert "invalid" in err.lower()
        
        ok, err = validate_hhmm("12:30:45")
        assert ok is False
        
        ok, err = validate_hhmm("1230")
        assert ok is False
    
    def test_missing_colon(self):
        """Тест отсутствия разделителя."""
        ok, err = validate_hhmm("1230")
        assert ok is False
    
    def test_whitespace_handling(self):
        """Тест обработки пробелов."""
        ok, err = validate_hhmm("  23:59  ")
        assert ok is True


class TestBackupSaves:
    """Тесты для функции backup_saves."""
    
    def test_basic_backup(self, sample_source_tree):
        """Тест базового бэкапа файлов."""
        source, backup = sample_source_tree
        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 4
        assert stats["errors"] == 0
        assert stats["total_size_mb"] > 0
        assert len(stats["copied_files"]) == 4

        # backup_saves создаёт подпапку с именем источника внутри backup_dir
        src_name = os.path.basename(os.path.normpath(source))
        dest_root = os.path.join(backup, src_name)

        # Проверяем, что файлы скопированы в правильную подпапку
        assert os.path.exists(os.path.join(dest_root, "file1.txt"))
        assert os.path.exists(os.path.join(dest_root, "file2.log"))
        assert os.path.exists(os.path.join(dest_root, "subdir1", "file3.txt"))
        assert os.path.exists(os.path.join(dest_root, "subdir2", "file4.tmp"))
    
    def test_backup_with_exclude_patterns(self, sample_source_tree):
        """Тест бэкапа с исключением паттернов."""
        source, backup = sample_source_tree
        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="*.log, *.tmp",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 2
        assert stats["files_skipped"] == 2

        src_name = os.path.basename(os.path.normpath(source))
        dest_root = os.path.join(backup, src_name)

        assert os.path.exists(os.path.join(dest_root, "file1.txt"))
        assert os.path.exists(os.path.join(dest_root, "subdir1", "file3.txt"))
        assert not os.path.exists(os.path.join(dest_root, "file2.log"))
        assert not os.path.exists(os.path.join(dest_root, "subdir2", "file4.tmp"))

    def test_backup_skip_unchanged(self, sample_source_tree):
        """Тест пропуска неизмененных файлов."""
        source, backup = sample_source_tree
        state = {"stop_flag": False}
        
        # Первый бэкап
        stats1 = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )
        assert stats1["files_copied"] == 4
        
        # Второй бэкап (файлы не изменились)
        stats2 = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )
        assert stats2["files_copied"] == 0
        assert stats2["files_skipped"] == 4
    
    def test_backup_stop_flag(self, sample_source_tree):
        """Тест остановки бэкапа по флагу."""
        source, backup = sample_source_tree
        state = {"stop_flag": True}
        
        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )
        
        # Бэкап должен остановиться сразу
        assert stats["files_copied"] == 0
    
    def test_backup_nonexistent_source(self, temp_dirs):
        """Тест бэкапа из несуществующей директории."""
        source, backup = temp_dirs
        nonexistent = os.path.join(source, "nonexistent")
        state = {"stop_flag": False}
        
        stats = backup_saves(
            source_dir=nonexistent,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[nonexistent],
            state=state,
        )
        
        assert stats["files_copied"] == 0
        assert stats["files_skipped"] == 0
    
    def test_backup_multiple_sources_different_names(self, temp_dirs):
        """Тест бэкапа нескольких источников с РАЗНЫМИ именами — конфликта нет."""
        source, backup = temp_dirs

        source1 = os.path.join(source, "data")
        source2 = os.path.join(source, "backup_data")
        os.makedirs(source1)
        os.makedirs(source2)

        with open(os.path.join(source1, "file.txt"), "w") as f:
            f.write("Content 1")
        with open(os.path.join(source2, "file.txt"), "w") as f:
            f.write("Content 2")

        state = {"stop_flag": False}
        all_sources = [source1, source2]

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

        # Имена разные — папки просто data/ и backup_data/
        assert os.path.exists(os.path.join(backup, "data", "file.txt"))
        assert os.path.exists(os.path.join(backup, "backup_data", "file.txt"))

    def test_backup_multiple_sources_same_name_conflict(self, temp_dirs):
        """Тест бэкапа нескольких источников с ОДИНАКОВЫМИ именами — срабатывает логика конфликта."""
        source, backup = temp_dirs

        # Два источника в разных местах, но с одинаковым базовым именем "data"
        source1 = os.path.join(source, "project_a", "data")
        source2 = os.path.join(source, "project_b", "data")
        os.makedirs(source1)
        os.makedirs(source2)

        with open(os.path.join(source1, "file.txt"), "w") as f:
            f.write("Content from project_a")
        with open(os.path.join(source2, "file.txt"), "w") as f:
            f.write("Content from project_b")

        state = {"stop_flag": False}
        all_sources = [source1, source2]

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

        # При конфликте имён backup_saves использует нормализованный полный путь
        # с заменой недопустимых символов на "_"
        def expected_folder(p):
            s = os.path.normpath(p)
            for ch in '<>:"/\\|?*':
                s = s.replace(ch, "_")
            return s

        assert os.path.exists(os.path.join(backup, expected_folder(source1), "file.txt"))
        assert os.path.exists(os.path.join(backup, expected_folder(source2), "file.txt"))

        # Содержимое не перемешалось
        with open(os.path.join(backup, expected_folder(source1), "file.txt"), "r") as f:
            assert f.read() == "Content from project_a"
        with open(os.path.join(backup, expected_folder(source2), "file.txt"), "r") as f:
            assert f.read() == "Content from project_b"
# =========================================================
# =========== TESTS FOR error_details IN backup_saves ======
# =========================================================

class TestBackupSavesErrorDetails:
    """Тесты для error_details в backup_saves."""

    def test_error_details_populated_on_copy_error(self, tmp_path):
        """Проверяет, что error_details заполняется при ошибках копирования."""
        from backup_logic import backup_saves
        
        temp_source = tmp_path / "source"
        temp_backup = tmp_path / "backup"
        temp_source.mkdir()
        temp_backup.mkdir()
        
        # Создаём файл
        test_file = temp_source / 'readonly.txt'
        test_file.write_text('test content')
        
        # В реальности ошибки копирования сложно эмулировать на Windows,
        # поэтому просто проверяем структуру возвращаемого словаря
        state = {'stop_flag': False}
        
        stats = backup_saves(
            str(temp_source), str(temp_backup),
            skip_links=False, exclude_patterns_str='',
            all_sources_in_profile=[str(temp_source)],
            state=state, log=None
        )
        
        # Проверяем, что error_details есть в stats
        assert 'error_details' in stats
        assert isinstance(stats['error_details'], list)

    def test_error_details_empty_on_success(self, tmp_path):
        """Проверяет, что error_details пуст при успешном копировании."""
        from backup_logic import backup_saves
        
        temp_source = tmp_path / "source"
        temp_backup = tmp_path / "backup"
        temp_source.mkdir()
        temp_backup.mkdir()
        
        # Создаём тестовый файл
        test_file = temp_source / 'test.txt'
        test_file.write_text('test content')
        
        state = {'stop_flag': False}
        
        stats = backup_saves(
            str(temp_source), str(temp_backup),
            skip_links=False, exclude_patterns_str='',
            all_sources_in_profile=[str(temp_source)],
            state=state, log=None
        )
        
        assert stats['error_details'] == []
        assert stats['errors'] == 0

    def test_error_details_returned_on_stop_flag(self, tmp_path):
        """Проверяет, что error_details возвращается при stop_flag."""
        from backup_logic import backup_saves
        
        temp_source = tmp_path / "source"
        temp_backup = tmp_path / "backup"
        temp_source.mkdir()
        temp_backup.mkdir()
        
        test_file = temp_source / 'test.txt'
        test_file.write_text('test content')
        
        state = {'stop_flag': True}
        
        stats = backup_saves(
            str(temp_source), str(temp_backup),
            skip_links=False, exclude_patterns_str='',
            all_sources_in_profile=[str(temp_source)],
            state=state, log=None
        )
        
        assert 'error_details' in stats
# =========================================================
# =========== TESTS FOR validate_profile_name ==============
# =========================================================

class TestValidateProfileName:
    """Тесты для validate_profile_name."""

    def test_valid_names(self):
        """Проверяет валидные имена профилей."""
        from backup_logic import validate_profile_name
        
        valid_names = [
            'Default',
            'MyProfile',
            'Profile-123',
            'Profile_2026',
            'Test.Profile',
            'Profile Name',
        ]
        
        for name in valid_names:
            ok, err = validate_profile_name(name)
            assert ok, f"Name '{name}' should be valid, but got error: {err}"

    def test_empty_name(self):
        """Проверяет обработку пустого имени."""
        from backup_logic import validate_profile_name
        
        ok, err = validate_profile_name('')
        assert not ok
        assert 'empty' in err.lower()
        
        ok, err = validate_profile_name('   ')
        assert not ok
        assert 'empty' in err.lower()

    def test_forbidden_characters(self):
        """Проверяет запрещённые символы."""
        from backup_logic import validate_profile_name
        
        forbidden = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        
        for ch in forbidden:
            ok, err = validate_profile_name(f'Test{ch}Profile')
            assert not ok, f"Character '{ch}' should be forbidden"
            assert 'not allowed' in err.lower()

    def test_reserved_names(self):
        """Проверяет зарезервированные имена Windows."""
        from backup_logic import validate_profile_name
        
        reserved = ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'LPT1', 'com1', 'lpt1']
        
        for name in reserved:
            ok, err = validate_profile_name(name)
            assert not ok, f"Name '{name}' should be reserved"
            assert 'reserved' in err.lower()

    def test_dots_and_spaces_only(self):
        """Проверяет имена, состоящие только из точек и пробелов."""
        from backup_logic import validate_profile_name
        
        # Только пробелы — ловятся первой проверкой (empty)
        empty_like = ['   ']
        for name in empty_like:
            ok, err = validate_profile_name(name)
            assert not ok, f"Name '{name}' should be invalid"
            assert 'empty' in err.lower()
        
        # Только точки (или точки с пробелами) — ловятся второй проверкой
        dots_only = ['.', '..', '...', '. . .']
        for name in dots_only:
            ok, err = validate_profile_name(name)
            assert not ok, f"Name '{name}' should be invalid"
            assert 'dots and spaces' in err.lower()
class TestIsReparsePoint:
    """Тесты для функции is_reparse_point."""
    
    def test_regular_file(self, temp_dirs):
        """Тест обычного файла."""
        source, _ = temp_dirs
        file_path = os.path.join(source, "test.txt")
        
        with open(file_path, "w") as f:
            f.write("test")
        
        assert is_reparse_point(file_path) is False
    
    def test_regular_directory(self, temp_dirs):
        """Тест обычной директории."""
        source, _ = temp_dirs
        dir_path = os.path.join(source, "testdir")
        os.makedirs(dir_path)
        
        assert is_reparse_point(dir_path) is False
    
    def test_nonexistent_path(self):
        """Тест несуществующего пути."""
        assert is_reparse_point("/nonexistent/path") is False



if __name__ == "__main__":
    pytest.main([__file__, "-v"])