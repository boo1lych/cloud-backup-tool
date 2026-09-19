"""Интеграционные тесты для метода run_backup."""
import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRunBackupIntegration:
    """Интеграционные тесты для run_backup."""

    @pytest.fixture
    def app(self):
        """Создаёт мок BackupApp с минимальными атрибутами."""
        from CloudBackupTool import BackupApp
        app = Mock(spec=BackupApp)
        app.update_log = Mock()
        app.profile_state = {"TestProfile": {"running": True, "stop_flag": False}}
        app.settings = {
            "profiles": {
                "TestProfile": {
                    "source_dirs": ["C:/source"],
                    "backup_dir": "C:/backup",
                    "skip_links": True,
                    "exclude_patterns": "",
                    "retry": {
                        "enabled": False,
                        "max_attempts": 1,
                        "interval_seconds": 5,
                        "retry_on": [],
                        "on_total_failure": []
                    },
                    "process_control": {
                        "enabled": False,
                        "close_before": [],
                        "close_mode": "graceful_then_force",
                        "graceful_timeout_sec": 10,
                        "on_close_failure": "abort",
                        "restore_after": "only_if_was_running"
                    },
                    "total_timeout_minutes": 0
                }
            }
        }
        # Подключаем реальные методы
        app.run_backup = BackupApp.run_backup.__get__(app, BackupApp)
        app._classify_backup_errors = BackupApp._classify_backup_errors.__get__(app, BackupApp)
        app._restore_processes = BackupApp._restore_processes.__get__(app, BackupApp)
        app._execute_failure_actions = BackupApp._execute_failure_actions.__get__(app, BackupApp)
        app._run_failure_script = BackupApp._run_failure_script.__get__(app, BackupApp)
        app._show_failure_message = Mock()  # Мокаем, чтобы не создавать реальное окно
        app.root = Mock()
        app.root.after = Mock()
        return app

    @patch('CloudBackupTool.os.path.exists', return_value=True)
    @patch('CloudBackupTool.backup_saves')
    def test_successful_backup_no_retry(self, mock_backup, mock_exists, app):
        """Успешный бэкап без retry."""
        mock_backup.return_value = {
            "files_copied": 10,
            "files_skipped": 5,
            "total_size_mb": 1.5,
            "errors": 0,
            "copied_files": ["file1.txt", "file2.txt"]
        }
        
        # 1024**3 = 1 073 741 824 байт (1 ГиБ). Возвращаем 2 ГиБ, чтобы точно пройти проверку MIN_FREE_BYTES.
        app._get_free_space = Mock(return_value=2 * 1024**3)
        app.check_backup_dir_available = Mock(return_value=True)

        app.run_backup("TestProfile")

        # Должен вызвать backup_saves один раз
        assert mock_backup.call_count == 1
        # Должен залогировать успех
        assert any("Total files copied: 10" in str(call) for call in app.update_log.call_args_list)

    @patch('CloudBackupTool.backup_saves')
    def test_retry_on_copy_errors(self, mock_backup, app):
        """Retry при ошибках копирования."""
        # Первая попытка — ошибка, вторая — успех
        mock_backup.side_effect = [
            {"files_copied": 0, "files_skipped": 0, "total_size_mb": 0, "errors": 5, "copied_files": []},
            {"files_copied": 10, "files_skipped": 5, "total_size_mb": 1.5, "errors": 0, "copied_files": []}
        ]
        
        app.settings["profiles"]["TestProfile"]["retry"]["enabled"] = True
        app.settings["profiles"]["TestProfile"]["retry"]["max_attempts"] = 2
        app.settings["profiles"]["TestProfile"]["retry"]["retry_on"] = ["copy_errors"]
        app.settings["profiles"]["TestProfile"]["retry"]["interval_seconds"] = 1
        
        app.run_backup("TestProfile")
        
        # Должен вызвать backup_saves два раза
        assert mock_backup.call_count == 2
        # Должен залогировать retry
        assert any("Waiting" in str(call) and "retry" in str(call) for call in app.update_log.call_args_list)

    @patch('CloudBackupTool.os.path.exists', return_value=True)
    @patch('CloudBackupTool.backup_saves')
    @patch('CloudBackupTool.error_logger.log_error')
    def test_retry_exhausted(self, mock_log_error, mock_backup, mock_exists, app):
        """Все попытки исчерпаны."""
        # Все попытки — ошибка
        mock_backup.return_value = {
            "files_copied": 0, "files_skipped": 0, "total_size_mb": 0, "errors": 5, "copied_files": []
        }
        
        # Исправлено: 2 ГиБ вместо 1000000000 байт
        app._get_free_space = Mock(return_value=2 * 1024**3)
        app.check_backup_dir_available = Mock(return_value=True)

        app.settings["profiles"]["TestProfile"]["retry"]["enabled"] = True
        app.settings["profiles"]["TestProfile"]["retry"]["max_attempts"] = 2
        app.settings["profiles"]["TestProfile"]["retry"]["retry_on"] = ["copy_errors"]
        app.settings["profiles"]["TestProfile"]["retry"]["interval_seconds"] = 1
        app.settings["profiles"]["TestProfile"]["retry"]["on_total_failure"] = [
            {"action": "show_message", "message": "Failed"}
        ]

        app.run_backup("TestProfile")

        # Должен вызвать backup_saves два раза
        assert mock_backup.call_count == 2
        # Должен залогировать ошибку
        assert mock_log_error.call_count >= 1
        # Должен выполнить действия при полном провале
        assert any("Executing failure actions" in str(call) for call in app.update_log.call_args_list)

    @patch('CloudBackupTool.backup_saves')
    def test_stop_flag_during_retry(self, mock_backup, app):
        """Прерывание retry по stop_flag."""
        mock_backup.return_value = {
            "files_copied": 0, "files_skipped": 0, "total_size_mb": 0, "errors": 5, "copied_files": []
        }
        
        app.settings["profiles"]["TestProfile"]["retry"]["enabled"] = True
        app.settings["profiles"]["TestProfile"]["retry"]["max_attempts"] = 3
        app.settings["profiles"]["TestProfile"]["retry"]["retry_on"] = ["copy_errors"]
        app.settings["profiles"]["TestProfile"]["retry"]["interval_seconds"] = 10
        
        # Устанавливаем stop_flag через 1 секунду
        def set_stop_flag():
            time.sleep(1)
            app.profile_state["TestProfile"]["stop_flag"] = True
        
        import threading
        threading.Thread(target=set_stop_flag, daemon=True).start()
        
        app.run_backup("TestProfile")
        
        # Должен прерваться до завершения всех попыток
        assert mock_backup.call_count < 3

    @patch('process_manager.start_process')
    @patch('process_manager.close_process')
    @patch('CloudBackupTool.backup_saves')
    def test_process_control_close_and_restore(self, mock_backup, mock_close, mock_start, app):
        """Закрытие и восстановление процессов."""
        mock_close.return_value = (True, "C:\\Outlook.exe")
        mock_start.return_value = True
        mock_backup.return_value = {
            "files_copied": 10, "files_skipped": 5, "total_size_mb": 1.5, "errors": 0, "copied_files": []
        }
        
        app.settings["profiles"]["TestProfile"]["process_control"]["enabled"] = True
        app.settings["profiles"]["TestProfile"]["process_control"]["close_before"] = ["OUTLOOK.EXE"]
        app.settings["profiles"]["TestProfile"]["process_control"]["restore_after"] = "only_if_was_running"
        
        app.run_backup("TestProfile")
        
        # Должен закрыть процесс
        mock_close.assert_called_once()
        # Должен восстановить процесс
        mock_start.assert_called_once_with("C:\\Outlook.exe")

    @patch('process_manager.close_process')
    @patch('CloudBackupTool.backup_saves')
    def test_process_close_failure_abort(self, mock_backup, mock_close, app):
        """Неудача закрытия процесса — abort."""
        mock_close.return_value = (False, None)
        
        app.settings["profiles"]["TestProfile"]["process_control"]["enabled"] = True
        app.settings["profiles"]["TestProfile"]["process_control"]["close_before"] = ["OUTLOOK.EXE"]
        app.settings["profiles"]["TestProfile"]["process_control"]["on_close_failure"] = "abort"
        
        app.run_backup("TestProfile")
        
        # Не должен вызвать backup_saves
        mock_backup.assert_not_called()
        # Должен залогировать abort
        assert any("Aborting" in str(call) for call in app.update_log.call_args_list)

    @patch('process_manager.close_process')
    @patch('CloudBackupTool.backup_saves')
    def test_process_close_failure_continue(self, mock_backup, mock_close, app):
        """Неудача закрытия процесса — continue."""
        mock_close.return_value = (False, None)
        mock_backup.return_value = {
            "files_copied": 10, "files_skipped": 5, "total_size_mb": 1.5, "errors": 0, "copied_files": []
        }
        
        app.settings["profiles"]["TestProfile"]["process_control"]["enabled"] = True
        app.settings["profiles"]["TestProfile"]["process_control"]["close_before"] = ["OUTLOOK.EXE"]
        app.settings["profiles"]["TestProfile"]["process_control"]["on_close_failure"] = "continue"
        
        app.run_backup("TestProfile")
        
        # Должен вызвать backup_saves несмотря на неудачу закрытия
        mock_backup.assert_called_once()
        # Должен залогировать continue
        assert any("Continuing despite" in str(call) for call in app.update_log.call_args_list)

    @patch('CloudBackupTool.backup_saves')
    def test_total_timeout(self, mock_backup, app):
        """Общий таймаут бэкапа."""
        # Имитируем долгий бэкап (2 секунды на каждый source_dir)
        def slow_backup(*args, **kwargs):
            time.sleep(2)
            return {"files_copied": 0, "files_skipped": 0, "total_size_mb": 0, "errors": 0, "copied_files": []}
        
        mock_backup.side_effect = slow_backup
        
        # Таймаут 0.05 минут = 3 секунды
        # После первого source_dir прошло 2 сек — таймаут не сработал
        # После второго source_dir прошло 4 сек > 3 сек — таймаут сработает
        app.settings["profiles"]["TestProfile"]["total_timeout_minutes"] = 0.05
        app.settings["profiles"]["TestProfile"]["source_dirs"] = ["C:/source1", "C:/source2", "C:/source3"]
        
        app.run_backup("TestProfile")
        
        # Должен прерваться по таймауту
        assert any("Timeout exceeded" in str(call) for call in app.update_log.call_args_list)

    @patch('subprocess.run')
    def test_failure_action_run_script(self, mock_run, app):
        """Действие run_script при полном провале."""
        mock_run.return_value = Mock(stdout="Success", stderr="", returncode=0)
        
        actions = [{"action": "run_script", "script_path": "C:\\test.bat", "log_output": True}]
        app._execute_failure_actions("TestProfile", actions)
        
        mock_run.assert_called_once()
        assert any("Script output" in str(call) for call in app.update_log.call_args_list)

    def test_failure_action_show_message(self, app):
        """Действие show_message при полном провале."""
        actions = [{"action": "show_message", "message": "Failed: {profile_name} at {timestamp}"}]
        app._execute_failure_actions("TestProfile", actions)
        
        # Должен вызвать _show_failure_message
        app._show_failure_message.assert_called_once()
        call_args = app._show_failure_message.call_args[0]
        assert call_args[0] == "TestProfile"
        assert "TestProfile" in call_args[1]