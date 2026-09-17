"""Тесты для модуля process_manager."""
import os
import sys
import pytest
from unittest.mock import Mock, patch
import psutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from process_manager import (
    close_process,
    start_process,
    find_process_by_name,
)


class TestFindProcessByName:
    def test_finds_running_process(self):
        """Находит процесс по имени (регистронезависимо)."""
        with patch('process_manager.psutil.process_iter') as mock_iter:
            mock_proc = Mock()
            mock_proc.info = {
                'name': 'OUTLOOK.EXE', 
                'exe': 'C:\\Program Files\\Outlook\\OUTLOOK.EXE',
                'pid': 1234
            }
            mock_iter.return_value = [mock_proc]
            
            result = find_process_by_name('outlook.exe')
            
            assert result is not None
            assert result['name'] == 'OUTLOOK.EXE'
            assert result['exe'] == 'C:\\Program Files\\Outlook\\OUTLOOK.EXE'
            assert result['pid'] == 1234

    def test_returns_none_if_not_found(self):
        """Возвращает None, если процесс не найден."""
        with patch('process_manager.psutil.process_iter') as mock_iter:
            mock_iter.return_value = []
            
            result = find_process_by_name('nonexistent.exe')
            
            assert result is None

    def test_case_insensitive_search(self):
        """Поиск регистронезависимый."""
        with patch('process_manager.psutil.process_iter') as mock_iter:
            mock_proc = Mock()
            mock_proc.info = {'name': 'Outlook.exe', 'exe': 'C:\\Outlook.exe', 'pid': 5678}
            mock_iter.return_value = [mock_proc]
            
            result = find_process_by_name('OUTLOOK.EXE')
            
            assert result is not None

    def test_handles_psutil_exceptions(self):
        """Обрабатывает исключения psutil."""
        with patch('process_manager.psutil.process_iter') as mock_iter:
            mock_iter.side_effect = Exception("psutil error")
            
            result = find_process_by_name('test.exe')
            
            assert result is None


class TestCloseProcess:
    def test_graceful_mode_success(self):
        """Graceful закрытие успешно."""
        with patch('process_manager.find_process_by_name') as mock_find, \
             patch('process_manager.psutil.Process') as mock_proc_class:
            
            mock_find.return_value = {'name': 'test.exe', 'exe': 'C:\\test.exe', 'pid': 1234}
            mock_proc = Mock()
            mock_proc_class.return_value = mock_proc
            mock_proc.wait.return_value = None
            
            success, exe_path = close_process('test.exe', mode='graceful', timeout=5)
            
            assert success is True
            assert exe_path == 'C:\\test.exe'
            mock_proc.terminate.assert_called_once()

    def test_graceful_mode_timeout(self):
        """Graceful закрытие с таймаутом."""
        with patch('process_manager.find_process_by_name') as mock_find, \
             patch('process_manager.psutil.Process') as mock_proc_class:
            
            mock_find.return_value = {'name': 'test.exe', 'exe': 'C:\\test.exe', 'pid': 1234}
            mock_proc = Mock()
            mock_proc_class.return_value = mock_proc
            mock_proc.wait.side_effect = psutil.TimeoutExpired(1234, 2)
            
            success, exe_path = close_process('test.exe', mode='graceful', timeout=2)
            
            assert success is False
            assert exe_path is None

    def test_force_mode_success(self):
        """Force закрытие успешно."""
        with patch('process_manager.find_process_by_name') as mock_find, \
             patch('process_manager.psutil.Process') as mock_proc_class:
            
            mock_find.return_value = {'name': 'test.exe', 'exe': 'C:\\test.exe', 'pid': 1234}
            mock_proc = Mock()
            mock_proc_class.return_value = mock_proc
            mock_proc.kill.return_value = None
            mock_proc.wait.return_value = None
            
            success, exe_path = close_process('test.exe', mode='force', timeout=5)
            
            assert success is True
            assert exe_path == 'C:\\test.exe'
            mock_proc.kill.assert_called_once()

    def test_graceful_then_force_mode(self):
        """Graceful then force: сначала graceful, потом force."""
        with patch('process_manager.find_process_by_name') as mock_find, \
             patch('process_manager.psutil.Process') as mock_proc_class:
            
            mock_find.return_value = {'name': 'test.exe', 'exe': 'C:\\test.exe', 'pid': 1234}
            mock_proc = Mock()
            mock_proc_class.return_value = mock_proc
            # Graceful не сработал (таймаут), потом force сработал
            mock_proc.wait.side_effect = [psutil.TimeoutExpired(1234, 2), None]
            
            success, exe_path = close_process('test.exe', mode='graceful_then_force', timeout=2)
            
            assert success is True
            assert exe_path == 'C:\\test.exe'
            mock_proc.terminate.assert_called_once()
            mock_proc.kill.assert_called_once()

    def test_process_not_found(self):
        """Процесс не найден."""
        with patch('process_manager.find_process_by_name') as mock_find:
            mock_find.return_value = None
            
            success, exe_path = close_process('nonexistent.exe', mode='graceful', timeout=5)
            
            assert success is False
            assert exe_path is None

    def test_process_already_terminated(self):
        """Процесс уже завершён."""
        with patch('process_manager.find_process_by_name') as mock_find, \
             patch('process_manager.psutil.Process') as mock_proc_class:
            
            mock_find.return_value = {'name': 'test.exe', 'exe': 'C:\\test.exe', 'pid': 1234}
            mock_proc = Mock()
            mock_proc_class.return_value = mock_proc
            mock_proc.terminate.side_effect = psutil.NoSuchProcess(1234)
            
            success, exe_path = close_process('test.exe', mode='graceful', timeout=5)
            
            # Если процесс уже мёртв — считаем успехом
            assert success is True
            assert exe_path == 'C:\\test.exe'


