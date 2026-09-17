"""Тесты для модуля error_log."""
import os
import sys
import pytest

# Добавляем корень проекта в sys.path, чтобы импортировать error_log
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from error_log import ErrorLogger


@pytest.fixture
def logger(tmp_path):
    """Создаёт ErrorLogger с временной директорией."""
    return ErrorLogger(log_dir=str(tmp_path))


@pytest.fixture
def logger_with_errors(logger):
    """Логгер с несколькими записанными ошибками."""
    logger.log_error("Profile1", "disk_unavailable", "Disk not found")
    logger.log_error("Profile2", "copy_errors", "Permission denied",
                     attempt=1, max_attempts=3)
    logger.log_error("Profile1", "process_close_failed", "Timeout",
                     attempt=2, max_attempts=3)
    return logger


class TestErrorLoggerInit:
    def test_creates_log_directory(self, tmp_path):
        log_dir = tmp_path / "custom_logs"
        assert not log_dir.exists()
        ErrorLogger(log_dir=str(log_dir))
        assert log_dir.exists()

    def test_creates_log_file_on_first_write(self, logger):
        errors_file = os.path.join(logger.log_dir, "errors.log")
        # RotatingFileHandler создаёт файл при инициализации, а не при первой записи
        # Поэтому проверяем, что файл пустой до первой записи
        if os.path.exists(errors_file):
            assert os.path.getsize(errors_file) == 0
        logger.log_error("Test", "test_type", "test message")
        assert os.path.exists(errors_file)
        assert os.path.getsize(errors_file) > 0

    def test_default_log_dir_used_when_not_specified(self):
        # При вызове без аргумента должен использоваться BASE_DIR/logs
        logger = ErrorLogger()
        assert logger.log_dir.endswith("logs")


class TestLogError:
    def test_log_without_attempt(self, logger):
        logger.log_error("Outlook", "disk_unavailable", "Disk not found")
        errors = logger.get_last_n_errors(10)
        assert len(errors) == 1
        assert "[Outlook]" in errors[0]
        assert "disk_unavailable" in errors[0]
        assert "Disk not found" in errors[0]

    def test_log_with_attempt(self, logger):
        logger.log_error("Outlook", "copy_errors", "Timeout",
                         attempt=2, max_attempts=3)
        errors = logger.get_last_n_errors(10)
        assert len(errors) == 1
        assert "Attempt 2/3" in errors[0]

    def test_multiple_errors(self, logger):
        for i in range(5):
            logger.log_error(f"Profile{i}", "test", f"Error {i}")
        errors = logger.get_last_n_errors(10)
        assert len(errors) == 5

    def test_timestamp_format(self, logger):
        logger.log_error("P", "e", "m")
        errors = logger.get_last_n_errors(1)
        # Формат: [YYYY-MM-DD HH:MM:SS] ...
        assert errors[0].startswith("[")
        assert errors[0][1:5].isdigit()  # год


class TestGetFileSize:
    def test_returns_zero_if_no_file(self, logger):
        assert logger.get_file_size() == 0

    def test_returns_correct_size(self, logger_with_errors):
        size = logger_with_errors.get_file_size()
        assert size > 0

    def test_size_grows_after_write(self, logger):
        size_before = logger.get_file_size()
        logger.log_error("P", "e", "some long message " * 50)
        size_after = logger.get_file_size()
        assert size_after > size_before


class TestGetNewErrors:
    def test_read_all_from_zero(self, logger_with_errors):
        errors, new_pos = logger_with_errors.get_new_errors(0)
        assert len(errors) == 3
        assert new_pos > 0

    def test_read_nothing_if_position_at_end(self, logger_with_errors):
        size = logger_with_errors.get_file_size()
        errors, new_pos = logger_with_errors.get_new_errors(size)
        assert errors == []
        assert new_pos == size

    def test_read_only_new_after_position(self, logger):
        logger.log_error("P1", "e1", "msg1")
        size_after_first = logger.get_file_size()

        logger.log_error("P2", "e2", "msg2")
        errors, new_pos = logger.get_new_errors(size_after_first)

        assert len(errors) == 1
        assert "P2" in errors[0]
        assert new_pos > size_after_first

    def test_handles_file_truncation(self, logger):
        # Записываем несколько ошибок
        logger.log_error("P1", "e1", "msg1")
        logger.log_error("P2", "e2", "msg2")

        # Имитируем ротацию — обрезаем файл (остаётся только последняя строка)
        errors_file = os.path.join(logger.log_dir, "errors.log")
        with open(errors_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        with open(errors_file, "w", encoding="utf-8") as f:
            f.write(lines[-1])

        # Старая позиция больше нового размера — должно сброситься на 0
        errors, new_pos = logger.get_new_errors(10000)
        assert len(errors) >= 1

    def test_empty_lines_filtered(self, logger):
        logger.log_error("P1", "e1", "msg1")
        errors, _ = logger.get_new_errors(0)
        # Все строки должны быть непустыми
        assert all(line.strip() for line in errors)


class TestGetLastNErrors:
    def test_returns_empty_if_no_file(self, logger):
        assert logger.get_last_n_errors(10) == []

    def test_returns_last_n(self, logger):
        for i in range(10):
            logger.log_error(f"P{i}", "e", f"msg{i}")
        errors = logger.get_last_n_errors(3)
        assert len(errors) == 3
        assert "P9" in errors[-1]
        assert "P7" in errors[0]

    def test_returns_all_if_less_than_n(self, logger):
        for i in range(3):
            logger.log_error(f"P{i}", "e", f"msg{i}")
        errors = logger.get_last_n_errors(10)
        assert len(errors) == 3

    def test_default_n_is_50(self, logger):
        for i in range(100):
            logger.log_error(f"P{i}", "e", f"msg{i}")
        errors = logger.get_last_n_errors()  # без аргумента — должно быть 50
        assert len(errors) == 50
        assert "P99" in errors[-1]
        assert "P50" in errors[0]