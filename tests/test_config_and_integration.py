import pytest
import os
import sys
import json
import shutil
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from backup_logic import backup_saves


# ============================================================
#  Особые имена файлов
# ============================================================

class TestBackupSavesSpecialFilenames:
    """Тесты бэкапа файлов с особыми именами."""

    def test_files_with_spaces(self, temp_dirs):
        """Файлы с пробелами в именах корректно копируются."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file with spaces.txt"), "w") as f:
            f.write("Content")
        with open(os.path.join(source, "another file.log"), "w") as f:
            f.write("Log")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 2
        assert os.path.exists(os.path.join(backup, os.path.basename(source), "file with spaces.txt"))

    def test_files_with_unicode_names(self, temp_dirs):
        """Файлы с Unicode именами корректно копируются."""
        source, backup = temp_dirs

        with open(os.path.join(source, "файл.txt"), "w", encoding="utf-8") as f:
            f.write("Русский")
        with open(os.path.join(source, "文件.txt"), "w", encoding="utf-8") as f:
            f.write("Китайский")
        with open(os.path.join(source, "ファイル.txt"), "w", encoding="utf-8") as f:
            f.write("Японский")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 3

    def test_files_with_emoji_names(self, temp_dirs):
        """Файлы с emoji в именах корректно копируются."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file_🔥.txt"), "w", encoding="utf-8") as f:
            f.write("Hot")
        with open(os.path.join(source, "file_🎉.txt"), "w", encoding="utf-8") as f:
            f.write("Party")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 2

    def test_files_with_apostrophes_in_names(self, temp_dirs):
        """Файлы с апострофами в именах корректно копируются."""
        source, backup = temp_dirs

        # Windows не разрешает " в именах файлов, но разрешает '
        with open(os.path.join(source, "file'apostrophe.txt"), "w") as f:
            f.write("Apostrophe")
        with open(os.path.join(source, "file's'quote.txt"), "w") as f:
            f.write("Multiple apostrophes")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 2
    def test_files_with_special_characters(self, temp_dirs):
        """Файлы со спецсимволами в именах корректно копируются."""
        source, backup = temp_dirs

        # Windows не позволяет < > : " / \ | ? * в именах файлов
        # Но можно использовать другие символы
        with open(os.path.join(source, "file@special.txt"), "w") as f:
            f.write("At")
        with open(os.path.join(source, "file#hash.txt"), "w") as f:
            f.write("Hash")
        with open(os.path.join(source, "file$dollar.txt"), "w") as f:
            f.write("Dollar")
        with open(os.path.join(source, "file%percent.txt"), "w") as f:
            f.write("Percent")

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

    def test_files_with_dots_in_names(self, temp_dirs):
        """Файлы с множественными точками в именах корректно копируются."""
        source, backup = temp_dirs

        with open(os.path.join(source, "file.name.with.dots.txt"), "w") as f:
            f.write("Dots")
        with open(os.path.join(source, ".hidden_file"), "w") as f:
            f.write("Hidden")
        with open(os.path.join(source, "file."), "w") as f:
            f.write("Trailing dot")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 3


# ============================================================
#  Бинарные файлы
# ============================================================

class TestBackupSavesBinaryFiles:
    """Тесты бэкапа бинарных файлов."""

    def test_binary_file_integrity(self, temp_dirs):
        """Бинарный файл копируется без изменений."""
        source, backup = temp_dirs

        # Создаём бинарный файл с известным содержимым
        binary_content = bytes(range(256)) * 100  # 25.6 KB
        src_file = os.path.join(source, "binary.bin")
        with open(src_file, "wb") as f:
            f.write(binary_content)

        # Вычисляем хеш источника
        src_hash = hashlib.md5(binary_content).hexdigest()

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

        # Проверяем целостность
        dest_file = os.path.join(backup, os.path.basename(source), "binary.bin")
        with open(dest_file, "rb") as f:
            dest_content = f.read()

        dest_hash = hashlib.md5(dest_content).hexdigest()
        assert src_hash == dest_hash
        assert len(dest_content) == len(binary_content)

    def test_mixed_text_and_binary(self, temp_dirs):
        """Смесь текстовых и бинарных файлов корректно копируется."""
        source, backup = temp_dirs

        with open(os.path.join(source, "text.txt"), "w") as f:
            f.write("Text content")
        with open(os.path.join(source, "binary.bin"), "wb") as f:
            f.write(bytes(range(256)))

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 2


# ============================================================
#  Пустые файлы и директории
# ============================================================

