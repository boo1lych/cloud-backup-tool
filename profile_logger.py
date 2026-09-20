"""Логирование в отдельные файлы для каждого профиля.
Каждый профиль получает свой RotatingFileHandler в logs/profiles/<name>.log.
"""
import os
import logging
import threading
from logging.handlers import RotatingFileHandler
import sys

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_LOG_DIR = os.path.join(BASE_DIR, "logs")
PROFILES_LOG_DIR_NAME = "profiles"


class ProfileLogger:
    """Менеджер логгеров по профилям. Потокобезопасный."""

    def __init__(self, log_dir=None):
        self.log_dir = log_dir if log_dir is not None else DEFAULT_LOG_DIR
        self.profiles_dir = os.path.join(self.log_dir, PROFILES_LOG_DIR_NAME)
        os.makedirs(self.profiles_dir, exist_ok=True)
        self._loggers = {}          # profile_name -> logging.Logger
        self._lock = threading.Lock()

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Заменяет недопустимые для имени файла символы на '_' и ограничивает длину."""
        result = name
        for ch in '<>:"/\\|?*':
            result = result.replace(ch, '_')
        
        # Ограничиваем длину имени файла (Windows лимит 255 символов)
        # Оставляем запас для расширения .log
        max_length = 200
        if len(result) > max_length:
            result = result[:max_length]
        
        return result

    def _get_log_file(self, profile_name: str) -> str:
        safe_name = self.sanitize_filename(profile_name)
        if not safe_name:
            safe_name = "_unnamed_"
        return os.path.join(self.profiles_dir, f"{safe_name}.log")

    def get_logger(self, profile_name: str) -> logging.Logger:
        """Возвращает (или создаёт) логгер для указанного профиля."""
        with self._lock:
            if profile_name in self._loggers:
                return self._loggers[profile_name]

            log_file = self._get_log_file(profile_name)
            unique_name = (
                f"ProfileLogger_{profile_name}_{id(self)}_{len(self._loggers)}"
            )
            logger = logging.getLogger(unique_name)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            logger.handlers.clear()

            handler = RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,   # 5 MB
                backupCount=5,
                encoding="utf-8",
            )
            formatter = logging.Formatter(
                "[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

            self._loggers[profile_name] = logger
            return logger

    def log(self, message: str, profile_name=None):
        """Записывает сообщение.
        Если profile_name задан — в лог этого профиля.
        Если None — во все известные логи профилей.
        """
        if profile_name is not None:
            logger = self.get_logger(profile_name)
            logger.info(message)
            return

        with self._lock:
            names = list(self._loggers.keys())
        for name in names:
            self.get_logger(name).info(message)

    def get_known_profile_names(self):
        """Возвращает список профилей, для которых уже созданы логгеры."""
        with self._lock:
            return list(self._loggers.keys())

    def read_last_lines(self, profile_name: str, n: int = 10000):
        """Читает последние N строк из файла лога профиля."""
        log_file = self._get_log_file(profile_name)
        if not os.path.exists(log_file):
            return []
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return lines[-n:]
        except Exception as e:
            print(f"Error reading profile log '{profile_name}': {e}")
            return []

    def on_profile_renamed(self, old_name: str, new_name: str):
        """Реагирует на переименование профиля.
        Закрывает старый logger. Переименовывает файл лога.
        Если файл с новым именем уже существует, добавляет суффикс.
        """
        old_file = self._get_log_file(old_name)
        new_file = self._get_log_file(new_name)
        
        with self._lock:
            if old_name in self._loggers:
                logger = self._loggers.pop(old_name)
                for h in logger.handlers:
                    try:
                        h.close()
                    except Exception:
                        pass
                logger.handlers.clear()
        
        # Переименовываем файл
        if os.path.exists(old_file):
            # Если новый файл уже существует, добавляем суффикс
            if os.path.exists(new_file):
                base, ext = os.path.splitext(new_file)
                counter = 1
                while os.path.exists(f"{base}_{counter}{ext}"):
                    counter += 1
                new_file = f"{base}_{counter}{ext}"
            
            try:
                os.rename(old_file, new_file)
            except Exception as e:
                print(f"Failed to rename log '{old_file}' -> '{new_file}': {e}")

    def on_profile_deleted(self, profile_name: str):
        """Реагирует на удаление профиля.
        Закрывает logger, но файл лога оставляет как архив.
        """
        with self._lock:
            if profile_name in self._loggers:
                logger = self._loggers.pop(profile_name)
                for h in logger.handlers:
                    try:
                        h.close()
                    except Exception:
                        pass
                logger.handlers.clear()

    def close_all(self):
        """Закрывает все handler'ы (вызывать при выходе)."""
        with self._lock:
            for logger in self._loggers.values():
                for h in logger.handlers:
                    try:
                        h.close()
                    except Exception:
                        pass
            self._loggers.clear()