"""Event-driven file system monitoring for backup profiles.
Uses watchdog for file events and ctypes + ReadDirectoryChangesW
for queue overflow detection on Windows.
"""
import os
import sys
import time
import threading
from typing import List, Dict, Callable, Optional, Set, Tuple
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ── Windows-specific: overflow detection via ReadDirectoryChangesW ──────
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    FILE_LIST_DIRECTORY = 0x0001
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
    FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
    FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
    FILE_NOTIFY_CHANGE_SIZE = 0x00000008

    ERROR_NOTIFY_ENUM_DIR = 1022

    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.restype = wintypes.HANDLE
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]

    _ReadDirectoryChangesW = _kernel32.ReadDirectoryChangesW
    _ReadDirectoryChangesW.restype = wintypes.BOOL
    _ReadDirectoryChangesW.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p, ctypes.c_void_p,
    ]

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.restype = wintypes.BOOL
    _CloseHandle.argtypes = [wintypes.HANDLE]

    _CancelIoEx = _kernel32.CancelIoEx
    _CancelIoEx.restype = wintypes.BOOL
    _CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]


# ── Watchdog event handler ──────────────────────────────────────────────

class _ProfileEventHandler(FileSystemEventHandler):
    """Forwards watchdog events to EventMonitor."""

    def __init__(self, monitor: "EventMonitor"):
        super().__init__()
        self.monitor = monitor

    def on_any_event(self, event):
        self.monitor._on_fs_event(event)


# ── Main monitor class ──────────────────────────────────────────────────

