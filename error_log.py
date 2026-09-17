"""Модуль для работы с логом ошибок (errors.log).
Отвечает за запись ошибок, чтение новых записей и управление позицией прочтения.
"""
import os
import logging
from logging.handlers import RotatingFileHandler
import sys

# Базовая директория: для .exe — рядом с exe, для скрипта — рядом с .py
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_LOG_DIR = os.path.join(BASE_DIR, "logs")


class ErrorLogger:
    """Логгер для записи ошибок в errors.log с ротацией."""
    
    _instance_counter = 0  # Счётчик для уникальных имён логгеров

    def __init__(self, log_dir=None):
        """Инициализация логгера.

        Args:
            log_dir: директория для логов. Если None — используется BASE_DIR/logs.
        """
        self.log_dir = log_dir if log_dir is not None else DEFAULT_LOG_DIR
        os.makedirs(self.log_dir, exist_ok=True)

        self.errors_log_file = os.path.join(self.log_dir, "errors.log")

        # Уникальное имя для каждого экземпляра, чтобы избежать переиспользования логгеров
        ErrorLogger._instance_counter += 1
        unique_name = f"ErrorLogger_{ErrorLogger._instance_counter}_{id(self)}"
        
        self.logger = logging.getLogger(unique_name)
        self.logger.setLevel(logging.ERROR)
        self.logger.propagate = False
        # Очищаем старые handlers на случай переиспользования имени
        self.logger.handlers.clear()
        
        rotating_handler = RotatingFileHandler(
            self.errors_log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=5,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        rotating_handler.setFormatter(formatter)
        self.logger.addHandler(rotating_handler)

    def log_error(self, profile_name, error_type, error_message,
                  attempt=None, max_attempts=None):
        """Записывает ошибку в errors.log.

        Args:
            profile_name: имя профиля
            error_type: тип ошибки (disk_unavailable, process_close_failed, etc.)
            error_message: детальное сообщение
            attempt: номер текущей попытки (опционально)
            max_attempts: максимальное количество попыток (опционально)
        """
        if attempt is not None and max_attempts is not None:
            msg = (f"[{profile_name}] Attempt {attempt}/{max_attempts} failed: "
                   f"{error_type}. {error_message}")
        else:
            msg = f"[{profile_name}] {error_type}: {error_message}"
        self.logger.error(msg)
        # Принудительно сбрасываем буфер, чтобы данные сразу попали в файл
        for handler in self.logger.handlers:
            handler.flush()

    def get_file_size(self):
        """Возвращает текущий размер файла errors.log в байтах."""
        try:
            if os.path.exists(self.errors_log_file):
                return os.path.getsize(self.errors_log_file)
            return 0
        except Exception:
            return 0

    def get_new_errors(self, last_read_pos):
        """Читает новые записи из errors.log с позиции last_read_pos.

        Args:
            last_read_pos: байтовая позиция, с которой начинать чтение

        Returns:
            tuple: (новые строки, текущий размер файла)
        """
        try:
            if not os.path.exists(self.errors_log_file):
                return [], 0

            current_size = os.path.getsize(self.errors_log_file)

            # Если файл стал меньше (ротация), читаем с начала
            if current_size < last_read_pos:
                last_read_pos = 0

            if current_size == last_read_pos:
                return [], current_size

            with open(self.errors_log_file, "r", encoding="utf-8") as f:
                f.seek(last_read_pos)
                new_lines = f.read().splitlines()

            # Фильтруем пустые строки
            new_lines = [line for line in new_lines if line.strip()]

            return new_lines, current_size
        except Exception as e:
            print(f"Error reading errors.log: {e}")
            return [], last_read_pos

    def get_last_n_errors(self, n=50):
        """Возвращает последние N записей из errors.log.

        Args:
            n: количество записей

        Returns:
            list: последние N строк
        """
        try:
            if not os.path.exists(self.errors_log_file):
                return []

            with open(self.errors_log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Убираем пустые строки
            lines = [line.strip() for line in lines if line.strip()]

            return lines[-n:]
        except Exception as e:
            print(f"Error reading last errors: {e}")
            return []


# Глобальный экземпляр логгера (используется приложением)
error_logger = ErrorLogger()