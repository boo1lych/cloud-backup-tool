"""Тесты для модуля error_notifier.py (VK Teams Alerts)."""
import json
import os
import logging
from unittest.mock import patch, MagicMock
from contextlib import contextmanager
from urllib.parse import unquote

import pytest

import error_notifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def mock_requests(return_value=None, side_effect=None):
    """Подменяет модуль requests в sys.modules на время контекста.
    Используется вместо patch('error_notifier.requests.get'), потому что
    requests импортируется лениво внутри _send_to_chats."""
    mock_req = MagicMock()
    if return_value is not None:
        mock_req.get.return_value = return_value
    if side_effect is not None:
        mock_req.get.side_effect = side_effect
    with patch.dict("sys.modules", {"requests": mock_req}):
        yield mock_req


def _write_config(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _make_response(status=200, text="ok"):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def notifier_env(tmp_path, monkeypatch):
    """Подменяет пути конфига/лога и отключает реальный логгер."""
    cfg_path = tmp_path / "error_notifications.json"
    log_path = tmp_path / "logs" / "error_notifications.log"
    (tmp_path / "logs").mkdir(exist_ok=True)

    monkeypatch.setattr(error_notifier, "CONFIG_FILE", str(cfg_path))
    monkeypatch.setattr(error_notifier, "LOG_FILE", str(log_path))

    fake_logger = MagicMock()
    monkeypatch.setattr(error_notifier, "_notifier_logger", fake_logger)

    return {
        "cfg_path": cfg_path,
        "log_path": log_path,
        "logger": fake_logger,
    }


# ---------------------------------------------------------------------------
# load_config / save_config
# ---------------------------------------------------------------------------

class TestLoadSaveConfig:
    def test_load_config_file_not_exists(self, notifier_env):
        cfg = error_notifier.load_config()
        assert cfg == {"enabled": False, "bot_token": "", "chat_ids": []}

    def test_load_config_valid(self, notifier_env):
        data = {"enabled": True, "bot_token": "TOKEN", "chat_ids": ["c1", "c2"]}
        _write_config(notifier_env["cfg_path"], data)
        cfg = error_notifier.load_config()
        assert cfg == data

    def test_load_config_missing_fields_fills_defaults(self, notifier_env):
        _write_config(notifier_env["cfg_path"], {"enabled": True})
        cfg = error_notifier.load_config()
        assert cfg["enabled"] is True
        assert cfg["bot_token"] == ""
        assert cfg["chat_ids"] == []

    def test_load_config_invalid_json(self, notifier_env):
        with open(notifier_env["cfg_path"], "w", encoding="utf-8") as f:
            f.write("{not valid json")
        cfg = error_notifier.load_config()
        assert cfg == {"enabled": False, "bot_token": "", "chat_ids": []}
        notifier_env["logger"].warning.assert_called()

    def test_save_config(self, notifier_env):
        data = {"enabled": True, "bot_token": "T", "chat_ids": ["x"]}
        ok = error_notifier.save_config(data)
        assert ok is True
        with open(notifier_env["cfg_path"], "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_save_config_failure(self, notifier_env, monkeypatch):
        monkeypatch.setattr(
            error_notifier, "CONFIG_FILE",
            "/nonexistent_dir_xyz/sub/config.json"
        )
        ok = error_notifier.save_config({"enabled": False})
        assert ok is False
        notifier_env["logger"].warning.assert_called()


# ---------------------------------------------------------------------------
# _format_details_block
# ---------------------------------------------------------------------------

class TestFormatDetailsBlock:
    def test_empty_details(self):
        assert error_notifier._format_details_block([]) == ""
        assert error_notifier._format_details_block(None) == ""

    def test_few_details(self):
        details = ["file1.txt: err1", "file2.txt: err2"]
        out = error_notifier._format_details_block(details)
        assert "Подробности (2):" in out
        assert "• file1.txt: err1" in out
        assert "• file2.txt: err2" in out
        assert "и ещё" not in out

    def test_exactly_max_details(self):
        details = [f"f{i}" for i in range(error_notifier.MAX_DETAILS_LINES)]
        out = error_notifier._format_details_block(details)
        assert f"Подробности ({error_notifier.MAX_DETAILS_LINES}):" in out
        assert "и ещё" not in out

    def test_more_than_max_details_truncated(self):
        n = error_notifier.MAX_DETAILS_LINES + 5
        details = [f"f{i}" for i in range(n)]
        out = error_notifier._format_details_block(details)
        assert f"Подробности ({n}):" in out
        assert "и ещё 5 файлов" in out
        for i in range(error_notifier.MAX_DETAILS_LINES):
            assert f"f{i}" in out
        for i in range(error_notifier.MAX_DETAILS_LINES, n):
            assert f"f{i}" not in out

    def test_custom_header(self):
        out = error_notifier._format_details_block(["x"], header="🔻 Ошибки")
        assert out.startswith("🔻 Ошибки")


# ---------------------------------------------------------------------------
# _send_to_chats
# ---------------------------------------------------------------------------

class TestSendToChats:
    def test_disabled_in_config(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": False, "bot_token": "T", "chat_ids": ["c1"]})
        result = error_notifier._send_to_chats("hello")
        assert result is False

    def test_empty_token(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "", "chat_ids": ["c1"]})
        result = error_notifier._send_to_chats("hello")
        assert result is False

    def test_empty_chat_ids(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": []})
        result = error_notifier._send_to_chats("hello")
        assert result is False

    def test_success_single_chat(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(return_value=_make_response(200)) as mock_req:
            result = error_notifier._send_to_chats("hello")
        assert result is True
        assert mock_req.get.call_count == 1
        url = mock_req.get.call_args[0][0]
        assert "token=T" in url
        assert "chatId=c1" in url
        assert "text=hello" in url

    def test_success_multiple_chats(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T",
                       "chat_ids": ["c1", "c2", "c3"]})
        with mock_requests(return_value=_make_response(200)) as mock_req:
            result = error_notifier._send_to_chats("hello")
        assert result is True
        assert mock_req.get.call_count == 3

    def test_http_error(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(return_value=_make_response(400, "bad request")):
            result = error_notifier._send_to_chats("hello")
        assert result is False
        notifier_env["logger"].warning.assert_called()

    def test_network_exception(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(side_effect=ConnectionError("no network")):
            result = error_notifier._send_to_chats("hello")
        assert result is False
        notifier_env["logger"].warning.assert_called()

    def test_mixed_results_at_least_one_success(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1", "c2"]})
        responses = [_make_response(500, "err"), _make_response(200)]
        with mock_requests(side_effect=responses):
            result = error_notifier._send_to_chats("hello")
        assert result is True

    def test_message_truncation(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        long_text = "x" * (error_notifier.MAX_MESSAGE_LENGTH + 500)
        with mock_requests(return_value=_make_response(200)) as mock_req:
            error_notifier._send_to_chats(long_text)
        sent_url = mock_req.get.call_args[0][0]
        assert "truncated" in sent_url


# ---------------------------------------------------------------------------
# send_test_message
# ---------------------------------------------------------------------------

class TestSendTestMessage:
    def test_disabled(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": False, "bot_token": "T", "chat_ids": ["c1"]})
        ok, msg = error_notifier.send_test_message()
        assert ok is False
        assert "disabled" in msg.lower()

    def test_empty_token(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "", "chat_ids": ["c1"]})
        ok, msg = error_notifier.send_test_message()
        assert ok is False
        assert "bot_token" in msg

    def test_empty_chat_ids(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": []})
        ok, msg = error_notifier.send_test_message()
        assert ok is False
        assert "chat_ids" in msg

    def test_success(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(return_value=_make_response(200)) as mock_req:
            ok, msg = error_notifier.send_test_message()
        assert ok is True
        assert "successfully" in msg.lower()
        sent_url = mock_req.get.call_args[0][0]
        sent_text = unquote(sent_url)
        assert "Test message from Cloud Backup Tool" in sent_text

    def test_send_failure(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(return_value=_make_response(500, "err")):
            ok, msg = error_notifier.send_test_message()
        assert ok is False
        assert "failed" in msg.lower()


# ---------------------------------------------------------------------------
# send_pre_backup_alert
# ---------------------------------------------------------------------------

class TestSendPreBackupAlert:
    def test_basic_alert(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(return_value=_make_response(200)) as mock_req:
            error_notifier.send_pre_backup_alert(
                profile_name="Outlook",
                error_type="disk_unavailable",
                error_message="Target path is not available: 'Z:\\backup'",
            )
        assert mock_req.get.call_count == 1
        sent_url = mock_req.get.call_args[0][0]
        sent_text = unquote(sent_url)
        assert "disk_unavailable" in sent_text
        assert "Outlook" in sent_text

    def test_with_details(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(return_value=_make_response(200)) as mock_req:
            error_notifier.send_pre_backup_alert(
                profile_name="Outlook",
                error_type="disk_unavailable",
                error_message="msg",
                details=["file1: err1", "file2: err2"],
            )
        sent_url = mock_req.get.call_args[0][0]
        sent_text = unquote(sent_url)
        assert "file1" in sent_text
        assert "file2" in sent_text

    def test_exception_does_not_propagate(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(side_effect=RuntimeError("boom")):
            error_notifier.send_pre_backup_alert("P", "disk_unavailable", "msg")
        notifier_env["logger"].warning.assert_called()


# ---------------------------------------------------------------------------
# send_session_alert
# ---------------------------------------------------------------------------

class TestSendSessionAlert:
    def _base_errors(self):
        return [
            {
                "error_type": "copy_errors",
                "error_message": "3 files failed",
                "attempt": 1,
                "max_attempts": 3,
                "details": ["f1: err", "f2: err"],
            },
            {
                "error_type": "disk_unavailable",
                "error_message": "Target not available",
                "attempt": 2,
                "max_attempts": 3,
                "details": [],
            },
        ]

    def test_empty_errors_no_send(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests() as mock_req:
            error_notifier.send_session_alert("P", [], "total_failure")
        mock_req.get.assert_not_called()

    def test_unknown_outcome_no_send(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests() as mock_req:
            error_notifier.send_session_alert("P", self._base_errors(), "unknown")
        mock_req.get.assert_not_called()

    def test_total_failure_format(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(return_value=_make_response(200)) as mock_req:
            error_notifier.send_session_alert(
                "Outlook", self._base_errors(), "total_failure"
            )
        sent_url = mock_req.get.call_args[0][0]
        sent_text = unquote(sent_url)
        assert "disk_unavailable" in sent_text
        assert "Outlook" in sent_text
        assert "2/3" in sent_text
        assert "f1" in sent_text
        assert "f2" in sent_text

    def test_success_after_retry_format(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(return_value=_make_response(200)) as mock_req:
            error_notifier.send_session_alert(
                "Outlook", self._base_errors(), "success_after_retry",
                successful_attempt=3,
            )
        sent_url = mock_req.get.call_args[0][0]
        sent_text = unquote(sent_url)
        assert "успешно" in sent_text
        assert "Outlook" in sent_text
        assert "3/3" in sent_text
        assert "1/3" in sent_text
        assert "2/3" in sent_text

    def test_timeout_format(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(return_value=_make_response(200)) as mock_req:
            error_notifier.send_session_alert(
                "Outlook", self._base_errors(), "timeout",
                total_timeout_minutes=60,
                elapsed_minutes=62.5,
            )
        sent_url = mock_req.get.call_args[0][0]
        sent_text = unquote(sent_url)
        assert "Таймаут" in sent_text
        assert "60" in sent_text
        assert "62.5" in sent_text
        assert "Outlook" in sent_text

    def test_exception_does_not_propagate(self, notifier_env):
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(side_effect=RuntimeError("boom")):
            error_notifier.send_session_alert(
                "Outlook", self._base_errors(), "total_failure"
            )
        notifier_env["logger"].warning.assert_called()

    def test_total_failure_aggregates_all_details(self, notifier_env):
        """Проверяет, что в total_failure собираются details из всех ошибок сеанса."""
        errors = [
            {
                "error_type": "copy_errors",
                "error_message": "m1",
                "attempt": 1, "max_attempts": 3,
                "details": ["a", "b"],
            },
            {
                "error_type": "copy_errors",
                "error_message": "m2",
                "attempt": 2, "max_attempts": 3,
                "details": ["c"],
            },
        ]
        _write_config(notifier_env["cfg_path"],
                      {"enabled": True, "bot_token": "T", "chat_ids": ["c1"]})
        with mock_requests(return_value=_make_response(200)) as mock_req:
            error_notifier.send_session_alert("P", errors, "total_failure")
        sent_url = mock_req.get.call_args[0][0]
        sent_text = unquote(sent_url)
        assert "a" in sent_text
        assert "b" in sent_text
        assert "c" in sent_text