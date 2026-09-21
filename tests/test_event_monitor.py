"""Тесты для EventMonitor — логика буферизации и debounce событий."""
import time
import threading
import pytest
from unittest.mock import MagicMock, Mock
from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileDeletedEvent, DirCreatedEvent
from event_monitor import EventMonitor


class MockEvent:
    """Мок события watchdog."""
    def __init__(self, event_type, src_path, is_directory=False, dest_path=None):
        self.event_type = event_type
        self.src_path = src_path
        self.is_directory = is_directory
        if dest_path:
            self.dest_path = dest_path


def _make_monitor(callback=None, log_callback=None):
    cb = callback or Mock()
    log_cb = log_callback or Mock()
    monitor = EventMonitor("TestProfile", cb, log_cb)
    # Не запускаем observer и потоки — тестируем только логику
    monitor.source_dirs = ["/src"]
    monitor.event_filters = ["created", "modified", "deleted", "moved"]
    monitor._running = True
    return monitor


def _cancel_timer(monitor):
    """Отменяет таймер debounce, чтобы не блокировать pytest."""
    if monitor._debounce_timer:
        monitor._debounce_timer.cancel()


class TestEventFiltering:
    def test_event_not_in_filters_ignored(self):
        monitor = _make_monitor()
        monitor.event_filters = ["created"]  # только created
        monitor._on_fs_event(MockEvent("modified", "/src/file.txt"))
        # Таймер не создаётся, т.к. событие отфильтровано
        assert len(monitor._event_buffer) == 0

    def test_event_in_filters_added(self):
        monitor = _make_monitor()
        monitor.event_filters = ["created", "modified"]
        monitor._on_fs_event(MockEvent("created", "/src/file.txt"))
        monitor._on_fs_event(MockEvent("modified", "/src/file2.txt"))
        _cancel_timer(monitor)
        assert "/src/file.txt" in monitor._event_buffer
        assert "/src/file2.txt" in monitor._event_buffer


class TestDeduplication:
    def test_created_then_modified_keeps_created(self):
        monitor = _make_monitor()
        monitor._on_fs_event(MockEvent("created", "/src/file.txt"))
        monitor._on_fs_event(MockEvent("modified", "/src/file.txt"))
        _cancel_timer(monitor)
        assert monitor._event_buffer["/src/file.txt"] == "created"

    def test_modified_then_modified_keeps_modified(self):
        monitor = _make_monitor()
        monitor._on_fs_event(MockEvent("modified", "/src/file.txt"))
        monitor._on_fs_event(MockEvent("modified", "/src/file.txt"))
        _cancel_timer(monitor)
        assert monitor._event_buffer["/src/file.txt"] == "modified"

    def test_created_then_deleted_marks_deleted(self):
        monitor = _make_monitor()
        monitor._on_fs_event(MockEvent("created", "/src/file.txt"))
        monitor._on_fs_event(MockEvent("deleted", "/src/file.txt"))
        _cancel_timer(monitor)
        assert monitor._event_buffer["/src/file.txt"] == "deleted"

    def test_modified_then_deleted_marks_deleted(self):
        monitor = _make_monitor()
        monitor._on_fs_event(MockEvent("modified", "/src/file.txt"))
        monitor._on_fs_event(MockEvent("deleted", "/src/file.txt"))
        _cancel_timer(monitor)
        assert monitor._event_buffer["/src/file.txt"] == "deleted"


class TestMovedHandling:
    def test_moved_removes_src_adds_dest_as_created(self):
        monitor = _make_monitor()
        # Сначала файл был создан
        monitor._on_fs_event(MockEvent("created", "/src/old.txt"))
        # Потом переименован
        monitor._on_fs_event(MockEvent("moved", "/src/old.txt", dest_path="/src/new.txt"))
        _cancel_timer(monitor)
        assert "/src/old.txt" not in monitor._event_buffer
        assert monitor._event_buffer["/src/new.txt"] == "created"
        assert len(monitor._moved_buffer) == 1
        assert monitor._moved_buffer[0] == ("/src/old.txt", "/src/new.txt")


class TestDirEventsSeparate:
    def test_file_and_dir_events_separate(self):
        monitor = _make_monitor()
        monitor._on_fs_event(MockEvent("created", "/src/file.txt", is_directory=False))
        monitor._on_fs_event(MockEvent("created", "/src/newdir", is_directory=True))
        _cancel_timer(monitor)
        assert "/src/file.txt" in monitor._event_buffer
        assert "/src/newdir" not in monitor._event_buffer
        assert "/src/newdir" in monitor._dir_event_buffer

    def test_dir_moved_separate_buffer(self):
        monitor = _make_monitor()
        monitor._on_fs_event(MockEvent("moved", "/src/old", is_directory=True, dest_path="/src/new"))
        _cancel_timer(monitor)
        assert len(monitor._dir_moved_buffer) == 1
        assert len(monitor._moved_buffer) == 0


class TestCollectEvents:
    def test_collect_clears_buffer(self, tmp_path):
        monitor = _make_monitor()
        # Создаём реальный файл, чтобы os.path.exists вернул True
        f = tmp_path / "file.txt"
        f.write_text("data")
        monitor._on_fs_event(MockEvent("created", str(f)))
        _cancel_timer(monitor)
        events = monitor._collect_events()
        assert len(events["changed"]) == 1
        assert len(monitor._event_buffer) == 0

    def test_collect_filters_nonexistent(self, tmp_path):
        monitor = _make_monitor()
        # Файл не существует — не должен попасть в changed
        monitor._on_fs_event(MockEvent("created", str(tmp_path / "missing.txt")))
        _cancel_timer(monitor)
        events = monitor._collect_events()
        assert len(events["changed"]) == 0

    def test_collect_deleted_always_included(self, tmp_path):
        monitor = _make_monitor()
        # deleted всегда включается, даже если файл не существует
        monitor._on_fs_event(MockEvent("deleted", str(tmp_path / "missing.txt")))
        _cancel_timer(monitor)
        events = monitor._collect_events()
        assert len(events["deleted"]) == 1