class TestStartProcess:
    def test_start_process_success(self):
        """Успешный запуск процесса."""
        with patch('process_manager.subprocess.Popen') as mock_popen:
            mock_popen.return_value = Mock()
            
            success = start_process('C:\\Program Files\\Outlook\\OUTLOOK.EXE')
            
            assert success is True
            mock_popen.assert_called_once()

    def test_start_process_file_not_found(self):
        """Файл не найден."""
        with patch('process_manager.subprocess.Popen') as mock_popen:
            mock_popen.side_effect = FileNotFoundError("File not found")
            
            success = start_process('C:\\nonexistent.exe')
            
            assert success is False

    def test_start_process_permission_error(self):
        """Ошибка доступа."""
        with patch('process_manager.subprocess.Popen') as mock_popen:
            mock_popen.side_effect = PermissionError("Permission denied")
            
            success = start_process('C:\\protected.exe')
            
            assert success is False

    def test_start_process_with_args(self):
        """Запуск с аргументами."""
        with patch('process_manager.subprocess.Popen') as mock_popen:
            mock_popen.return_value = Mock()
            
            success = start_process('C:\\test.exe', args=['--arg1', '--arg2'])
            
            assert success is True
            call_args = mock_popen.call_args[0][0]
            assert call_args == ['C:\\test.exe', '--arg1', '--arg2']


class TestIntegration:
    def test_close_and_start_process(self):
        """Интеграционный тест: закрытие и запуск."""
        with patch('process_manager.find_process_by_name') as mock_find, \
             patch('process_manager.psutil.Process') as mock_proc_class, \
             patch('process_manager.subprocess.Popen') as mock_popen:
            
            # Закрытие
            mock_find.return_value = {'name': 'test.exe', 'exe': 'C:\\test.exe', 'pid': 1234}
            mock_proc = Mock()
            mock_proc_class.return_value = mock_proc
            mock_proc.wait.return_value = None
            
            success, exe_path = close_process('test.exe', mode='graceful', timeout=5)
            assert success is True
            assert exe_path == 'C:\\test.exe'
            
            # Запуск
            mock_popen.return_value = Mock()
            success = start_process(exe_path)
            assert success is True