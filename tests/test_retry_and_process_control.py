"""Тесты для логики retry, process_control и timeout."""
import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestClassifyBackupErrors:
    """Тесты для метода _classify_backup_errors."""

    @pytest.fixture
    def app(self):
        """Создаёт мок BackupApp с минимальными атрибутами."""
        from CloudBackupTool import BackupApp
        app = Mock(spec=BackupApp)
        # Подключаем реальный метод
        app._classify_backup_errors = BackupApp._classify_backup_errors.__get__(app, BackupApp)
        return app

    def test_no_errors(self, app):
        """Нет ошибок — пустой список."""
        total_stats = {"errors": 0}
        result = app._classify_backup_errors(total_stats, False, False)
        assert result == []

    def test_copy_errors(self, app):
        """Ошибки копирования."""
        total_stats = {"errors": 5}
        result = app._classify_backup_errors(total_stats, False, False)
        assert "copy_errors" in result

    def test_timeout_exceeded(self, app):
        """Таймаут превышен."""
        total_stats = {"errors": 0}
        result = app._classify_backup_errors(total_stats, True, False)
        assert "timeout_exceeded" in result

    def test_both_errors(self, app):
        """И таймаут, и ошибки копирования."""
        total_stats = {"errors": 3}
        result = app._classify_backup_errors(total_stats, True, False)
        assert "timeout_exceeded" in result
        assert "copy_errors" in result


class TestRestoreProcesses:
    """Тесты для метода _restore_processes."""

    @pytest.fixture
    def app(self):
        """Создаёт мок BackupApp."""
        from CloudBackupTool import BackupApp
        app = Mock(spec=BackupApp)
        app.update_log = Mock()
        app._restore_processes = BackupApp._restore_processes.__get__(app, BackupApp)
        return app

    def test_restore_never(self, app):
        """restore_after=never — не восстанавливает."""
        closed = {"OUTLOOK.EXE": "C:\\Outlook.exe"}
        app._restore_processes("Test", closed, "never")
        app.update_log.assert_not_called()

    def test_restore_empty_dict(self, app):
        """Пустой словарь — не восстанавливает."""
        app._restore_processes("Test", {}, "always")
        app.update_log.assert_not_called()

    @patch('process_manager.start_process')
    def test_restore_only_if_was_running(self, mock_start, app):
        """restore_after=only_if_was_running — восстанавливает закрытые."""
        mock_start.return_value = True
        closed = {"OUTLOOK.EXE": "C:\\Outlook.exe"}
        app._restore_processes("Test", closed, "only_if_was_running")
        mock_start.assert_called_once_with("C:\\Outlook.exe")
        assert "Restored: OUTLOOK.EXE" in app.update_log.call_args[0][0]

    @patch('process_manager.start_process')
    def test_restore_always(self, mock_start, app):
        """restore_after=always — восстанавливает."""
        mock_start.return_value = True
        closed = {"OUTLOOK.EXE": "C:\\Outlook.exe"}
        app._restore_processes("Test", closed, "always")
        mock_start.assert_called_once()

    @patch('process_manager.start_process')
    def test_restore_failure(self, mock_start, app):
        """Ошибка восстановления — логируется."""
        mock_start.return_value = False
        closed = {"OUTLOOK.EXE": "C:\\Outlook.exe"}
        app._restore_processes("Test", closed, "always")
        assert "Failed to restore: OUTLOOK.EXE" in app.update_log.call_args[0][0]


class TestExecuteFailureActions:
    """Тесты для метода _execute_failure_actions."""

    @pytest.fixture
    def app(self):
        """Создаёт мок BackupApp."""
        from CloudBackupTool import BackupApp
        app = Mock(spec=BackupApp)
        app.update_log = Mock()
        app._execute_failure_actions = BackupApp._execute_failure_actions.__get__(app, BackupApp)
        app._run_failure_script = Mock()
        app._show_failure_message = Mock()
        return app

    def test_empty_actions(self, app):
        """Пустой список действий — ничего не делает."""
        app._execute_failure_actions("Test", [])
        app._run_failure_script.assert_not_called()
        app._show_failure_message.assert_not_called()

    def test_run_script_action(self, app):
        """Действие run_script."""
        actions = [{"action": "run_script", "script_path": "C:\\test.bat", "log_output": True}]
        app._execute_failure_actions("Test", actions)
        app._run_failure_script.assert_called_once_with("Test", "C:\\test.bat", True)

    def test_show_message_action(self, app):
        """Действие show_message с подстановкой переменных."""
        actions = [{"action": "show_message", "message": "Failed: {profile_name} at {timestamp}"}]
        app._execute_failure_actions("Outlook", actions)
        app._show_failure_message.assert_called_once()
        call_args = app._show_failure_message.call_args[0]
        assert call_args[0] == "Outlook"
        assert "Outlook" in call_args[1]
        assert datetime.now().strftime("%Y") in call_args[1]  # Год в timestamp

    def test_multiple_actions(self, app):
        """Несколько действий."""
        actions = [
            {"action": "run_script", "script_path": "C:\\test.bat", "log_output": True},
            {"action": "show_message", "message": "Failed"}
        ]
        app._execute_failure_actions("Test", actions)
        app._run_failure_script.assert_called_once()
        app._show_failure_message.assert_called_once()


class TestRunFailureScript:
    """Тесты для метода _run_failure_script."""

    @pytest.fixture
    def app(self):
        """Создаёт мок BackupApp."""
        from CloudBackupTool import BackupApp
        app = Mock(spec=BackupApp)
        app.update_log = Mock()
        app._run_failure_script = BackupApp._run_failure_script.__get__(app, BackupApp)
        return app

    @patch('subprocess.run')
    def test_script_success(self, mock_run, app):
        """Скрипт выполнен успешно."""
        mock_run.return_value = Mock(stdout="Output", stderr="", returncode=0)
        app._run_failure_script("Test", "C:\\test.bat", True)
        mock_run.assert_called_once()
        assert "Script output" in app.update_log.call_args[0][0]

    @patch('subprocess.run')
    def test_script_with_stderr(self, mock_run, app):
        """Скрипт с ошибками в stderr."""
        mock_run.return_value = Mock(stdout="", stderr="Error", returncode=1)
        app._run_failure_script("Test", "C:\\test.bat", True)
        assert "Script errors" in app.update_log.call_args[0][0]

    @patch('subprocess.run')
    def test_script_no_log(self, mock_run, app):
        """log_output=False — не логирует."""
        mock_run.return_value = Mock(stdout="Output", stderr="", returncode=0)
        app._run_failure_script("Test", "C:\\test.bat", False)
        app.update_log.assert_not_called()

    @patch('subprocess.run')
    def test_script_exception(self, mock_run, app):
        """Исключение при запуске скрипта."""
        mock_run.side_effect = Exception("Script failed")
        app._run_failure_script("Test", "C:\\test.bat", True)
        assert "Failed to run script" in app.update_log.call_args[0][0]