class TestPendingBackup:
    def test_pending_set_when_backup_running(self):
        monitor = _make_monitor()
        monitor.backup_running = True
        monitor._trigger_backup_with_events({"changed": ["/src/f.txt"]})
        assert monitor.pending_backup is True
        # Callback не должен вызываться
        monitor.callback.assert_not_called()

    def test_callback_called_when_not_running(self):
        monitor = _make_monitor()
        monitor.backup_running = False
        monitor._trigger_backup_with_events({"changed": ["/src/f.txt"]})
        assert monitor.backup_running is True
        monitor.callback.assert_called_once()

    def test_on_backup_complete_no_events_no_callback(self, tmp_path):
        """Если нет реальных событий, callback не вызывается."""
        monitor = _make_monitor()
        monitor.backup_running = True
        monitor.pending_backup = True
        # Добавляем событие для несуществующего файла
        monitor._event_buffer["/src/missing.txt"] = "modified"
        monitor.on_backup_complete()
        # Файл не существует, поэтому changed пустой, callback не вызывается
        assert monitor.backup_running is False
        assert monitor.pending_backup is False
        monitor.callback.assert_not_called()

    def test_on_backup_complete_with_events_calls_callback(self, tmp_path):
        """Если есть реальные события, callback вызывается."""
        callback = Mock()
        monitor = _make_monitor(callback=callback)
        monitor.backup_running = True
        monitor.pending_backup = True
        # Создаём реальный файл
        f = tmp_path / "file.txt"
        f.write_text("data")
        monitor._event_buffer[str(f)] = "modified"
        monitor.on_backup_complete()
        # Файл существует, поэтому callback должен вызваться
        assert monitor.backup_running is True  # backup_running устанавливается в True
        assert monitor.pending_backup is False
        callback.assert_called_once()


class TestDebounce:
    def test_fire_backup_calls_callback_with_events(self, tmp_path):
        """Проверяем, что _fire_backup вызывает callback с событиями."""
        callback = Mock()
        monitor = _make_monitor(callback=callback)
        f = tmp_path / "file.txt"
        f.write_text("data")
        # Добавляем событие напрямую в буфер (без создания таймера)
        monitor._event_buffer[str(f)] = "created"
        # Вызываем _fire_backup напрямую
        monitor._fire_backup()
        # Callback должен быть вызван
        callback.assert_called_once()
        args = callback.call_args
        assert args[0][0] == "TestProfile"
        events = args[0][1]
        assert "changed" in events
        assert str(f) in events["changed"]

    def test_fire_backup_empty_events_no_callback(self):
        """Проверяем, что при пустых событиях callback не вызывается."""
        callback = Mock()
        monitor = _make_monitor(callback=callback)
        # Буфер пустой
        monitor._fire_backup()
        # Callback не должен вызываться
        callback.assert_not_called()

    def test_fire_backup_with_multiple_events(self, tmp_path):
        """Проверяем обработку нескольких событий."""
        callback = Mock()
        monitor = _make_monitor(callback=callback)
        f1 = tmp_path / "file1.txt"
        f1.write_text("data1")
        f2 = tmp_path / "file2.txt"
        f2.write_text("data2")
        # Добавляем несколько событий
        monitor._event_buffer[str(f1)] = "created"
        monitor._event_buffer[str(f2)] = "modified"
        monitor._fire_backup()
        callback.assert_called_once()
        events = callback.call_args[0][1]
        assert len(events["changed"]) == 2


class TestOverflowHandling:
    def test_overflow_run_immediately(self):
        callback = Mock()
        monitor = _make_monitor(callback=callback)
        monitor.on_overflow = "run_immediately"
        monitor._handle_overflow()
        callback.assert_called_once()
        args = callback.call_args
        assert args[0][0] == "TestProfile"
        assert args[0][1] is None  # events=None для полного бэкапа
        assert args[1].get("overflow") is True

    def test_overflow_log_warning(self):
        callback = Mock()
        monitor = _make_monitor(callback=callback)
        monitor.on_overflow = "log_warning"
        monitor._handle_overflow()
        callback.assert_not_called()
        monitor.log_callback.assert_called()

    def test_overflow_run_by_schedule(self):
        callback = Mock()
        monitor = _make_monitor(callback=callback)
        monitor.on_overflow = "run_by_schedule"
        monitor._handle_overflow()
        callback.assert_called_once()
        args = callback.call_args
        assert args[1].get("overflow") is True


class TestLogCallback:
    def test_log_callback_called_on_event(self):
        log_cb = Mock()
        monitor = _make_monitor(log_callback=log_cb)
        monitor._on_fs_event(MockEvent("created", "/src/file.txt"))
        _cancel_timer(monitor)
        assert log_cb.called
        msg = log_cb.call_args[0][0]
        assert "created" in msg
        assert "file.txt" in msg

    def test_log_callback_includes_dir_marker(self):
        log_cb = Mock()
        monitor = _make_monitor(log_callback=log_cb)
        monitor._on_fs_event(MockEvent("created", "/src/dir", is_directory=True))
        _cancel_timer(monitor)
        msg = log_cb.call_args[0][0]
        assert "dir" in msg