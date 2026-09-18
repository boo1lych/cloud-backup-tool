"""Тесты для ProfileLogger — логирование в отдельные файлы профилей."""
import os
import tempfile
import shutil
import pytest
from profile_logger import ProfileLogger


@pytest.fixture
def temp_log_dir():
    """Создаёт временную директорию для логов."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def profile_logger(temp_log_dir):
    """Создаёт ProfileLogger с временной директорией."""
    return ProfileLogger(log_dir=temp_log_dir)


class TestSanitizeFilename:
    """Тесты для sanitize_filename."""

    def test_sanitize_replaces_forbidden_chars(self, profile_logger):
        """Проверяет замену запрещённых символов."""
        result = profile_logger.sanitize_filename('test<>:"/\\|?*name')
        assert result == 'test_________name'

    def test_sanitize_preserves_valid_chars(self, profile_logger):
        """Проверяет, что допустимые символы не меняются."""
        result = profile_logger.sanitize_filename('Valid-Name_123')
        assert result == 'Valid-Name_123'

    def test_sanitize_empty_string(self, profile_logger):
        """Проверяет обработку пустой строки."""
        result = profile_logger.sanitize_filename('')
        assert result == ''


class TestGetLogFile:
    """Тесты для _get_log_file."""

    def test_get_log_file_creates_correct_path(self, profile_logger, temp_log_dir):
        """Проверяет формирование пути к файлу лога."""
        result = profile_logger._get_log_file('TestProfile')
        expected = os.path.join(temp_log_dir, 'profiles', 'TestProfile.log')
        assert result == expected

    def test_get_log_file_sanitizes_name(self, profile_logger, temp_log_dir):
        """Проверяет, что имя файла санитизируется."""
        result = profile_logger._get_log_file('Test<>Profile')
        expected = os.path.join(temp_log_dir, 'profiles', 'Test__Profile.log')
        assert result == expected

    def test_get_log_file_handles_empty_name(self, profile_logger, temp_log_dir):
        """Проверяет обработку пустого имени."""
        result = profile_logger._get_log_file('')
        expected = os.path.join(temp_log_dir, 'profiles', '_unnamed_.log')
        assert result == expected


class TestGetLogger:
    """Тесты для get_logger."""

    def test_get_logger_creates_logger(self, profile_logger):
        """Проверяет создание логгера."""
        logger = profile_logger.get_logger('TestProfile')
        assert logger is not None
        assert logger.level == 20  # logging.INFO

    def test_get_logger_returns_same_instance(self, profile_logger):
        """Проверяет, что повторный вызов возвращает тот же логгер."""
        logger1 = profile_logger.get_logger('TestProfile')
        logger2 = profile_logger.get_logger('TestProfile')
        assert logger1 is logger2

    def test_get_logger_creates_file(self, profile_logger, temp_log_dir):
        """Проверяет, что логгер создаёт файл."""
        logger = profile_logger.get_logger('TestProfile')
        logger.info('Test message')
        for handler in logger.handlers:
            handler.flush()
        
        log_file = os.path.join(temp_log_dir, 'profiles', 'TestProfile.log')
        assert os.path.exists(log_file)


class TestLog:
    """Тесты для log."""

    def test_log_with_profile_name(self, profile_logger, temp_log_dir):
        """Проверяет запись в лог конкретного профиля."""
        profile_logger.log('Test message', profile_name='Profile1')
        
        log_file = os.path.join(temp_log_dir, 'profiles', 'Profile1.log')
        assert os.path.exists(log_file)
        
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'Test message' in content

    def test_log_without_profile_name_writes_to_all(self, profile_logger, temp_log_dir):
        """Проверяет запись во все логи при отсутствии profile_name."""
        # Создаём два логгера
        profile_logger.get_logger('Profile1')
        profile_logger.get_logger('Profile2')
        
        # Логируем без profile_name
        profile_logger.log('System message', profile_name=None)
        
        # Проверяем, что сообщение записано в оба файла
        for profile in ['Profile1', 'Profile2']:
            log_file = os.path.join(temp_log_dir, 'profiles', f'{profile}.log')
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
            assert 'System message' in content

    def test_log_without_profile_name_no_loggers(self, profile_logger):
        """Проверяет, что логирование без profile_name не падает при отсутствии логгеров."""
        # Не должно быть исключений
        profile_logger.log('System message', profile_name=None)


class TestReadLastLines:
    """Тесты для read_last_lines."""

    def test_read_last_lines_returns_correct_count(self, profile_logger, temp_log_dir):
        """Проверяет чтение последних N строк."""
        # Записываем 10 строк
        for i in range(10):
            profile_logger.log(f'Line {i}', profile_name='TestProfile')
        
        lines = profile_logger.read_last_lines('TestProfile', n=5)
        assert len(lines) == 5
        assert 'Line 5' in lines[0]
        assert 'Line 9' in lines[-1]

    def test_read_last_lines_nonexistent_file(self, profile_logger):
        """Проверяет чтение из несуществующего файла."""
        lines = profile_logger.read_last_lines('NonexistentProfile')
        assert lines == []

    def test_read_last_lines_all_lines(self, profile_logger, temp_log_dir):
        """Проверяет чтение всех строк, если их меньше N."""
        for i in range(3):
            profile_logger.log(f'Line {i}', profile_name='TestProfile')
        
        lines = profile_logger.read_last_lines('TestProfile', n=100)
        assert len(lines) == 3


class TestOnProfileRenamed:
    """Тесты для on_profile_renamed."""

    def test_on_profile_renamed_closes_old_logger(self, profile_logger):
        """Проверяет закрытие старого логгера."""
        profile_logger.get_logger('OldName')
        assert 'OldName' in profile_logger.get_known_profile_names()
        
        profile_logger.on_profile_renamed('OldName', 'NewName')
        assert 'OldName' not in profile_logger.get_known_profile_names()

    def test_on_profile_renamed_renames_file(self, profile_logger, temp_log_dir):
        """Проверяет переименование файла лога."""
        # Создаём логгер и записываем сообщение
        logger = profile_logger.get_logger('OldName')
        logger.info('Test message')
        for handler in logger.handlers:
            handler.flush()
        
        old_file = os.path.join(temp_log_dir, 'profiles', 'OldName.log')
        new_file = os.path.join(temp_log_dir, 'profiles', 'NewName.log')
        
        assert os.path.exists(old_file)
        
        profile_logger.on_profile_renamed('OldName', 'NewName')
        
        assert not os.path.exists(old_file)
        assert os.path.exists(new_file)

    def test_on_profile_renamed_no_rename_if_new_exists(self, profile_logger, temp_log_dir):
        """Проверяет, что файл не переименовывается, если новый уже существует."""
        # Создаём оба файла
        logger1 = profile_logger.get_logger('OldName')
        logger1.info('Old message')
        for handler in logger1.handlers:
            handler.flush()
        
        logger2 = profile_logger.get_logger('NewName')
        logger2.info('New message')
        for handler in logger2.handlers:
            handler.flush()
        
        old_file = os.path.join(temp_log_dir, 'profiles', 'OldName.log')
        new_file = os.path.join(temp_log_dir, 'profiles', 'NewName.log')
        
        assert os.path.exists(old_file)
        assert os.path.exists(new_file)
        
        profile_logger.on_profile_renamed('OldName', 'NewName')
        
        # Старый файл должен остаться (не переименован)
        assert os.path.exists(old_file)
        assert os.path.exists(new_file)


class TestOnProfileDeleted:
    """Тесты для on_profile_deleted."""

    def test_on_profile_deleted_closes_logger(self, profile_logger):
        """Проверяет закрытие логгера при удалении профиля."""
        profile_logger.get_logger('TestProfile')
        assert 'TestProfile' in profile_logger.get_known_profile_names()
        
        profile_logger.on_profile_deleted('TestProfile')
        assert 'TestProfile' not in profile_logger.get_known_profile_names()

    def test_on_profile_deleted_keeps_file(self, profile_logger, temp_log_dir):
        """Проверяет, что файл лога остаётся после удаления профиля."""
        logger = profile_logger.get_logger('TestProfile')
        logger.info('Test message')
        for handler in logger.handlers:
            handler.flush()
        
        log_file = os.path.join(temp_log_dir, 'profiles', 'TestProfile.log')
        assert os.path.exists(log_file)
        
        profile_logger.on_profile_deleted('TestProfile')
        
        # Файл должен остаться
        assert os.path.exists(log_file)


class TestCloseAll:
    """Тесты для close_all."""

    def test_close_all_closes_all_loggers(self, profile_logger):
        """Проверяет закрытие всех логгеров."""
        profile_logger.get_logger('Profile1')
        profile_logger.get_logger('Profile2')
        
        assert len(profile_logger.get_known_profile_names()) == 2
        
        profile_logger.close_all()
        
        assert len(profile_logger.get_known_profile_names()) == 0