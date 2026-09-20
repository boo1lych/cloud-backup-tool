"""Модуль для управления процессами (закрытие/запуск).
Использует psutil для работы с процессами Windows.
"""
import os
import sys
import logging
import subprocess
import psutil
import ctypes
from typing import Optional, Tuple, Dict, Any
from logging.handlers import RotatingFileHandler

# --- Логгер для process_manager ---
if getattr(sys, 'frozen', False):
    _PM_BASE_DIR = os.path.dirname(sys.executable)
else:
    _PM_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_PM_LOG_DIR = os.path.join(_PM_BASE_DIR, "logs")
os.makedirs(_PM_LOG_DIR, exist_ok=True)

_pm_logger = logging.getLogger("process_manager")
_pm_logger.setLevel(logging.ERROR)
_pm_logger.propagate = False
_pm_logger.handlers.clear()
_pm_handler = RotatingFileHandler(
    os.path.join(_PM_LOG_DIR, "process_manager.log"),
    maxBytes=1 * 1024 * 1024,  # 1 MB
    backupCount=5,
    encoding="utf-8",
)
_pm_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
_pm_logger.addHandler(_pm_handler)

class ProcessNotFoundError(Exception):
    """Исключение, когда процесс не найден."""
    pass

def find_process_by_name(process_name: str) -> Optional[Dict[str, Any]]:
    """Ищет процесс по имени (регистронезависимо).
    
    Args:
        process_name: имя процесса (например, "OUTLOOK.EXE")
    
    Returns:
        Словарь с информацией о процессе {'name': str, 'exe': str, 'pid': int} или None
    """
    try:
        for proc in psutil.process_iter(['name', 'exe', 'pid']):
            try:
                if proc.info['name'] and proc.info['name'].upper() == process_name.upper():
                    return {
                        'name': proc.info['name'],
                        'exe': proc.info['exe'] or '',
                        'pid': proc.info['pid']
                    }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None
    except Exception as e:
        _pm_logger.error(f"Error searching for process '{process_name}': {e}")
        return None

def _send_wm_close(pid: int) -> bool:
    """Отправляет WM_CLOSE окнам процесса (настоящий graceful shutdown для Windows)."""
    try:
        user32 = ctypes.windll.user32
        WM_CLOSE = 0x0010
        
        def enum_windows_callback(hwnd, lparam):
            window_pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value == pid:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return True
        
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        callback = WNDENUMPROC(enum_windows_callback)
        user32.EnumWindows(callback, 0)
        return True
    except Exception as e:
        _pm_logger.error(f"Failed to send WM_CLOSE to PID {pid}: {e}")
        return False

def close_process(process_name: str, mode: str = 'graceful_then_force',
                  timeout: int = 10) -> Tuple[bool, Optional[str]]:
    """Закрывает процесс по имени.
    
    Args:
        process_name: имя процесса (например, "OUTLOOK.EXE")
        mode: режим закрытия:
            - 'graceful': мягкое завершение (WM_CLOSE)
            - 'force': жёсткое завершение (kill)
            - 'graceful_then_force': сначала graceful, потом force
        timeout: таймаут ожидания после graceful (в секундах)
    
    Returns:
        Tuple[bool, Optional[str]]: (успех, путь к exe или None)
    """
    proc_info = find_process_by_name(process_name)
    if not proc_info:
        # Процесс уже не запущен — для нашей цели (закрыть перед бэкапом) это успех.
        # Возвращаем None как exe_path, чтобы не пытаться восстанавливать его позже.
        return True, None
    
    exe_path = proc_info['exe']
    pid = proc_info.get('pid')
    if pid is None:
        return False, None
    
    try:
        p = psutil.Process(pid)
        
        if mode == 'graceful':
            # Настоящий graceful shutdown для Windows — WM_CLOSE
            _send_wm_close(pid)
            try:
                p.wait(timeout=timeout)
                return True, exe_path
            except psutil.TimeoutExpired:
                return False, None
        
        elif mode == 'force':
            p.kill()
            p.wait(timeout=5)
            return True, exe_path
        
        elif mode == 'graceful_then_force':
            # Сначала пробуем WM_CLOSE
            _send_wm_close(pid)
            try:
                p.wait(timeout=timeout)
                return True, exe_path
            except psutil.TimeoutExpired:
                # Если не закрылся — жёсткое завершение
                p.kill()
                p.wait(timeout=5)
                return True, exe_path
        
        else:
            raise ValueError(f"Unknown close mode: {mode}")
    
    except psutil.NoSuchProcess:
        # Процесс уже завершён — считаем успехом
        return True, exe_path
    except psutil.AccessDenied as e:
        _pm_logger.error(f"Access denied when closing process '{process_name}': {e}")
        return False, None
    except Exception as e:
        _pm_logger.error(f"Error closing process '{process_name}': {e}")
        return False, None

def start_process(exe_path: str, args: list = None) -> bool:
    """Запускает процесс по пути к exe.
    
    Args:
        exe_path: полный путь к исполняемому файлу
        args: опциональные аргументы командной строки
    
    Returns:
        bool: True, если запуск успешен
    """
    try:
        cmd = [exe_path]
        if args:
            cmd.extend(args)
        subprocess.Popen(cmd, shell=False)
        return True
    except FileNotFoundError:
        _pm_logger.error(f"Executable not found: {exe_path}")
        return False
    except PermissionError:
        _pm_logger.error(f"Permission denied: {exe_path}")
        return False
    except Exception as e:
        _pm_logger.error(f"Error starting process '{exe_path}': {e}")
        return False