class TestBackupSavesEmptyFiles:
    """Тесты бэкапа пустых файлов."""

    def test_empty_file_is_copied(self, temp_dirs):
        """Пустой файл корректно копируется."""
        source, backup = temp_dirs

        with open(os.path.join(source, "empty.txt"), "w") as f:
            pass  # Пустой файл

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
        dest_file = os.path.join(backup, os.path.basename(source), "empty.txt")
        assert os.path.exists(dest_file)
        assert os.path.getsize(dest_file) == 0

    def test_empty_directories_are_created(self, temp_dirs):
        """Пустые директории создаются в бэкапе (сохраняется структура)."""
        source, backup = temp_dirs

        empty_dir = os.path.join(source, "empty_dir")
        os.makedirs(empty_dir)

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

        assert stats["files_copied"] == 1
        # Пустая директория создаётся (os.makedirs в цикле обхода)
        assert os.path.exists(os.path.join(backup, os.path.basename(source), "empty_dir"))
        assert os.path.isdir(os.path.join(backup, os.path.basename(source), "empty_dir"))

# ============================================================
#  Интеграционные тесты с реальной структурой
# ============================================================

class TestBackupSavesIntegration:
    """Интеграционные тесты с реалистичной структурой."""

    def test_realistic_project_structure(self, temp_dirs):
        """Тест с реалистичной структурой проекта."""
        source, backup = temp_dirs

        # Создаём структуру проекта
        os.makedirs(os.path.join(source, "src"))
        os.makedirs(os.path.join(source, "tests"))
        os.makedirs(os.path.join(source, "docs"))
        os.makedirs(os.path.join(source, ".git"))

        with open(os.path.join(source, "README.md"), "w") as f:
            f.write("# Project")
        with open(os.path.join(source, "src", "main.py"), "w") as f:
            f.write("print('Hello')")
        with open(os.path.join(source, "tests", "test_main.py"), "w") as f:
            f.write("def test(): pass")
        with open(os.path.join(source, "docs", "api.md"), "w") as f:
            f.write("# API")
        with open(os.path.join(source, ".git", "config"), "w") as f:
            f.write("[core]")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str=".git",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 4  # README.md, main.py, test_main.py, api.md
        assert stats["files_skipped"] == 1  # .git/config

    def test_multiple_sources_with_overlapping_names(self, temp_dirs):
        """Тест нескольких источников с перекрывающимися именами файлов."""
        source, backup = temp_dirs

        # Два источника с одинаковыми именами файлов
        source1 = os.path.join(source, "project_a")
        source2 = os.path.join(source, "project_b")
        os.makedirs(source1)
        os.makedirs(source2)

        with open(os.path.join(source1, "config.json"), "w") as f:
            f.write('{"a": 1}')
        with open(os.path.join(source2, "config.json"), "w") as f:
            f.write('{"b": 2}')

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

        # Оба файла должны быть на месте, не перезаписав друг друга
        dest1 = os.path.join(backup, "project_a", "config.json")
        dest2 = os.path.join(backup, "project_b", "config.json")
        assert os.path.exists(dest1)
        assert os.path.exists(dest2)

        with open(dest1) as f:
            assert f.read() == '{"a": 1}'
        with open(dest2) as f:
            assert f.read() == '{"b": 2}'


# ============================================================
#  Тесты производительности (опционально)
# ============================================================

class TestBackupSavesPerformance:
    """Тесты производительности (не для CI, только локально)."""

    @pytest.mark.skip(reason="Медленный тест, только для локальной проверки")
    def test_many_small_files(self, temp_dirs):
        """Тест с большим количеством маленьких файлов."""
        source, backup = temp_dirs

        # Создаём 1000 маленьких файлов
        for i in range(1000):
            with open(os.path.join(source, f"file_{i:04d}.txt"), "w") as f:
                f.write(f"Content {i}")

        state = {"stop_flag": False}

        stats = backup_saves(
            source_dir=source,
            backup_dir=backup,
            skip_links=False,
            exclude_patterns_str="",
            all_sources_in_profile=[source],
            state=state,
        )

        assert stats["files_copied"] == 1000

    @pytest.mark.skip(reason="Медленный тест, только для локальной проверки")
    def test_large_file(self, temp_dirs):
        """Тест с большим файлом (100 MB)."""
        source, backup = temp_dirs

        # Создаём большой файл
        large_content = b"x" * (100 * 1024 * 1024)  # 100 MB
        with open(os.path.join(source, "large.bin"), "wb") as f:
            f.write(large_content)

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
        assert stats["total_size_mb"] > 90


if __name__ == "__main__":
    pytest.main([__file__, "-v"])