class EventMonitor:
    """File system monitor for a single backup profile.

    Lifecycle:
        monitor = EventMonitor(name, backup_cb, log_cb)
        monitor.start(dirs, filters, on_overflow, debounce)
        ...
        monitor.on_backup_complete()   # called by BackupApp after each backup
        ...
        monitor.stop()
    """

    def __init__(self, profile_name: str, callback: Callable, log_callback: Callable):
        """
        Args:
            profile_name: имя профиля (для логов)
            callback: fn(profile_name, events, overflow=False) — вызывается для запуска бэкапа
                      events: dict с ключами changed/deleted/moved/dirs_created/dirs_deleted/dirs_moved
            log_callback: fn(message) — вызывается для логирования
        """
        self.profile_name = profile_name
        self.callback = callback
        self.log_callback = log_callback

        # Config
        self.source_dirs: List[str] = []
        self.event_filters: List[str] = []
        self.on_overflow: str = "run_immediately"
        self.debounce_seconds: float = 5.0

        # Watchdog
        self.observer = None  

        # Event buffer (debounce)
        self._event_buffer: Dict[str, str] = {}  # path -> last_event_type
        self._moved_buffer: List[Tuple[str, str]] = []  # (src, dest)
        self._dir_event_buffer: Dict[str, str] = {}  # dir_path -> last_event_type
        self._dir_moved_buffer: List[Tuple[str, str]] = []  # (src, dest)
        self._buffer_lock = threading.Lock()

        # Debounce
        self._debounce_timer: Optional[threading.Timer] = None
        self._debounce_lock = threading.Lock()

        # Backup state
        self.backup_running = False
        self.pending_backup = False
        self._backup_lock = threading.Lock()

        # Overflow detection (Windows)
        self._overflow_threads: List[threading.Thread] = []
        self._overflow_stop_flag = False
        self._overflow_handles: Dict[str, object] = {}
        self._overflow_lock = threading.Lock()

        # Availability checker
        self._avail_thread: Optional[threading.Thread] = None
        self._avail_stop_flag = False
        self._dir_available: Dict[str, bool] = {}

        self._running = False

    # ── Public API ──────────────────────────────────────────────────────

    def start(self, source_dirs: List[str], event_filters: List[str],
              on_overflow: str, debounce_seconds: float):
        """Start monitoring. Stops any previous monitoring first."""
        self.stop()

        self.source_dirs = list(source_dirs)
        self.event_filters = list(event_filters)
        self.on_overflow = on_overflow
        self.debounce_seconds = debounce_seconds
        self._running = True
        self._overflow_stop_flag = False
        self._avail_stop_flag = False

        # Init availability map
        for d in self.source_dirs:
            self._dir_available[d] = os.path.exists(d)

        self._create_observer()
        self._start_overflow_monitors()
        self._start_availability_checker()

        self.log_callback(
            f"[{self.profile_name}] Monitoring started "
            f"({len(self.source_dirs)} dirs, "
            f"filters: {', '.join(self.event_filters)})"
        )

    def stop(self):
        """Stop all monitoring threads and observers."""
        if not self._running and self.observer is None:
            return
        self._running = False
        self._overflow_stop_flag = True
        self._avail_stop_flag = True

        # 1. Cancel debounce timer
        with self._debounce_lock:
            if self._debounce_timer:
                self._debounce_timer.cancel()
                self._debounce_timer = None

        # 2. Stop watchdog observer (join в отдельном потоке, чтобы не блокировать UI)
        if self.observer:
            obs = self.observer
            self.observer = None
            try:
                obs.stop()
            except Exception:
                pass
            # Не делаем join — observer daemon, завершится сам
            # Но если нужно — запускаем join в фоновом потоке
            def _join_observer():
                try:
                    obs.join(timeout=5)
                except Exception:
                    pass
            threading.Thread(target=_join_observer, daemon=True).start()

        # 3. Cancel overflow IO (потоки завершатся сами, они daemon)
        if sys.platform == "win32":
            with self._overflow_lock:
                for d, handle in self._overflow_handles.items():
                    try:
                        _CancelIoEx(handle, None)
                        _CloseHandle(handle)
                    except Exception:
                        pass
                self._overflow_handles.clear()

        self._overflow_threads.clear()

        # 4. Availability checker — поток завершится сам (daemon + flag)
        self._avail_thread = None

        self.log_callback(f"[{self.profile_name}] Monitoring stopped")

    def restart(self, source_dirs: List[str], event_filters: List[str],
                on_overflow: str, debounce_seconds: float):
        """Restart monitoring with new parameters."""
        self.start(source_dirs, event_filters, on_overflow, debounce_seconds)

    def on_backup_complete(self):
        """Must be called by BackupApp after backup finishes (success or fail)."""
        should_trigger = False
        events = None
        with self._backup_lock:
            self.backup_running = False
            if self.pending_backup:
                self.pending_backup = False
                self.log_callback(
                    f"[{self.profile_name}] Running pending backup "
                    f"(changes during previous backup)"
                )
                events = self._collect_events()
                if any(events.values()):
                    should_trigger = True
        # Вызываем вне lock, чтобы избежать deadlock
        if should_trigger and events:
            self._trigger_backup_with_events(events)

    # ── Watchdog observer ───────────────────────────────────────────────

    def _create_observer(self):
        self.observer = Observer()
        handler = _ProfileEventHandler(self)
        existing = [d for d in self.source_dirs if os.path.exists(d)]
        for d in existing:
            try:
                self.observer.schedule(handler, d, recursive=True)
            except Exception as e:
                self.log_callback(
                    f"[{self.profile_name}] Failed to watch '{d}': {e}"
                )
        if existing:
            self.observer.daemon = True
            self.observer.start()

    def _recreate_observer(self):
        """Re-create watchdog observer (e.g. after dir comes back online)."""
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=5)
            except Exception:
                pass
        self._create_observer()

    # ── File system event handling ──────────────────────────────────────

    def _on_fs_event(self, event):
        event_type = event.event_type  # "created"|"modified"|"deleted"|"moved"
        if event_type not in self.event_filters:
            return

        is_dir = event.is_directory
        path = event.src_path

        kind = "dir" if is_dir else "file"
        log_path = path
        if event_type == "moved" and hasattr(event, "dest_path"):
            log_path = f"{event.src_path} -> {event.dest_path}"

        self.log_callback(f"[{self.profile_name}] {event_type} ({kind}): {log_path}")

        # Добавляем событие в буфер
        with self._buffer_lock:
            if is_dir:
                if event_type == "moved" and hasattr(event, "dest_path"):
                    self._dir_moved_buffer.append((event.src_path, event.dest_path))
                else:
                    self._dir_event_buffer[path] = event_type
            else:
                if event_type == "moved" and hasattr(event, "dest_path"):
                    self._moved_buffer.append((event.src_path, event.dest_path))
                    # Удаляем src из буфера, если он там был
                    self._event_buffer.pop(event.src_path, None)
                    # Добавляем dest как "created"
                    self._event_buffer[event.dest_path] = "created"
                else:
                    # Дедупликация: created + modified → created
                    existing = self._event_buffer.get(path)
                    if existing == "created" and event_type == "modified":
                        pass  # Оставляем "created"
                    else:
                        self._event_buffer[path] = event_type

        self._reset_debounce()

    def _collect_events(self) -> Dict:
        """Собирает и дедуплицирует события из буфера."""
        with self._buffer_lock:
            # Обработка конфликтов: created + deleted → игнорировать
            changed = []
            deleted = []
            for path, event_type in self._event_buffer.items():
                if event_type == "deleted":
                    deleted.append(path)
                else:
                    # created или modified
                    if os.path.exists(path):
                        changed.append(path)
                    # Если файл не существует — игнорируем (был создан и удалён)

            moved = list(self._moved_buffer)

            dirs_created = []
            dirs_deleted = []
            for path, event_type in self._dir_event_buffer.items():
                if event_type == "deleted":
                    dirs_deleted.append(path)
                else:
                    if os.path.exists(path):
                        dirs_created.append(path)

            dirs_moved = list(self._dir_moved_buffer)

            # Очищаем буфер
            self._event_buffer.clear()
            self._moved_buffer.clear()
            self._dir_event_buffer.clear()
            self._dir_moved_buffer.clear()

        return {
            "changed": changed,
            "deleted": deleted,
            "moved": moved,
            "dirs_created": dirs_created,
            "dirs_deleted": dirs_deleted,
            "dirs_moved": dirs_moved,
        }

    def _reset_debounce(self):
        """Reset debounce timer. Backup will fire after debounce_seconds of silence."""
        with self._debounce_lock:
            if self._debounce_timer:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(
                self.debounce_seconds, self._fire_backup
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _fire_backup(self):
        """Собирает события и запускает бэкап."""
        events = self._collect_events()
        # Проверяем, есть ли реальные события (не пустые списки)
        if any(events.values()):
            self._trigger_backup_with_events(events)

    def _trigger_backup_with_events(self, events: Dict):
        """Decide whether to start backup now or queue it."""
        with self._backup_lock:
            if self.backup_running:
                self.pending_backup = True
                self.log_callback(
                    f"[{self.profile_name}] Backup already running, "
                    f"queued pending backup"
                )
                return
            self.backup_running = True

        # callback signature: fn(profile_name, events, overflow=False)
        self.callback(self.profile_name, events)

    # ── Overflow detection (Windows only) ───────────────────────────────

    def _start_overflow_monitors(self):
        if sys.platform != "win32":
            return
        for d in self.source_dirs:
            if not os.path.exists(d):
                continue
            t = threading.Thread(
                target=self._overflow_monitor_thread, args=(d,), daemon=True
            )
            self._overflow_threads.append(t)
            t.start()

    def _overflow_monitor_thread(self, dir_path: str):
        handle = _CreateFileW(
            dir_path,
            FILE_LIST_DIRECTORY,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if not handle or handle == INVALID_HANDLE_VALUE:
            self.log_callback(
                f"[{self.profile_name}] Overflow monitor: "
                f"cannot open '{dir_path}'"
            )
            return

        with self._overflow_lock:
            self._overflow_handles[dir_path] = handle

        buf_size = 65536
        buf = ctypes.create_string_buffer(buf_size)
        bytes_returned = wintypes.DWORD(0)
        notify_filter = (
            FILE_NOTIFY_CHANGE_FILE_NAME
            | FILE_NOTIFY_CHANGE_DIR_NAME
            | FILE_NOTIFY_CHANGE_LAST_WRITE
            | FILE_NOTIFY_CHANGE_SIZE
        )

        while not self._overflow_stop_flag:
            result = _ReadDirectoryChangesW(
                handle, buf, buf_size, True,
                notify_filter, ctypes.byref(bytes_returned),
                None, None,
            )
            if not result:
                err = ctypes.get_last_error()
                if err == ERROR_NOTIFY_ENUM_DIR:
                    self.log_callback(
                        f"[{self.profile_name}] Queue overflow detected "
                        f"for: {dir_path}"
                    )
                    self._handle_overflow()
                else:
                    if not self._overflow_stop_flag:
                        self.log_callback(
                            f"[{self.profile_name}] Overflow monitor "
                            f"error {err} for: {dir_path}"
                        )
                break

        with self._overflow_lock:
            self._overflow_handles.pop(dir_path, None)
        try:
            _CloseHandle(handle)
        except Exception:
            pass

    def _handle_overflow(self):
        if self.on_overflow == "run_immediately":
            self.log_callback(
                f"[{self.profile_name}] Queue overflow — "
                f"running full backup immediately"
            )
            # При переполнении запускаем полный бэкап (без событий)
            with self._backup_lock:
                if self.backup_running:
                    self.pending_backup = True
                    return
                self.backup_running = True
            self.callback(self.profile_name, None, overflow=True)
        elif self.on_overflow == "run_by_schedule":
            self.log_callback(
                f"[{self.profile_name}] Queue overflow — "
                f"will run by previous schedule"
            )
            self.callback(self.profile_name, None, overflow=True)
        elif self.on_overflow == "log_warning":
            self.log_callback(
                f"[{self.profile_name}] Queue overflow — "
                f"warning only, no action"
            )

    # ── Availability checker ────────────────────────────────────────────

    def _start_availability_checker(self):
        self._avail_thread = threading.Thread(
            target=self._availability_check_thread, daemon=True
        )
        self._avail_thread.start()

    def _availability_check_thread(self):
        while not self._avail_stop_flag:
            # Короткие sleep с проверкой флага (без threading.Event для Python 3.14)
            for _ in range(60):  # 60 * 0.5 = 30 секунд
                if self._avail_stop_flag:
                    return
                time.sleep(0.5)
            for d in list(self.source_dirs):
                was_available = self._dir_available.get(d, True)
                is_available = os.path.exists(d)
                if was_available and not is_available:
                    self._dir_available[d] = False
                    self.log_callback(
                        f"[{self.profile_name}] Source dir unavailable: {d}"
                    )
                elif not was_available and is_available:
                    self._dir_available[d] = True
                    self.log_callback(
                        f"[{self.profile_name}] Source dir back online: {d}"
                    )
                    self._recreate_observer()
                    # При возвращении директории запускаем полный бэкап
                    with self._backup_lock:
                        if self.backup_running:
                            self.pending_backup = True
                            continue
                        self.backup_running = True
                    self.callback(self.profile_name, None, overflow=False)