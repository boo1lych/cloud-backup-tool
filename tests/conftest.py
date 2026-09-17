import pytest
import os
import tempfile
import shutil


@pytest.fixture
def temp_dirs():
    """Создает временные директории для тестирования бэкапа."""
    source = tempfile.mkdtemp(prefix="test_source_")
    backup = tempfile.mkdtemp(prefix="test_backup_")
    
    yield source, backup
    
    # Очистка после теста
    shutil.rmtree(source, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)


@pytest.fixture
def sample_source_tree(temp_dirs):
    """Создает тестовую структуру файлов в source директории."""
    source, backup = temp_dirs
    
    # Создаем файлы
    os.makedirs(os.path.join(source, "subdir1"), exist_ok=True)
    os.makedirs(os.path.join(source, "subdir2"), exist_ok=True)
    
    with open(os.path.join(source, "file1.txt"), "w", encoding="utf-8") as f:
        f.write("Content 1")
    
    with open(os.path.join(source, "file2.log"), "w", encoding="utf-8") as f:
        f.write("Log content")
    
    with open(os.path.join(source, "subdir1", "file3.txt"), "w", encoding="utf-8") as f:
        f.write("Content 3")
    
    with open(os.path.join(source, "subdir2", "file4.tmp"), "w", encoding="utf-8") as f:
        f.write("Temp file")
    
    return source, backup