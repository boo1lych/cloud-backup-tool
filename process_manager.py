"""Модуль для управления процессами (за封闭тие/запуск).
Использует psutil для работы с процессами Windows.
"""
import subprocess
import psutil
from typing import Optional, Tuple, Dict, Any


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
        print(f"Error searching for process '{process_name}': {e}")
        return None


def close_process(process_name: str, mode: str = 'graceful_then_force',
timeout: int = 10) -> Tuple[bool, Optional[str]]:
    """Закрывает процесс по имени.
    Args:
        process_name: имя процесса (например, "OUTLOOK.EXE")
        mode: режим закрытия:
            - 'graceful': мягкое завершение (terminate)
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
            p.terminate()  # Рекомендуемый psutil способ для graceful shutdown в Windows
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
            p.terminate()
            try:
                p.wait(timeout=timeout)
                return True, exe_path
            except psutil.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
                return True, exe_path
        
        else:
            raise ValueError(f"Unknown close mode: {mode}")
            
    except psutil.NoSuchProcess:
        # Процесс уже завершён — считаем успехом
        return True, exe_path
    except psutil.AccessDenied as e:
        print(f"Access denied when closing process '{process_name}': {e}")
        return False, None
    except Exception as e:
        print(f"Error closing process '{process_name}': {e}")
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
        print(f"Executable not found: {exe_path}")
        return False
    except PermissionError:
        print(f"Permission denied: {exe_path}")
        return False
    except Exception as e:
        print(f"Error starting process '{exe_path}': {e}")
        return False