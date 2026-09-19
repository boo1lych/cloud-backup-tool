import os
import shutil
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox, simpledialog
from datetime import datetime
import threading
import json
import ctypes
import winreg as reg
import time
import schedule
import sys
import sv_ttk
import traceback
import atexit
import queue
import copy
from backup_logic import (
    validate_custom_time, validate_hhmm, backup_saves, is_reparse_point,
    validate_profile_name,
)
from error_log import error_logger
from profile_logger import ProfileLogger
import error_notifier

MAX_COPIED_LIST = 10000
WEEK_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MIN_FREE_BYTES = 1024 ** 3  # 1 GB minimum free space required

# Базовая директория: для .exe — рядом с exe, для скрипта — рядом с .py
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "bt2_config.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
CRASH_LOG_FILE = os.path.join(LOG_DIR, "crash_exit.log")

os.makedirs(LOG_DIR, exist_ok=True)


def log_exit_or_crash(reason, exc_info=None):
    """Логирует причины завершения работы или краха приложения."""
    msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CRITICAL] {reason}"
    if exc_info:
        msg += "\n" + "\n".join(traceback.format_exception(*exc_info))
    msg += "\n" + "-" * 50 + "\n"
    try:
        with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg)
            f.flush()
    except Exception:
        pass


def _global_exception_handler(exc_type, exc_value, exc_traceback):
    log_exit_or_crash("Unhandled exception in main thread", (exc_type, exc_value, exc_traceback))
    sys.excepthook(exc_type, exc_value, exc_traceback)


def _thread_exception_handler(args):
    thread_name = args.thread.name if args.thread else "Unknown"
    log_exit_or_crash(f"Unhandled exception in thread '{thread_name}'",
                      (args.exc_type, args.exc_value, args.exc_traceback))


def _atexit_handler():
    log_exit_or_crash("Python interpreter shutdown (atexit triggered)")


sys.excepthook = _global_exception_handler
if hasattr(threading, 'excepthook'):
    threading.excepthook = _thread_exception_handler
atexit.register(_atexit_handler)

import pystray
from PIL import Image


class BackupApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Cloud Backup Tool")
        self.root.geometry("1500x850")
        self.root.minsize(900, 650)
        self.root.resizable(True, True)

        # --- Иконка главного окна ---
        icon_path_ico = os.path.join(BASE_DIR, "backup.ico")
        icon_path_png = os.path.join(BASE_DIR, "backup.png")
        try:
            if os.path.exists(icon_path_ico):
                self.root.iconbitmap(icon_path_ico)
            elif os.path.exists(icon_path_png):
                self.icon_img = tk.PhotoImage(file=icon_path_png)
                self.root.iconphoto(True, self.icon_img)
        except Exception as e:
            print(f"Failed to set window icon: {e}")

        # --- Структура настроек (новый формат с профилями) ---
        self.settings = {
            "global": {
                "autorun": False,
                "start_minimized": False,
                "log_to_file": True,
                "active_profile": "Default",
                "theme": "light",
            },
            "profiles": {
                "Default": {
                    "source_dirs": [],
                    "backup_dir": "",
                    "skip_links": True,
                    "backup_schedule": "None",
                    "custom_time": "",
                    "exclude_patterns": "~$, *.tmp",
                    "enabled": False,
                    "auto_start_backup": False,
                    "weekly_days": ["Monday"],
                    "weekly_time": "23:00",
                }
            },
        }

        # Состояние каждого профиля
        self.profile_state = {}
        self.load_config()
        self._apply_theme(self.settings["global"].get("theme", "light"))
        for pname in self.settings["profiles"]:
            self.profile_state[pname] = {"running": False, "thread": None, "stop_flag": False}

        # --- Логгеры по профилям ---
        self.profile_logger = ProfileLogger()

        self.sched_stop = threading.Event()
        self.sched_thread = None
        self.schedule_lock = threading.Lock()
        self.profile_widgets = {}
        self.current_profile_name = None
        self.log_queue = queue.Queue()

        self.create_widgets()
        self.root.after(1000, self._flush_log_ui)
        self.root.after(2000, self._update_error_indicator)
        self.create_tray_icon()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.setup_schedule()

        if self.settings["global"].get("start_minimized", False):
            self.hide_window()
        else:
            self.root.deiconify()

        self.root.after(500, self._auto_start_on_launch)

    def _auto_start_on_launch(self):
        for pname, profile in self.settings["profiles"].items():
            if profile.get("enabled", False) and profile.get("auto_start_backup", False):
                self.start_profile_backup(pname, show_dialog=False)

    # =========================================================
    # ===================== UI CREATION =======================
    # =========================================================
    def create_widgets(self):
        # === Menu Bar ===
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Exit", command=self.exit_app)
        menubar.add_cascade(label="File", menu=file_menu)

        prefs_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Preferences", menu=prefs_menu)
        self.prefs_autorun_var = tk.BooleanVar(value=self.check_autorun())
        self.prefs_start_min_var = tk.BooleanVar(value=self.settings["global"].get("start_minimized", False))
        self.prefs_log_file_var = tk.BooleanVar(value=self.settings["global"].get("log_to_file", True))
        self.prefs_theme_var = tk.StringVar(value=self.settings["global"].get("theme", "light"))
        prefs_menu.add_checkbutton(label="Run at Windows startup", variable=self.prefs_autorun_var, command=self._toggle_autorun_from_menu)
        prefs_menu.add_checkbutton(label="Start minimized", variable=self.prefs_start_min_var, command=self._toggle_start_minimized_from_menu)
        prefs_menu.add_checkbutton(label="Save log to file", variable=self.prefs_log_file_var, command=self._toggle_log_to_file_from_menu)
        prefs_menu.add_separator()
        prefs_menu.add_command(label="VK Teams Alerts", command=self.open_vk_teams_alerts_settings)
        prefs_menu.add_separator()
        theme_menu = tk.Menu(prefs_menu, tearoff=0)
        theme_menu.add_radiobutton(label="Light", variable=self.prefs_theme_var, value="light", command=self._apply_theme_from_menu)
        theme_menu.add_radiobutton(label="Dark", variable=self.prefs_theme_var, value="dark", command=self._apply_theme_from_menu)
        prefs_menu.add_cascade(label="Theme", menu=theme_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.open_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

        # === Main frame ===
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === Глобальная панель управления (без изменений) ===
        global_control = ttk.LabelFrame(main_frame, text="Global Control", padding=10)
        global_control.pack(fill=tk.X, pady=(0, 10))
        gbtn_frame = ttk.Frame(global_control)
        gbtn_frame.pack(fill=tk.X)
        ttk.Button(gbtn_frame, text="► Start All",
                   command=self.start_all_backups, width=15).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(gbtn_frame, text="■ Stop All",
                   command=self.stop_all_backups, width=15).pack(side=tk.LEFT, padx=(0, 10))
        self.error_indicator = tk.Label(gbtn_frame, text="", fg="red", font=("Arial", 10, "bold"), cursor="hand2")
        self.error_indicator.pack(side=tk.RIGHT, padx=(20, 0))
        self.error_indicator.bind("<Button-1>", lambda e: self._open_error_summary())

        # === Master-Detail container ===
        master_detail = ttk.Frame(main_frame)
        master_detail.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # === Левая панель ===
        left_panel = ttk.Frame(master_detail, width=220)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)

        profiles_toolbar_row1 = ttk.Frame(left_panel)
        profiles_toolbar_row1.pack(fill=tk.X, pady=(0, 2))
        ttk.Button(profiles_toolbar_row1, text="New", command=self.new_profile, width=8).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(profiles_toolbar_row1, text="Rename", command=self.rename_profile, width=8).pack(side=tk.LEFT)

        profiles_toolbar_row2 = ttk.Frame(left_panel)
        profiles_toolbar_row2.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(profiles_toolbar_row2, text="Duplicate", command=self.duplicate_profile, width=8).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(profiles_toolbar_row2, text="Delete", command=self.delete_profile, width=8).pack(side=tk.LEFT)

        self.profiles_listbox = tk.Listbox(left_panel, exportselection=False, font=("Arial", 10))
        self.profiles_listbox.pack(fill=tk.BOTH, expand=True)
        self.profiles_listbox.bind("<<ListboxSelect>>", self.on_profile_selected)

        # === Правая панель ===
        right_panel = ttk.Frame(master_detail)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.profile_notebook = ttk.Notebook(right_panel)
        self.profile_notebook.pack(fill=tk.BOTH, expand=True)

        self.main_tab = ttk.Frame(self.profile_notebook, padding=10)
        self.process_control_tab = ttk.Frame(self.profile_notebook, padding=10)
        self.retry_settings_tab = ttk.Frame(self.profile_notebook, padding=10)
        self.profile_notebook.add(self.main_tab, text="Main")
        self.profile_notebook.add(self.process_control_tab, text="Process Control")
        self.profile_notebook.add(self.retry_settings_tab, text="Retry Settings")

        self._create_main_tab_widgets()
        self._create_process_control_tab_widgets()
        self._create_retry_settings_tab_widgets()

        # Заполняем Listbox
        for profile_name in self.settings["profiles"]:
            self.profiles_listbox.insert(tk.END, profile_name)

        # Выбираем активный профиль
        active = self.settings["global"].get("active_profile", "Default")
        if active in self.settings["profiles"]:
            idx = list(self.settings["profiles"].keys()).index(active)
            self.profiles_listbox.selection_set(idx)
            self.profiles_listbox.see(idx)
            self._load_profile_to_widgets(active)
        elif self.settings["profiles"]:
            self.profiles_listbox.selection_set(0)
            first_profile = list(self.settings["profiles"].keys())[0]
            self._load_profile_to_widgets(first_profile)

        # === Log ===
        log_frame = ttk.LabelFrame(main_frame, text="Backup Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_display = scrolledtext.ScrolledText(log_frame, height=8, width=90, font=("Consolas", 9))
        self.log_display.pack(fill=tk.BOTH, expand=True)

    def _create_main_tab_widgets(self):
        widgets = {}

        # Profile Control
        ctrl_frame = ttk.LabelFrame(self.main_tab, text="Profile Control", padding=10)
        ctrl_frame.pack(fill=tk.X, pady=(0, 10))
        ctrl_inner = ttk.Frame(ctrl_frame)
        ctrl_inner.pack(fill=tk.X)

        widgets["enabled_var"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctrl_inner, text="Enabled", variable=widgets["enabled_var"],
                        command=self.on_profile_enabled_changed).pack(side=tk.LEFT, padx=(0, 20))
        widgets["start_btn"] = ttk.Button(ctrl_inner, text="► Start",
                                          command=self.start_current_profile_backup, width=12)
        widgets["start_btn"].pack(side=tk.LEFT, padx=(0, 5))
        widgets["stop_btn"] = ttk.Button(ctrl_inner, text="■ Stop",
                                         command=self.stop_current_profile_backup, width=12, state=tk.DISABLED)
        widgets["stop_btn"].pack(side=tk.LEFT, padx=(0, 20))
        widgets["status_label"] = ttk.Label(ctrl_inner, text="Idle", foreground="gray")
        widgets["status_label"].pack(side=tk.LEFT)

        # Source Directories
        source_frame = ttk.LabelFrame(self.main_tab, text="Source Directories", padding=10)
        source_frame.pack(fill=tk.X, pady=(0, 10))
        widgets["source_listbox"] = tk.Listbox(source_frame, selectmode=tk.EXTENDED, height=4, width=80)
        widgets["source_listbox"].pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        source_btns = ttk.Frame(source_frame)
        source_btns.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Button(source_btns, text="Add...", command=self.add_source, width=12).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(source_btns, text="Remove", command=self.remove_source, width=12).pack(fill=tk.X)

        # Backup Destination
        dest_frame = ttk.LabelFrame(self.main_tab, text="Backup Destination", padding=10)
        dest_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(dest_frame, text="Directory:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        widgets["backup_entry"] = ttk.Entry(dest_frame, width=60)
        widgets["backup_entry"].grid(row=0, column=1, padx=(0, 10), sticky=tk.EW)
        ttk.Button(dest_frame, text="Browse...", command=self.browse_backup).grid(row=0, column=2)
        dest_frame.columnconfigure(1, weight=1)

        # Profile Settings
        settings_frame = ttk.LabelFrame(self.main_tab, text="Profile Settings", padding=10)
        settings_frame.pack(fill=tk.X, pady=(0, 10))

        left_col = ttk.Frame(settings_frame)
        left_col.grid(row=0, column=0, sticky=tk.NW, padx=(0, 20))
        widgets["skip_links_var"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(left_col, text="Skip symbolic links/junctions",
                        variable=widgets["skip_links_var"],
                        command=self.save_current_profile_settings).pack(anchor=tk.W, pady=2)
        widgets["auto_start_backup_var"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(left_col, text="Run backup immediately on app start",
                        variable=widgets["auto_start_backup_var"],
                        command=self.save_current_profile_settings).pack(anchor=tk.W, pady=2)

        right_col = ttk.Frame(settings_frame)
        right_col.grid(row=0, column=1, sticky=tk.NW)

        ttk.Label(right_col, text="Backup Schedule:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        widgets["schedule_var"] = tk.StringVar(value="None")
        widgets["schedule_menu"] = ttk.Combobox(right_col, textvariable=widgets["schedule_var"],
                                                values=["None", "Daily 23:00", "Daily 18:00", "Daily 10:00", "Custom", "Weekly"],
                                                state="readonly", width=15)
        widgets["schedule_menu"].grid(row=0, column=1, padx=(0, 10))
        widgets["schedule_menu"].bind("<<ComboboxSelected>>", self.schedule_changed)

        widgets["custom_time_entry"] = ttk.Entry(right_col, width=10)
        widgets["custom_time_entry"].grid(row=0, column=2, padx=(0, 10))
        widgets["custom_time_entry"].bind("<FocusOut>", self.on_custom_time_changed)
        widgets["custom_time_entry"].bind("<Return>", self.on_custom_time_changed)

        widgets["weekly_time_entry"] = ttk.Entry(right_col, width=10)
        widgets["weekly_time_entry"].grid(row=0, column=2, padx=(0, 10))
        widgets["weekly_time_entry"].bind("<FocusOut>", self.on_weekly_settings_changed)
        widgets["weekly_time_entry"].bind("<Return>", self.on_weekly_settings_changed)

        widgets["custom_hint_label"] = tk.Label(right_col, text="Examples: 21:30 (daily at 21:30), 120 (every 120 minutes)", fg="gray")
        widgets["custom_hint_label"].grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=(0, 5))
        widgets["weekly_hint_label"] = tk.Label(right_col, text="Time format: HH:MM (e.g., 23:00)", fg="gray")
        widgets["weekly_hint_label"].grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=(0, 5))

        widgets["weekly_days_frame"] = ttk.Frame(right_col)
        widgets["weekly_days_frame"].grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(0, 5))
        widgets["weekly_day_vars"] = {}
        for day in WEEK_DAYS:
            var = tk.BooleanVar(value=False)
            widgets["weekly_day_vars"][day] = var
            ttk.Checkbutton(widgets["weekly_days_frame"], text=day[:3], variable=var,
                            command=self.on_weekly_settings_changed).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Label(right_col, text="Exclude patterns (comma-separated):").grid(row=3, column=0, sticky=tk.W, pady=(10, 0))
        widgets["exclude_entry"] = ttk.Entry(right_col, width=40)
        widgets["exclude_entry"].grid(row=3, column=1, columnspan=2, sticky=tk.EW, pady=(10, 0))
        widgets["exclude_hint_label"] = tk.Label(right_col, text="Masks: *$*.txt, ~$, *.tmp, logs/*", fg="gray")
        widgets["exclude_hint_label"].grid(row=4, column=1, columnspan=2, sticky=tk.W, pady=(0, 5))

        widgets["custom_time_entry"].grid_remove()
        widgets["custom_hint_label"].grid_remove()
        widgets["weekly_time_entry"].grid_remove()
        widgets["weekly_days_frame"].grid_remove()
        widgets["weekly_hint_label"].grid_remove()

        self.profile_widgets = widgets

    def _create_process_control_tab_widgets(self):
        widgets = self.profile_widgets
        pc_frame = ttk.LabelFrame(self.process_control_tab, text="Process Control", padding=10)
        pc_frame.pack(fill=tk.X, pady=(0, 10))

        widgets["pc_enabled_var"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(pc_frame, text="Enable process control", variable=widgets["pc_enabled_var"],
                        command=self.save_current_profile_settings).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 10))

        ttk.Label(pc_frame, text="Processes to close before backup:").grid(row=1, column=0, sticky=tk.NW, pady=(0, 5))
        widgets["pc_close_listbox"] = tk.Listbox(pc_frame, height=5, width=28)
        widgets["pc_close_listbox"].grid(row=2, column=0, rowspan=2, sticky=tk.NW, padx=(0, 10))

        pc_btns = ttk.Frame(pc_frame)
        pc_btns.grid(row=2, column=1, rowspan=2, sticky=tk.NW)
        ttk.Button(pc_btns, text="Add...", command=self.add_process_to_close, width=12).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(pc_btns, text="Remove", command=self.remove_process_to_close, width=12).pack(fill=tk.X)

        ttk.Label(pc_frame, text="Close mode:").grid(row=2, column=2, sticky=tk.W, padx=(20, 10), pady=2)
        widgets["pc_close_mode_var"] = tk.StringVar(value="graceful_then_force")
        ttk.Combobox(pc_frame, textvariable=widgets["pc_close_mode_var"],
                     values=["graceful", "force", "graceful_then_force"],
                     state="readonly", width=22).grid(row=2, column=3, sticky=tk.W, pady=2)

        ttk.Label(pc_frame, text="Graceful timeout (sec):").grid(row=3, column=2, sticky=tk.W, padx=(20, 10), pady=2)
        widgets["pc_graceful_timeout_var"] = tk.StringVar(value="10")
        ttk.Entry(pc_frame, textvariable=widgets["pc_graceful_timeout_var"], width=10).grid(row=3, column=3, sticky=tk.W, pady=2)

        ttk.Label(pc_frame, text="On close failure:").grid(row=4, column=2, sticky=tk.W, padx=(20, 10), pady=2)
        widgets["pc_on_close_failure_var"] = tk.StringVar(value="abort")
        ttk.Combobox(pc_frame, textvariable=widgets["pc_on_close_failure_var"],
                     values=["abort", "continue"], state="readonly", width=22).grid(row=4, column=3, sticky=tk.W, pady=2)

        ttk.Label(pc_frame, text="Restore after:").grid(row=5, column=2, sticky=tk.W, padx=(20, 10), pady=2)
        widgets["pc_restore_after_var"] = tk.StringVar(value="only_if_was_running")
        ttk.Combobox(pc_frame, textvariable=widgets["pc_restore_after_var"],
                     values=["always", "only_if_was_running", "never"],
                     state="readonly", width=22).grid(row=5, column=3, sticky=tk.W, pady=2)

    def _create_retry_settings_tab_widgets(self):
        widgets = self.profile_widgets
        retry_frame = ttk.LabelFrame(self.retry_settings_tab, text="Retry Settings", padding=10)
        retry_frame.pack(fill=tk.X, pady=(0, 10))

        widgets["retry_enabled_var"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(retry_frame, text="Enable retry", variable=widgets["retry_enabled_var"],
                        command=self.save_current_profile_settings).pack(anchor=tk.W, pady=(0, 10))

        retry_opts = ttk.Frame(retry_frame)
        retry_opts.pack(fill=tk.X)

        ttk.Label(retry_opts, text="Max attempts:").grid(row=0, column=0, sticky=tk.W, pady=2)
        widgets["retry_max_attempts_var"] = tk.StringVar(value="3")
        ttk.Entry(retry_opts, textvariable=widgets["retry_max_attempts_var"], width=10).grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=2)

        ttk.Label(retry_opts, text="Interval (seconds):").grid(row=1, column=0, sticky=tk.W, pady=2)
        widgets["retry_interval_seconds_var"] = tk.StringVar(value="300")
        ttk.Entry(retry_opts, textvariable=widgets["retry_interval_seconds_var"], width=10).grid(row=1, column=1, sticky=tk.W, padx=(10, 0), pady=2)

        ttk.Label(retry_opts, text="Retry on:").grid(row=0, column=2, sticky=tk.W, padx=(20, 0), pady=2)
        widgets["retry_on_vars"] = {}
        retry_on_options = ["disk_unavailable", "process_close_failed", "copy_errors", "low_disk_space", "source_missing", "timeout_exceeded"]
        retry_on_labels = ["Disk unavailable", "Process close failed", "Copy errors", "Low disk space", "Source missing", "Timeout exceeded"]
        for i, (opt, label) in enumerate(zip(retry_on_options, retry_on_labels)):
            var = tk.BooleanVar(value=False)
            widgets["retry_on_vars"][opt] = var
            row = i // 2
            col = 2 + (i % 2)
            ttk.Checkbutton(retry_opts, text=label, variable=var,
                            command=self.save_current_profile_settings).grid(row=row, column=col, sticky=tk.W, padx=(20, 0), pady=2)

        ttk.Label(retry_frame, text="On total failure:").pack(anchor=tk.W, pady=(10, 5))
        widgets["retry_failure_listbox"] = tk.Listbox(retry_frame, height=4, width=60)
        widgets["retry_failure_listbox"].pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        widgets["retry_on_total_failure_actions"] = []
        failure_btns = ttk.Frame(retry_frame)
        failure_btns.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Button(failure_btns, text="Add...", command=lambda: self.open_action_dialog(None), width=12).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(failure_btns, text="Edit...", command=lambda: self.open_action_dialog("selected"), width=12).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(failure_btns, text="Remove", command=self.remove_failure_action, width=12).pack(fill=tk.X)

        timeout_frame = ttk.LabelFrame(self.retry_settings_tab, text="Total Timeout", padding=10)
        timeout_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(timeout_frame, text="Timeout (minutes):").pack(side=tk.LEFT, padx=(0, 10))
        widgets["total_timeout_minutes_var"] = tk.StringVar(value="0")
        ttk.Entry(timeout_frame, textvariable=widgets["total_timeout_minutes_var"], width=10).pack(side=tk.LEFT)
        ttk.Label(timeout_frame, text="(0 = no timeout)", foreground="gray").pack(side=tk.LEFT, padx=(10, 0))

    # =========================================================
    # ============= PROFILE WIDGETS LOADING ===================
    # =========================================================
    def _load_profile_to_widgets(self, profile_name):
        if profile_name not in self.settings["profiles"]:
            return
        self.current_profile_name = profile_name
        profile_data = self.settings["profiles"][profile_name]
        w = self.profile_widgets

        # Main tab
        w["enabled_var"].set(profile_data.get("enabled", False))
        w["source_listbox"].delete(0, tk.END)
        for path in profile_data.get("source_dirs", []):
            w["source_listbox"].insert(tk.END, path)
        w["backup_entry"].delete(0, tk.END)
        w["backup_entry"].insert(0, profile_data.get("backup_dir", ""))
        w["skip_links_var"].set(profile_data.get("skip_links", True))
        w["auto_start_backup_var"].set(profile_data.get("auto_start_backup", False))
        w["schedule_var"].set(profile_data.get("backup_schedule", "None"))
        w["custom_time_entry"].delete(0, tk.END)
        w["custom_time_entry"].insert(0, profile_data.get("custom_time", ""))
        w["weekly_time_entry"].delete(0, tk.END)
        w["weekly_time_entry"].insert(0, profile_data.get("weekly_time", "23:00"))
        w["exclude_entry"].delete(0, tk.END)
        w["exclude_entry"].insert(0, profile_data.get("exclude_patterns", ""))
        selected_days = profile_data.get("weekly_days", ["Monday"])
        for day, var in w["weekly_day_vars"].items():
            var.set(day in selected_days)
        self._update_schedule_visibility()

        # Advanced tab: Process Control
        pc = profile_data.get("process_control", {})
        w["pc_enabled_var"].set(pc.get("enabled", False))
        w["pc_close_listbox"].delete(0, tk.END)
        for proc in pc.get("close_before", []):
            w["pc_close_listbox"].insert(tk.END, proc)
        w["pc_close_mode_var"].set(pc.get("close_mode", "graceful_then_force"))
        w["pc_graceful_timeout_var"].set(str(pc.get("graceful_timeout_sec", 10)))
        w["pc_on_close_failure_var"].set(pc.get("on_close_failure", "abort"))
        w["pc_restore_after_var"].set(pc.get("restore_after", "only_if_was_running"))

        # Advanced tab: Retry Settings
        retry = profile_data.get("retry", {})
        w["retry_enabled_var"].set(retry.get("enabled", False))
        w["retry_max_attempts_var"].set(str(retry.get("max_attempts", 3)))
        w["retry_interval_seconds_var"].set(str(retry.get("interval_seconds", 300)))
        retry_on_list = retry.get("retry_on", [])
        for opt, var in w["retry_on_vars"].items():
            var.set(opt in retry_on_list)
        w["retry_on_total_failure_actions"] = copy.deepcopy(retry.get("on_total_failure", []))
        self._update_failure_listbox()

        # Total Timeout
        w["total_timeout_minutes_var"].set(str(profile_data.get("total_timeout_minutes", 0)))

        self.update_profile_status(profile_name)
        self._update_custom_time_hint()
        self._refresh_log_display(profile_name)

    def _update_schedule_visibility(self):
        w = self.profile_widgets
        value = w["schedule_var"].get()
        w["custom_time_entry"].grid_remove()
        w["custom_hint_label"].grid_remove()
        w["weekly_time_entry"].grid_remove()
        w["weekly_days_frame"].grid_remove()
        w["weekly_hint_label"].grid_remove()
        if value == "Custom":
            w["custom_time_entry"].grid()
            w["custom_hint_label"].grid()
        elif value == "Weekly":
            w["weekly_time_entry"].grid()
            w["weekly_days_frame"].grid()
            w["weekly_hint_label"].grid()

    # =========================================================
    # =============== PROFILE SELECTION / SAVE ================
    # =========================================================
    def on_profile_selected(self, event=None):
        sel = self.profiles_listbox.curselection()
        if not sel:
            return
        new_name = self.profiles_listbox.get(sel[0])
        # Сохраняем предыдущий профиль
        if self.current_profile_name and self.current_profile_name != new_name:
            self.save_current_profile_settings()
        self._load_profile_to_widgets(new_name)
        self.settings["global"]["active_profile"] = new_name
        self.save_config()

    def save_current_profile_settings(self):
        if not self.current_profile_name or self.current_profile_name not in self.settings["profiles"]:
            return
        self._sync_profile_widgets_to_settings(self.current_profile_name)
        self.save_config()

    def _sync_profile_widgets_to_settings(self, profile_name):
        if profile_name not in self.settings["profiles"]:
            return
        w = self.profile_widgets
        p = self.settings["profiles"][profile_name]
        p["source_dirs"] = list(w["source_listbox"].get(0, tk.END))
        p["backup_dir"] = w["backup_entry"].get()
        p["skip_links"] = w["skip_links_var"].get()
        p["backup_schedule"] = w["schedule_var"].get()
        p["custom_time"] = w["custom_time_entry"].get()
        p["exclude_patterns"] = w["exclude_entry"].get()
        p["enabled"] = w["enabled_var"].get()
        p["auto_start_backup"] = w["auto_start_backup_var"].get()
        p["weekly_time"] = w["weekly_time_entry"].get()
        p["weekly_days"] = [day for day, var in w["weekly_day_vars"].items() if var.get()]
        p["process_control"] = {
            "enabled": w["pc_enabled_var"].get(),
            "close_before": list(w["pc_close_listbox"].get(0, tk.END)),
            "close_mode": w["pc_close_mode_var"].get(),
            "graceful_timeout_sec": int(w["pc_graceful_timeout_var"].get() or 10),
            "on_close_failure": w["pc_on_close_failure_var"].get(),
            "restore_after": w["pc_restore_after_var"].get()
        }
        retry_on = [opt for opt, var in w["retry_on_vars"].items() if var.get()]
        p["retry"] = {
            "enabled": w["retry_enabled_var"].get(),
            "max_attempts": int(w["retry_max_attempts_var"].get() or 3),
            "interval_seconds": int(w["retry_interval_seconds_var"].get() or 300),
            "retry_on": retry_on,
            "on_total_failure": w.get("retry_on_total_failure_actions", [])
        }
        p["total_timeout_minutes"] = int(w["total_timeout_minutes_var"].get() or 0)

    # =========================================================
    # ============== PROFILE MANAGEMENT (NEW) =================
    # =========================================================
    def get_active_profile_name(self):
        if self.current_profile_name and self.current_profile_name in self.settings["profiles"]:
            return self.current_profile_name
        return self.settings["global"].get("active_profile", "Default")

    def _refresh_profiles_listbox(self, select_name=None):
        self.profiles_listbox.delete(0, tk.END)
        names = list(self.settings["profiles"].keys())
        for name in names:
            self.profiles_listbox.insert(tk.END, name)
        target = select_name or self.settings["global"].get("active_profile", "Default")
        if target in names:
            idx = names.index(target)
            self.profiles_listbox.selection_clear(0, tk.END)
            self.profiles_listbox.selection_set(idx)
            self.profiles_listbox.see(idx)
            self._load_profile_to_widgets(target)
        elif names:
            self.profiles_listbox.selection_set(0)
            self._load_profile_to_widgets(names[0])

    def new_profile(self):
        name = simpledialog.askstring("New Profile", "Enter profile name:", parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        ok, err = validate_profile_name(name)
        if not ok:
            messagebox.showerror("Error", f"Invalid profile name: {err}")
            return
        if name in self.settings["profiles"]:
            messagebox.showerror("Error", f"Profile '{name}' already exists.")
            return
        self.settings["profiles"][name] = {
            "source_dirs": [], "backup_dir": "", "skip_links": True,
            "backup_schedule": "None", "custom_time": "", "exclude_patterns": "",
            "enabled": False, "auto_start_backup": False,
            "weekly_days": ["Monday"], "weekly_time": "23:00",
        }
        self.profile_state[name] = {"running": False, "thread": None, "stop_flag": False}
        self.settings["global"]["active_profile"] = name
        self.save_config()
        self.setup_schedule()
        self._refresh_profiles_listbox(name)

    def rename_profile(self):
        old_name = self.get_active_profile_name()
        if old_name == "Default":
            messagebox.showwarning("Warning", "The 'Default' profile cannot be renamed.")
            return
        new_name = simpledialog.askstring("Rename Profile", f"Enter new name for '{old_name}':",
                                          parent=self.root, initialvalue=old_name)
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        ok, err = validate_profile_name(new_name)
        if not ok:
            messagebox.showerror("Error", f"Invalid profile name: {err}")
            return
        if new_name in self.settings["profiles"]:
            messagebox.showerror("Error", f"Profile '{new_name}' already exists.")
            return
        # Сохраняем текущие настройки перед переименованием
        self.save_current_profile_settings()
        self.settings["profiles"][new_name] = self.settings["profiles"].pop(old_name)
        self.profile_state[new_name] = self.profile_state.pop(old_name)
        if self.settings["global"].get("active_profile") == old_name:
            self.settings["global"]["active_profile"] = new_name
        self.profile_logger.on_profile_renamed(old_name, new_name)
        self.save_config()
        self.setup_schedule()
        self._refresh_profiles_listbox(new_name)

    def duplicate_profile(self):
        src_name = self.get_active_profile_name()
        new_name = simpledialog.askstring("Duplicate Profile",
                                          f"Enter name for copy of '{src_name}':",
                                          parent=self.root, initialvalue=f"{src_name} (copy)")
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        ok, err = validate_profile_name(new_name)
        if not ok:
            messagebox.showerror("Error", f"Invalid profile name: {err}")
            return
        if new_name in self.settings["profiles"]:
            messagebox.showerror("Error", f"Profile '{new_name}' already exists.")
            return
        self.save_current_profile_settings()
        self.settings["profiles"][new_name] = copy.deepcopy(self.settings["profiles"][src_name])
        self.settings["profiles"][new_name]["enabled"] = False
        self.profile_state[new_name] = {"running": False, "thread": None, "stop_flag": False}
        self.save_config()
        self._refresh_profiles_listbox(new_name)

    def delete_profile(self):
        name = self.get_active_profile_name()
        if name == "Default":
            messagebox.showwarning("Warning", "The 'Default' profile cannot be deleted.")
            return
        if self.profile_state.get(name, {}).get("running", False):
            messagebox.showwarning("Warning", f"Profile '{name}' is currently running. Stop it first.")
            return
        if not messagebox.askyesno("Confirm Delete", f"Delete profile '{name}'?"):
            return
        del self.settings["profiles"][name]
        self.profile_state.pop(name, None)
        self.profile_logger.on_profile_deleted(name)
        if self.settings["global"].get("active_profile") == name:
            self.settings["global"]["active_profile"] = "Default"
        self.save_config()
        self.setup_schedule()
        self._refresh_profiles_listbox()

    # =========================================================
    # ========== CURRENT PROFILE BUTTON HANDLERS ==============
    # =========================================================
    def start_current_profile_backup(self):
        name = self.get_active_profile_name()
        if name:
            self.start_profile_backup(name)

    def stop_current_profile_backup(self):
        name = self.get_active_profile_name()
        if name:
            self.stop_profile_backup(name)

    def on_profile_enabled_changed(self):
        name = self.get_active_profile_name()
        if not name:
            return
        enabled = self.profile_widgets["enabled_var"].get()
        self.settings["profiles"][name]["enabled"] = enabled
        self.save_config()
        self.setup_schedule()
        self.update_profile_status(name)
        self.update_log(f"Profile '{name}' {'enabled' if enabled else 'disabled'}",
                        profile_name=name)

    def add_source(self):
        directory = filedialog.askdirectory()
        if directory:
            current = list(self.profile_widgets["source_listbox"].get(0, tk.END))
            if directory not in current:
                self.profile_widgets["source_listbox"].insert(tk.END, directory)
                self.save_current_profile_settings()

    def remove_source(self):
        selected = list(self.profile_widgets["source_listbox"].curselection())
        for idx in reversed(selected):
            self.profile_widgets["source_listbox"].delete(idx)
        self.save_current_profile_settings()

    def browse_backup(self):
        current = self.profile_widgets["backup_entry"].get()
        initial = current if current else os.getcwd()
        directory = filedialog.askdirectory(initialdir=initial)
        if directory:
            self.profile_widgets["backup_entry"].delete(0, tk.END)
            self.profile_widgets["backup_entry"].insert(0, directory)
            self.save_current_profile_settings()

    def add_process_to_close(self):
        proc = simpledialog.askstring("Add Process", "Enter process name (e.g., OUTLOOK.EXE):", parent=self.root)
        if proc:
            proc = proc.strip().upper()
            current = list(self.profile_widgets["pc_close_listbox"].get(0, tk.END))
            if proc not in current:
                self.profile_widgets["pc_close_listbox"].insert(tk.END, proc)
                self.save_current_profile_settings()

    def remove_process_to_close(self):
        selected = list(self.profile_widgets["pc_close_listbox"].curselection())
        for idx in reversed(selected):
            self.profile_widgets["pc_close_listbox"].delete(idx)
        self.save_current_profile_settings()

    def _update_failure_listbox(self):
        w = self.profile_widgets
        w["retry_failure_listbox"].delete(0, tk.END)
        for action in w.get("retry_on_total_failure_actions", []):
            if action.get("action") == "run_script":
                w["retry_failure_listbox"].insert(tk.END, f"run_script: {action.get('script_path', '')}")
            elif action.get("action") == "show_message":
                w["retry_failure_listbox"].insert(tk.END, f"show_message: {action.get('message', '')}")

    def remove_failure_action(self):
        w = self.profile_widgets
        selected = list(w["retry_failure_listbox"].curselection())
        actions = w.get("retry_on_total_failure_actions", [])
        for idx in reversed(selected):
            if idx < len(actions):
                actions.pop(idx)
                w["retry_failure_listbox"].delete(idx)
        self.save_current_profile_settings()

    def open_action_dialog(self, edit_index):
        w = self.profile_widgets
        actions = w.get("retry_on_total_failure_actions", [])
        if edit_index == "selected":
            sel = w["retry_failure_listbox"].curselection()
            if not sel:
                return
            edit_index = sel[0]
            existing = actions[edit_index]
        else:
            existing = {"action": "run_script", "script_path": "", "log_output": True,
                        "message": "Backup failed after all retries"}

        dialog = tk.Toplevel(self.root)
        dialog.title("Action Settings")
        
        # Центрирование относительно главного окна
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_width = self.root.winfo_width()
        main_height = self.root.winfo_height()
        x = main_x + (main_width - 400) // 2
        y = main_y + (main_height - 250) // 2
        dialog.geometry(f"400x250+{x}+{y}")
        
        dialog.minsize(400, 250)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.attributes('-toolwindow', True)

        ttk.Label(dialog, text="Action type:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        action_type_var = tk.StringVar(value=existing.get("action", "run_script"))
        type_cb = ttk.Combobox(dialog, textvariable=action_type_var,
                               values=["run_script", "show_message"], state="readonly", width=20)
        type_cb.pack(anchor=tk.W, padx=10, pady=(0, 10))

        frame_script = ttk.LabelFrame(dialog, text="run_script", padding=10)
        frame_script.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(frame_script, text="Script path:").grid(row=0, column=0, sticky=tk.W, pady=2)
        script_path_var = tk.StringVar(value=existing.get("script_path", ""))
        ttk.Entry(frame_script, textvariable=script_path_var, width=30).grid(row=0, column=1, padx=5, pady=2)
        ttk.Button(frame_script, text="Browse...",
                   command=lambda: self._browse_script(script_path_var)).grid(row=0, column=2, pady=2)
        log_output_var = tk.BooleanVar(value=existing.get("log_output", True))
        ttk.Checkbutton(frame_script, text="Log output to backup log",
                        variable=log_output_var).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=5)

        frame_msg = ttk.LabelFrame(dialog, text="show_message", padding=10)
        frame_msg.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(frame_msg, text="Message:").grid(row=0, column=0, sticky=tk.W, pady=2)
        message_var = tk.StringVar(value=existing.get("message", "Backup failed after all retries"))
        ttk.Entry(frame_msg, textvariable=message_var, width=40).grid(row=0, column=1, padx=5, pady=2)

        def update_visibility(*args):
            if action_type_var.get() == "run_script":
                frame_script.pack(fill=tk.X, padx=10, pady=5)
                frame_msg.pack_forget()
            else:
                frame_script.pack_forget()
                frame_msg.pack(fill=tk.X, padx=10, pady=5)

        action_type_var.trace_add("write", update_visibility)
        update_visibility()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        def on_ok():
            new_action = {"action": action_type_var.get()}
            if new_action["action"] == "run_script":
                new_action["script_path"] = script_path_var.get()
                new_action["log_output"] = log_output_var.get()
            else:
                new_action["message"] = message_var.get()
            if edit_index is not None and isinstance(edit_index, int):
                actions[edit_index] = new_action
            else:
                actions.append(new_action)
            w["retry_on_total_failure_actions"] = actions
            self._update_failure_listbox()
            self.save_current_profile_settings()
            dialog.destroy()

        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy, width=10).pack(side=tk.RIGHT, padx=(0, 5))
        ttk.Button(btn_frame, text="OK", command=on_ok, width=10).pack(side=tk.RIGHT)

    def _browse_script(self, string_var):
        path = filedialog.askopenfilename(filetypes=[("Scripts", "*.bat *.ps1 *.exe"), ("All files", "*.*")])
        if path:
            string_var.set(path)

    def on_custom_time_changed(self, event=None):
        self.save_current_profile_settings()
        self.setup_schedule()
        self._update_custom_time_hint()

    def on_weekly_settings_changed(self, event=None):
        self.save_current_profile_settings()
        self.setup_schedule()
        self._update_custom_time_hint()

    def schedule_changed(self, event=None):
        self._update_schedule_visibility()
        self.save_current_profile_settings()
        self.setup_schedule()
        self.update_tray_menu()

    # =========================================================
    # ============= PREFERENCES & ABOUT DIALOGS ===============
    # =========================================================
    def open_preferences(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Preferences")
        dialog.geometry("350x240")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        autorun_var = tk.BooleanVar(value=self.check_autorun())
        start_min_var = tk.BooleanVar(value=self.settings["global"].get("start_minimized", False))
        log_file_var = tk.BooleanVar(value=self.settings["global"].get("log_to_file", True))
        theme_var = tk.StringVar(value=self.settings["global"].get("theme", "light"))

        ttk.Checkbutton(frame, text="Run at Windows startup", variable=autorun_var).pack(anchor=tk.W, pady=5)
        ttk.Checkbutton(frame, text="Start minimized", variable=start_min_var).pack(anchor=tk.W, pady=5)
        ttk.Checkbutton(frame, text="Save log to file", variable=log_file_var).pack(anchor=tk.W, pady=5)

        theme_frame = ttk.Frame(frame)
        theme_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(theme_frame, text="Theme:").pack(side=tk.LEFT, padx=(0, 10))
        theme_combo = ttk.Combobox(theme_frame, textvariable=theme_var,
                                values=["light", "dark"], state="readonly", width=10)
        theme_combo.pack(side=tk.LEFT)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))

        def on_ok():
            # Autorun
            if autorun_var.get() != self.check_autorun():
                self.set_autorun(autorun_var.get())
            # Start minimized
            self.settings["global"]["start_minimized"] = start_min_var.get()
            # Log to file
            self.settings["global"]["log_to_file"] = log_file_var.get()
            # Theme
            new_theme = theme_var.get()
            self.settings["global"]["theme"] = new_theme
            self._apply_theme(new_theme)
            self.prefs_theme_var.set(new_theme)
            self.save_config()
            dialog.destroy()

        ttk.Button(btn_frame, text="OK", command=on_ok, width=10).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy, width=10).pack(side=tk.RIGHT, padx=(0, 5))

    def open_vk_teams_alerts_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("VK Teams Alerts")
        
        # Центрирование относительно главного окна
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_width = self.root.winfo_width()
        main_height = self.root.winfo_height()
        x = main_x + (main_width - 520) // 2
        y = main_y + (main_height - 420) // 2
        dialog.geometry(f"520x420+{x}+{y}")
        
        dialog.minsize(520, 420)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.attributes('-toolwindow', True)

        cfg = error_notifier.load_config()

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        enabled_var = tk.BooleanVar(value=cfg.get("enabled", False))
        ttk.Checkbutton(frame, text="Enable notifications", variable=enabled_var).pack(anchor=tk.W, pady=(0, 10))

        # Bot Token
        token_frame = ttk.Frame(frame)
        token_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(token_frame, text="Bot Token:").pack(side=tk.LEFT, padx=(0, 10))
        token_var = tk.StringVar(value=cfg.get("bot_token", ""))
        token_entry = ttk.Entry(token_frame, textvariable=token_var, width=40, show="•")
        token_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Chat IDs
        chat_frame = ttk.LabelFrame(frame, text="Chat IDs", padding=10)
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        chat_listbox = tk.Listbox(chat_frame, height=6, font=("Consolas", 9))
        chat_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        for cid in cfg.get("chat_ids", []):
            chat_listbox.insert(tk.END, cid)

        chat_btns = ttk.Frame(chat_frame)
        chat_btns.pack(side=tk.RIGHT, fill=tk.Y)

        def add_chat_id():
            cid = simpledialog.askstring("Add Chat ID", "Enter chat ID:", parent=dialog)
            if cid:
                cid = cid.strip()
                if cid and cid not in chat_listbox.get(0, tk.END):
                    chat_listbox.insert(tk.END, cid)

        def remove_chat_id():
            sel = list(chat_listbox.curselection())
            for idx in reversed(sel):
                chat_listbox.delete(idx)

        ttk.Button(chat_btns, text="Add...", command=add_chat_id, width=10).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(chat_btns, text="Remove", command=remove_chat_id, width=10).pack(fill=tk.X)

        # Test message
        test_btn = ttk.Button(frame, text="Send Test Message", command=lambda: _send_test())
        test_btn.pack(anchor=tk.W, pady=(0, 10))

        status_var = tk.StringVar(value="")
        status_label = ttk.Label(frame, textvariable=status_var, foreground="gray")
        status_label.pack(anchor=tk.W)

        def _send_test():
            # Сохраняем текущие значения в конфиг перед тестом
            temp_cfg = {
                "enabled": enabled_var.get(),
                "bot_token": token_var.get().strip(),
                "chat_ids": list(chat_listbox.get(0, tk.END)),
            }
            error_notifier.save_config(temp_cfg)
            ok, msg = error_notifier.send_test_message()
            status_var.set(msg)
            status_label.config(foreground="green" if ok else "red")

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(15, 0))

        def on_ok():
            new_cfg = {
                "enabled": enabled_var.get(),
                "bot_token": token_var.get().strip(),
                "chat_ids": list(chat_listbox.get(0, tk.END)),
            }
            error_notifier.save_config(new_cfg)
            dialog.destroy()

        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy, width=10).pack(side=tk.RIGHT, padx=(0, 5))
        ttk.Button(btn_frame, text="OK", command=on_ok, width=10).pack(side=tk.RIGHT)

    def open_about(self):
        messagebox.showinfo("About", "Cloud Backup Tool\nVersion 3.0.0\n\nBackup utility for cloud storage")

    def _toggle_autorun_from_menu(self):
        self.set_autorun(self.prefs_autorun_var.get())

    def _toggle_start_minimized_from_menu(self):
        self.settings["global"]["start_minimized"] = self.prefs_start_min_var.get()
        self.save_config()

    def _toggle_log_to_file_from_menu(self):
        self.settings["global"]["log_to_file"] = self.prefs_log_file_var.get()
        self.save_config()

    def _apply_theme_from_menu(self):
        theme = self.prefs_theme_var.get()
        self.settings["global"]["theme"] = theme
        self._apply_theme(theme)
        self.save_config()

    def _apply_theme(self, theme):
        if theme not in ("light", "dark"):
            theme = "light"
        try:
            sv_ttk.set_theme(theme)
        except Exception as e:
            print(f"Failed to apply theme '{theme}': {e}")

    # =========================================================
    # ================= PROFILE STATUS / STATE ================
    # =========================================================
    def update_profile_status(self, profile_name, text=None, color=None):
        if profile_name != self.current_profile_name:
            return
        w = self.profile_widgets
        if "status_label" not in w:
            return
        if text is None:
            state = self.profile_state.get(profile_name, {})
            enabled = self.settings["profiles"].get(profile_name, {}).get("enabled", False)
            if state.get("running", False):
                text, color = "Running...", "orange"
            elif not enabled:
                text, color = "Disabled", "gray"
            else:
                text, color = "Idle (scheduled)", "blue"
        w["status_label"].config(text=text, foreground=color)

    def _set_profile_running(self, profile_name, running):
        state = self.profile_state.setdefault(profile_name, {"running": False, "thread": None, "stop_flag": False})
        state["running"] = running
        if profile_name == self.current_profile_name:
            w = self.profile_widgets
            if running:
                w["start_btn"].config(state=tk.DISABLED)
                w["stop_btn"].config(state=tk.NORMAL)
            else:
                w["start_btn"].config(state=tk.NORMAL)
                w["stop_btn"].config(state=tk.DISABLED)
        self.update_profile_status(profile_name)

    # =========================================================
    # ======================= LOGGING =========================
    # =========================================================
    def update_log(self, message, profile_name=None):
        """Логирует сообщение.
        Если profile_name задан — пишет в UI (если профиль активен) и в лог этого профиля.
        Если None — пишет в UI и во ВСЕ логи профилей (системные сообщения).
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        self.log_queue.put((log_line, profile_name))
        if self.settings["global"].get("log_to_file", False):
            self.profile_logger.log(message, profile_name)

    def _flush_log_ui(self):
        items = []
        try:
            while True:
                items.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        if items and hasattr(self, "log_display"):
            try:
                current = self.current_profile_name
                lines_to_add = []
                for line, pname in items:
                    # Показываем в UI, если:
                    # - это системное сообщение (pname is None), или
                    # - это сообщение для текущего активного профиля
                    if pname is None or pname == current:
                        lines_to_add.append(line)
                if lines_to_add:
                    self.log_display.insert(tk.END, "".join(lines_to_add))
                    self.log_display.see(tk.END)
            except tk.TclError:
                pass
        self.root.after(1000, self._flush_log_ui)

    def _refresh_log_display(self, profile_name):
        """Перечитывает лог указанного профиля в UI (при переключении профиля)."""
        if not hasattr(self, "log_display"):
            return
        try:
            self.log_display.delete(1.0, tk.END)
            lines = self.profile_logger.read_last_lines(profile_name, 10000)
            for line in lines:
                self.log_display.insert(tk.END, line)
            self.log_display.see(tk.END)
        except tk.TclError:
            pass

    # =========================================================
    # ====================== BACKUP ===========================
    # =========================================================
    def check_backup_dir_available(self, backup_dir):
        if not backup_dir:
            return False
        try:
            if not os.path.exists(backup_dir):
                return False
            if not os.path.isdir(backup_dir):
                return False
            if not os.access(backup_dir, os.W_OK):
                return False
            return True
        except Exception:
            return False

    def start_profile_backup(self, profile_name, show_dialog=True):
        state = self.profile_state.get(profile_name)
        if not state:
            return
        if state.get("running", False):
            self.update_log(f"Profile '{profile_name}': backup already running, skipping.",
                            profile_name=profile_name)
            return
        profile = self.settings["profiles"].get(profile_name, {})
        source_dirs = profile.get("source_dirs", [])
        backup_dir = profile.get("backup_dir", "")
        if not source_dirs:
            if show_dialog:
                messagebox.showerror("Error", f"No source directories specified in profile '{profile_name}'.")
            return
        if not backup_dir:
            if show_dialog:
                messagebox.showerror("Error", f"No backup directory specified in profile '{profile_name}'.")
            return
        if not self.check_backup_dir_available(backup_dir):
            error_msg = f"Target path is not available: '{backup_dir}'"
            error_type = "disk_unavailable"
            error_logger.log_error(profile_name, error_type, error_msg)
            self.update_log(f"{error_msg} (profile '{profile_name}'). Waiting for next cycle.",
                            profile_name=profile_name)
            try:
                error_notifier.send_pre_backup_alert(profile_name, error_type, error_msg)
            except Exception as e:
                self.update_log(f"Failed to send pre-backup alert: {e}", profile_name=profile_name)
            if show_dialog:
                messagebox.showwarning("Backup Skipped", f"{error_msg} (profile '{profile_name}').")
            return
        free_bytes = self._get_free_space(backup_dir)
        if free_bytes is not None and free_bytes < MIN_FREE_BYTES:
            free_gb = free_bytes / (1024 ** 3)
            error_msg = f"Low disk space on target: {free_gb:.2f} GB free"
            error_type = "low_disk_space"
            error_logger.log_error(profile_name, error_type, error_msg)
            if show_dialog:
                if not messagebox.askyesno("Low Disk Space",
                                           f"Only {free_gb:.2f} GB free on target disk.\nContinue backup?"):
                    try:
                        error_notifier.send_pre_backup_alert(profile_name, error_type, error_msg)
                    except Exception as e:
                        self.update_log(f"Failed to send pre-backup alert: {e}", profile_name=profile_name)
                    return
            else:
                self.update_log(f"{error_msg}. Skipping.", profile_name=profile_name)
                try:
                    error_notifier.send_pre_backup_alert(profile_name, error_type, error_msg)
                except Exception as e:
                    self.update_log(f"Failed to send pre-backup alert: {e}", profile_name=profile_name)
                return
        self.save_config()
        state["stop_flag"] = False
        self._set_profile_running(profile_name, True)
        self.update_log(f"=== Starting backup for profile '{profile_name}' ===",
                        profile_name=profile_name)
        t = threading.Thread(target=self.run_backup, args=(profile_name,), daemon=True)
        state["thread"] = t
        t.start()

    def stop_profile_backup(self, profile_name):
        state = self.profile_state.get(profile_name)
        if state:
            state["stop_flag"] = True
            self.update_log(f"Backup stopped by user for profile '{profile_name}'.",
                            profile_name=profile_name)
            self._set_profile_running(profile_name, False)

    def start_all_backups(self):
        started = 0
        for pname, profile in self.settings["profiles"].items():
            if profile.get("enabled", False):
                state = self.profile_state.get(pname, {})
                if not state.get("running", False):
                    self.start_profile_backup(pname, show_dialog=False)
                    started += 1
        self.update_log(f"Start All: launched {started} profile(s).")

    def stop_all_backups(self):
        stopped = 0
        for pname, state in self.profile_state.items():
            if state.get("running", False):
                self.stop_profile_backup(pname)
                stopped += 1
        self.update_log(f"Stop All: stopped {stopped} profile(s).")

    def run_backup(self, profile_name):
        state = self.profile_state.get(profile_name, {})
        profile = self.settings["profiles"].get(profile_name, {})
        source_dirs = profile.get("source_dirs", [])
        backup_dir = profile.get("backup_dir", "")
        skip_links = profile.get("skip_links", True)
        exclude_patterns_str = profile.get("exclude_patterns", "")
        retry_config = profile.get("retry", {})
        retry_enabled = retry_config.get("enabled", False)
        max_attempts = retry_config.get("max_attempts", 3) if retry_enabled else 1
        interval_seconds = retry_config.get("interval_seconds", 300)
        retry_on = retry_config.get("retry_on", [])
        on_total_failure = retry_config.get("on_total_failure", [])
        pc_config = profile.get("process_control", {})
        pc_enabled = pc_config.get("enabled", False)
        close_before = pc_config.get("close_before", [])
        close_mode = pc_config.get("close_mode", "graceful_then_force")
        graceful_timeout = pc_config.get("graceful_timeout_sec", 10)
        on_close_failure = pc_config.get("on_close_failure", "abort")
        restore_after = pc_config.get("restore_after", "only_if_was_running")
        total_timeout_minutes = profile.get("total_timeout_minutes", 0)

        # Сбор ошибок сеанса для отправки алерта
        session_errors = []
        # Флаги для определения outcome
        outcome = None  # "total_failure" | "success_after_retry" | "timeout" | None
        successful_attempt = None
        session_start_time = time.time()
        timeout_elapsed_minutes = None

        closed_processes = {}
        for attempt in range(1, max_attempts + 1):
            if state.get("stop_flag", False):
                self.update_log(f"[{profile_name}] Backup stopped by user.",
                                profile_name=profile_name)
                # При stop by user алерт НЕ отправляем
                break
            self.update_log(f"[{profile_name}] === Attempt {attempt}/{max_attempts} ===",
                            profile_name=profile_name)

            if pc_enabled and close_before:
                self.update_log(f"[{profile_name}] Closing processes before backup...",
                                profile_name=profile_name)
                for proc_name in close_before:
                    from process_manager import close_process
                    success, exe_path = close_process(proc_name, mode=close_mode, timeout=graceful_timeout)
                    if success:
                        if exe_path:
                            closed_processes[proc_name] = exe_path
                            self.update_log(f"[{profile_name}] Closed: {proc_name}",
                                            profile_name=profile_name)
                        else:
                            self.update_log(f"[{profile_name}] Already closed: {proc_name}",
                                            profile_name=profile_name)
                    else:
                        self.update_log(f"[{profile_name}] Failed to close: {proc_name}",
                                        profile_name=profile_name)
                        if on_close_failure == "abort":
                            error_msg = f"Failed to close process '{proc_name}'"
                            error_type = "process_close_failed"
                            error_logger.log_error(profile_name, error_type, error_msg, attempt, max_attempts)
                            # При process_close_failed с abort алерт НЕ отправляем
                            self.update_log(f"[{profile_name}] Aborting due to process close failure.",
                                            profile_name=profile_name)
                            if attempt == max_attempts or not retry_enabled:
                                self._execute_failure_actions(profile_name, on_total_failure)
                            self._restore_processes(profile_name, closed_processes, restore_after)
                            self.root.after(0, lambda pn=profile_name: self._set_profile_running(pn, False))
                            return
                        else:
                            self.update_log(f"[{profile_name}] Continuing despite process close failure.",
                                            profile_name=profile_name)

            start_time = time.time()
            total_stats = {"files_copied": 0, "files_skipped": 0, "total_size_mb": 0, "errors": 0}
            all_copied_files = []
            all_error_details = []
            timeout_exceeded = False
            try:
                for source_dir in source_dirs:
                    if state.get("stop_flag", False):
                        break
                    if total_timeout_minutes > 0:
                        elapsed_minutes = (time.time() - start_time) / 60
                        if elapsed_minutes >= total_timeout_minutes:
                            timeout_exceeded = True
                            self.update_log(f"[{profile_name}] Timeout exceeded ({total_timeout_minutes} minutes).",
                                            profile_name=profile_name)
                            break
                    stats = backup_saves(
                        source_dir, backup_dir, skip_links, exclude_patterns_str,
                        source_dirs, state,
                        log=lambda m: self.update_log(m, profile_name=profile_name),
                    )
                    for key in total_stats:
                        total_stats[key] += stats.get(key, 0)
                    all_error_details.extend(stats.get("error_details", []))
                    new_files = stats.get("copied_files", [])
                    if len(all_copied_files) < MAX_COPIED_LIST:
                        room = MAX_COPIED_LIST - len(all_copied_files)
                        all_copied_files.extend(new_files[:room])
                    total_stats["total_copied_count"] = total_stats.get("total_copied_count", 0) + len(new_files)

                    if total_timeout_minutes > 0:
                        elapsed_minutes = (time.time() - start_time) / 60
                        if elapsed_minutes >= total_timeout_minutes:
                            timeout_exceeded = True
                            self.update_log(f"[{profile_name}] Timeout exceeded ({total_timeout_minutes} minutes).",
                                            profile_name=profile_name)
                            break

                elapsed_time = time.time() - start_time
                speed = total_stats["total_size_mb"] / elapsed_time if elapsed_time > 0 else 0
                error_types = self._classify_backup_errors(
                    total_stats, timeout_exceeded, state.get("stop_flag", False),
                    backup_dir=backup_dir, source_dirs=source_dirs
                )

                if state.get("stop_flag", False):
                    self.update_log(f"[{profile_name}] Backup stopped.",
                                    profile_name=profile_name)
                    self._restore_processes(profile_name, closed_processes, restore_after)
                    self.root.after(0, lambda pn=profile_name: self._set_profile_running(pn, False))
                    # При stop by user алерт НЕ отправляем
                    return

                if error_types:
                    error_msg = ", ".join(error_types)
                    error_logger.log_error(
                        profile_name, error_types[0], error_msg,
                        attempt, max_attempts, details=all_error_details or None,
                    )
                    # Сохраняем ошибку в session_errors
                    session_errors.append({
                        "error_type": error_types[0],
                        "error_message": error_msg,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "details": list(all_error_details) if all_error_details else [],
                    })
                    self.update_log(f"[{profile_name}] Attempt {attempt}/{max_attempts} failed: {error_msg}",
                                    profile_name=profile_name)
                    should_retry = retry_enabled and any(et in retry_on for et in error_types)
                    if should_retry and attempt < max_attempts:
                        self.update_log(f"[{profile_name}] Waiting {interval_seconds} seconds before retry...",
                                        profile_name=profile_name)
                        for _ in range(interval_seconds):
                            if state.get("stop_flag", False):
                                break
                            time.sleep(1)
                        continue
                    else:
                        if attempt == max_attempts:
                            outcome = "total_failure"
                            self._execute_failure_actions(profile_name, on_total_failure)
                else:
                    msg = (f"[{profile_name}] Total files copied: {total_stats['files_copied']}\n"
                           f"Total files skipped: {total_stats['files_skipped']}\n"
                           f"Total size copied: {total_stats['total_size_mb']:.2f} MB\n"
                           f"Errors occurred: {total_stats['errors']}\n"
                           f"Time elapsed: {elapsed_time:.2f} seconds\n"
                           f"Average speed: {speed:.2f} MB/s")
                    self.update_log(msg, profile_name=profile_name)
                    total_count = total_stats.get("total_copied_count", total_stats["files_copied"])
                    if all_copied_files:
                        summary = f"\n=== Copied files ({total_count}) ===\n"
                        for f in all_copied_files:
                            summary += f"• {f}\n"
                        if total_count > len(all_copied_files):
                            summary += f"... and {total_count - len(all_copied_files)} more files (list truncated)\n"
                        self.update_log(summary, profile_name=profile_name)
                    else:
                        self.update_log(f"\n=== [{profile_name}] Copied files: none (all files are up to date) ===\n",
                                        profile_name=profile_name)
                    # Успешное завершение
                    if session_errors:
                        outcome = "success_after_retry"
                        successful_attempt = attempt
                    break

                # Если был timeout — прерываем цикл attempts
                if timeout_exceeded:
                    outcome = "timeout"
                    timeout_elapsed_minutes = (time.time() - session_start_time) / 60
                    break

            except Exception as e:
                error_msg = str(e)
                error_type = "copy_errors"
                error_logger.log_error(
                    profile_name, error_type, error_msg,
                    attempt, max_attempts, details=all_error_details or None,
                )
                session_errors.append({
                    "error_type": error_type,
                    "error_message": error_msg,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "details": list(all_error_details) if all_error_details else [],
                })
                self.update_log(f"[{profile_name}] Attempt {attempt}/{max_attempts} failed: {error_msg}",
                                profile_name=profile_name)
                should_retry = retry_enabled and error_type in retry_on
                if should_retry and attempt < max_attempts:
                    self.update_log(f"[{profile_name}] Waiting {interval_seconds} seconds before retry...",
                                    profile_name=profile_name)
                    for _ in range(interval_seconds):
                        if state.get("stop_flag", False):
                            break
                        time.sleep(1)
                    continue
                else:
                    outcome = "total_failure"

        self._restore_processes(profile_name, closed_processes, restore_after)

        # Отправка агрегированного алерта по итогам сеанса
        if session_errors and outcome and not state.get("stop_flag", False):
            try:
                error_notifier.send_session_alert(
                    profile_name=profile_name,
                    session_errors=session_errors,
                    outcome=outcome,
                    successful_attempt=successful_attempt,
                    total_timeout_minutes=total_timeout_minutes if outcome == "timeout" else None,
                    elapsed_minutes=timeout_elapsed_minutes if outcome == "timeout" else None,
                )
            except Exception as e:
                self.update_log(f"Failed to send session alert: {e}", profile_name=profile_name)

        self.root.after(0, lambda pn=profile_name: self._set_profile_running(pn, False))

    def _classify_backup_errors(self, total_stats, timeout_exceeded, stop_flag, 
                                backup_dir=None, source_dirs=None):
        error_types = []
        if timeout_exceeded:
            error_types.append("timeout_exceeded")
        
        if total_stats.get("errors", 0) > 0:
            error_types.append("copy_errors")
        
        # Проверка доступности диска
        if backup_dir and not self.check_backup_dir_available(backup_dir):
            error_types.append("disk_unavailable")
        
        # Проверка свободного места
        if backup_dir:
            free_bytes = self._get_free_space(backup_dir)
            if free_bytes is not None and free_bytes < MIN_FREE_BYTES:
                error_types.append("low_disk_space")
        
        # Проверка доступности источников
        if source_dirs:
            for src in source_dirs:
                if not os.path.exists(src):
                    error_types.append("source_missing")
                    break
        
        return error_types

    def _restore_processes(self, profile_name, closed_processes, restore_after):
        if restore_after == "never":
            return
        if not closed_processes:
            return
        self.update_log(f"[{profile_name}] Restoring processes...",
                        profile_name=profile_name)
        from process_manager import start_process
        for proc_name, exe_path in closed_processes.items():
            if restore_after == "only_if_was_running" or restore_after == "always":
                if start_process(exe_path):
                    self.update_log(f"[{profile_name}] Restored: {proc_name}",
                                    profile_name=profile_name)
                else:
                    self.update_log(f"[{profile_name}] Failed to restore: {proc_name}",
                                    profile_name=profile_name)

    def _execute_failure_actions(self, profile_name, actions):
        if not actions:
            return
        self.update_log(f"[{profile_name}] Executing failure actions...",
                        profile_name=profile_name)
        for action in actions:
            action_type = action.get("action")
            if action_type == "run_script":
                script_path = action.get("script_path", "")
                log_output = action.get("log_output", True)
                if script_path:
                    self._run_failure_script(profile_name, script_path, log_output)
            elif action_type == "show_message":
                message = action.get("message", "Backup failed")
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                message = message.replace("{profile_name}", profile_name)
                message = message.replace("{timestamp}", timestamp)
                self._show_failure_message(profile_name, message)

    def _run_failure_script(self, profile_name, script_path, log_output):
        import subprocess
        try:
            result = subprocess.run([script_path], capture_output=log_output, text=True, timeout=60)
            if log_output:
                if result.stdout:
                    self.update_log(f"[{profile_name}] Script output:\n{result.stdout}",
                                    profile_name=profile_name)
                if result.stderr:
                    self.update_log(f"[{profile_name}] Script errors:\n{result.stderr}",
                                    profile_name=profile_name)
        except Exception as e:
            self.update_log(f"[{profile_name}] Failed to run script '{script_path}': {e}",
                            profile_name=profile_name)

    def _show_failure_message(self, profile_name, message):
        if not hasattr(self, '_failure_message_windows'):
            self._failure_message_windows = {}
        if profile_name in self._failure_message_windows:
            window = self._failure_message_windows[profile_name]
            if window.winfo_exists():
                window.text.delete(1.0, tk.END)
                window.text.insert(tk.END, message)
                return
        window = tk.Toplevel(self.root)
        window.title(f"Backup Failed - {profile_name}")
        
        # Центрирование относительно главного окна
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_width = self.root.winfo_width()
        main_height = self.root.winfo_height()
        x = main_x + (main_width - 500) // 2
        y = main_y + (main_height - 300) // 2
        window.geometry(f"500x300+{x}+{y}")
        
        window.minsize(500, 300)
        window.transient(self.root)
        window.attributes('-toolwindow', True)
        text = scrolledtext.ScrolledText(window, wrap=tk.WORD, font=("Arial", 10))
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text.insert(tk.END, message)
        text.config(state=tk.DISABLED)
        window.text = text
        self._failure_message_windows[profile_name] = window

        def on_close():
            if profile_name in self._failure_message_windows:
                del self._failure_message_windows[profile_name]
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", on_close)

    # =========================================================
    # ===================== AUTORUN ===========================
    # =========================================================
    def toggle_autorun(self):
        if self.check_autorun():
            self.set_autorun(False)
        else:
            self.set_autorun(True)

    def set_autorun(self, enable):
        key = reg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with reg.OpenKey(key, key_path, 0, reg.KEY_ALL_ACCESS) as registry_key:
                if enable:
                    exe_path = (sys.executable if getattr(sys, "frozen", False)
                                else os.path.abspath(__file__))
                    reg.SetValueEx(registry_key, "CloudBackupTool", 0, reg.REG_SZ, f'"{exe_path}"')
                else:
                    reg.DeleteValue(registry_key, "CloudBackupTool")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to modify autorun: {str(e)}")

    def check_autorun(self):
        key = reg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with reg.OpenKey(key, key_path, 0, reg.KEY_READ) as registry_key:
                try:
                    reg.QueryValueEx(registry_key, "CloudBackupTool")
                    return True
                except FileNotFoundError:
                    return False
        except Exception:
            return False

    # =========================================================
    # ==================== SCHEDULER ==========================
    # =========================================================
    def setup_schedule(self):
        self.sched_stop.set()
        if self.sched_thread and self.sched_thread.is_alive():
            self.sched_thread.join(timeout=2)
            if self.sched_thread.is_alive():
                self.update_log("[WARNING] Scheduler thread did not stop in 2s, continuing anyway")
        self.sched_stop.clear()
        with self.schedule_lock:
            schedule.clear()
        for profile_name, profile in self.settings["profiles"].items():
            if not profile.get("enabled", False):
                continue
            sched = profile.get("backup_schedule", "None")
            if sched == "None":
                continue
            try:
                self._register_schedule(profile_name, profile)
            except Exception as e:
                self.update_log(f"Error registering schedule for '{profile_name}': {e}",
                                profile_name=profile_name)
        self.sched_thread = threading.Thread(target=self.run_scheduler, daemon=True)
        self.sched_thread.start()

    def _update_custom_time_hint(self):
        w = self.profile_widgets
        if not self.current_profile_name:
            return
        profile = self.settings["profiles"].get(self.current_profile_name, {})
        sched = profile.get("backup_schedule")
        if sched == "Custom" and "custom_hint_label" in w:
            custom = profile.get("custom_time", "")
            ok, err = validate_custom_time(custom)
            if ok:
                w["custom_hint_label"].config(
                    text="Examples: 21:30 (daily at 21:30), 120 (every 120 minutes)", fg="gray")
            else:
                w["custom_hint_label"].config(text=err, fg="red")
        elif sched == "Weekly" and "weekly_hint_label" in w:
            weekly_time = profile.get("weekly_time", "")
            weekly_days = profile.get("weekly_days", [])
            if not weekly_days:
                w["weekly_hint_label"].config(text="Select at least one day", fg="red")
                return
            ok, err = validate_hhmm(weekly_time)
            if ok:
                w["weekly_hint_label"].config(text="Time format: HH:MM (e.g., 23:00)", fg="gray")
            else:
                w["weekly_hint_label"].config(text=err, fg="red")

    def _register_schedule(self, profile_name, profile):
        sched = profile.get("backup_schedule", "None")
        if sched.startswith("Daily"):
            parts = sched.split()
            if len(parts) >= 2:
                time_str = parts[1]
                schedule.every().day.at(time_str).do(self.scheduled_backup, profile_name)
                self.update_log(f"Schedule (profile '{profile_name}'): daily at {time_str}",
                                profile_name=profile_name)
            else:
                self.update_log(f"Error: invalid schedule format for '{profile_name}': '{sched}'",
                                profile_name=profile_name)
        elif sched == "Custom":
            custom = profile.get("custom_time", "")
            ok, err = validate_custom_time(custom)
            if not ok:
                self.update_log(f"Error: {err} for '{profile_name}': '{custom}'",
                                profile_name=profile_name)
            elif ":" in custom:
                schedule.every().day.at(custom).do(self.scheduled_backup, profile_name)
                self.update_log(f"Schedule (profile '{profile_name}'): daily at {custom}",
                                profile_name=profile_name)
            else:
                schedule.every(int(custom)).minutes.do(self.scheduled_backup, profile_name)
                self.update_log(f"Schedule (profile '{profile_name}'): every {custom} minutes",
                                profile_name=profile_name)
        elif sched == "Weekly":
            weekly_days = profile.get("weekly_days", [])
            weekly_time = profile.get("weekly_time", "")
            if not weekly_days:
                self.update_log(f"Error: no days selected for weekly schedule for '{profile_name}'",
                                profile_name=profile_name)
                return
            ok, err = validate_hhmm(weekly_time)
            if not ok:
                self.update_log(f"Error: {err} for '{profile_name}': '{weekly_time}'",
                                profile_name=profile_name)
                return
            for day in weekly_days:
                getattr(schedule.every(), day.lower()).at(weekly_time).do(self.scheduled_backup, profile_name)
            days_str = ", ".join(weekly_days)
            self.update_log(f"Schedule (profile '{profile_name}'): weekly on {days_str} at {weekly_time}",
                            profile_name=profile_name)

    def run_scheduler(self):
        try:
            while not self.sched_stop.is_set():
                with self.schedule_lock:
                    schedule.run_pending()
                time.sleep(1)
        except Exception as e:
            self.update_log(f"Scheduler thread error: {e}")

    def scheduled_backup(self, profile_name):
        self.root.after(0, self._try_start_scheduled_backup, profile_name)

    def _try_start_scheduled_backup(self, profile_name):
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        profile = self.settings["profiles"].get(profile_name, {})
        if not profile.get("enabled", False):
            return
        state = self.profile_state.get(profile_name, {})
        if state.get("running", False):
            self.update_log(f"[{profile_name}] Scheduled backup skipped: already running.",
                            profile_name=profile_name)
            return
        self.start_profile_backup(profile_name, show_dialog=False)

    # =========================================================
    # ====================== CONFIG ===========================
    # =========================================================
    def save_config(self):
        active = self.current_profile_name or self.settings["global"].get("active_profile", "Default")
        if active in self.settings["profiles"] and active == self.current_profile_name:
            self._sync_profile_widgets_to_settings(active)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=1)

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Failed to load config: {e}")
            return

        if "profiles" not in data and "source_dirs" in data:
            legacy_profile = {
                "source_dirs": data.get("source_dirs", []),
                "backup_dir": data.get("backup_dir", ""),
                "skip_links": data.get("skip_links", True),
                "backup_schedule": data.get("backup_schedule", "None"),
                "custom_time": data.get("custom_time", ""),
                "exclude_patterns": data.get("exclude_patterns", ""),
                "enabled": data.get("auto_start_backup", False),
                "auto_start_backup": data.get("auto_start_backup", False),
                "weekly_days": ["Monday"],
                "weekly_time": "23:00",
            }
            self.settings = {
                "global": {
                    "autorun": False,
                    "start_minimized": False,
                    "log_to_file": True,
                    "active_profile": "Default",
                    "theme": "light",
                },
                "profiles": {"Default": legacy_profile},
            }
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, ensure_ascii=False, indent=1)
            except Exception:
                pass
            return

        if "global" in data:
            self.settings["global"].update(data["global"])
        if "theme" not in self.settings["global"]:
            self.settings["global"]["theme"] = "light"
        if "profiles" in data:
            self.settings["profiles"] = data["profiles"]
            for pname, pdata in self.settings["profiles"].items():
                if "enabled" not in pdata:
                    pdata["enabled"] = pdata.get("auto_start_backup", False)
                if "weekly_days" not in pdata:
                    pdata["weekly_days"] = ["Monday"]
                if "weekly_time" not in pdata:
                    pdata["weekly_time"] = "23:00"
            if "Default" not in self.settings["profiles"]:
                self.settings["profiles"]["Default"] = {
                    "source_dirs": [], "backup_dir": "", "skip_links": True,
                    "backup_schedule": "None", "custom_time": "", "exclude_patterns": "",
                    "enabled": False, "auto_start_backup": False,
                    "weekly_days": ["Monday"], "weekly_time": "23:00",
                }
            for pname, pdata in self.settings["profiles"].items():
                if "process_control" not in pdata:
                    pdata["process_control"] = {
                        "enabled": False, "close_before": [],
                        "close_mode": "graceful_then_force", "graceful_timeout_sec": 10,
                        "on_close_failure": "abort", "restore_after": "only_if_was_running"
                    }
                if "retry" not in pdata:
                    pdata["retry"] = {
                        "enabled": False, "max_attempts": 3, "interval_seconds": 300,
                        "retry_on": ["disk_unavailable", "process_close_failed", "copy_errors"],
                        "on_total_failure": []
                    }
                if "total_timeout_minutes" not in pdata:
                    pdata["total_timeout_minutes"] = 0

        if "errors_last_read_pos" not in self.settings["global"]:
            self.settings["global"]["errors_last_read_pos"] = 0

    # =========================================================
    # ==================== TRAY ICON ==========================
    # =========================================================
    def create_tray_menu(self):
        return pystray.Menu(
            pystray.MenuItem("Open Window", self.show_window, default=True),
            pystray.MenuItem("Minimize to Tray", self.hide_window),
            pystray.MenuItem("Run at Windows startup", self.toggle_autorun_from_tray,
                             checked=lambda item: self.check_autorun()),
            pystray.MenuItem("Exit", self.exit_app),
        )

    def create_tray_icon(self):
        icon_path_ico = os.path.join(BASE_DIR, "backup.ico")
        icon_path_png = os.path.join(BASE_DIR, "backup.png")
        image = None
        try:
            if os.path.exists(icon_path_ico):
                image = Image.open(icon_path_ico)
            elif os.path.exists(icon_path_png):
                image = Image.open(icon_path_png)
        except Exception as e:
            print(f"Failed to load tray icon: {e}")
        if image is None:
            image = Image.new("RGB", (16, 16), color="white")
        self.tray_icon = pystray.Icon("CloudBackupTool", image, "Cloud Backup Tool", self.create_tray_menu())
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def update_tray_menu(self):
        if hasattr(self, "tray_icon") and self.tray_icon:
            try:
                self.tray_icon.update_menu()
            except Exception:
                pass

    def hide_window(self, *args):
        self.root.withdraw()

    def show_window(self, *args):
        self.root.after(0, self._restore_window)

    def _restore_window(self):
        self.root.deiconify()
        self.root.state('normal')
        self.root.lift()
        self.root.focus_force()

    def exit_app(self, *args):
        if hasattr(self, "sched_stop"):
            self.sched_stop.set()
        self.root.after(0, self._shutdown)

    def _shutdown(self):
        log_exit_or_crash("Normal shutdown initiated by user (exit_app called)")
        if hasattr(self, "profile_logger"):
            try:
                self.profile_logger.close_all()
            except Exception:
                pass
        if hasattr(self, "tray_icon") and self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    def toggle_autorun_from_tray(self, icon, item):
        if self.check_autorun():
            self.set_autorun(False)
        else:
            self.set_autorun(True)

    # =========================================================
    # ================= ERROR INDICATOR =======================
    # =========================================================
    def _update_error_indicator(self):
        last_pos = self.settings["global"].get("errors_last_read_pos", 0)
        new_errors, new_pos = error_logger.get_new_errors(last_pos)
        if new_errors:
            count = len(new_errors)
            self.error_indicator.config(text=f"⚠ [{count} error{'s' if count != 1 else ''}]")
        else:
            self.error_indicator.config(text="")
        self.root.after(5000, self._update_error_indicator)

    def _open_error_summary(self):
        if hasattr(self, '_error_summary_window') and self._error_summary_window.winfo_exists():
            self._error_summary_window.lift()
            self._error_summary_window.focus_force()
            return
        window = tk.Toplevel(self.root)
        window.title("Error Summary")
        
        # Правый верхний угол экрана с отступом 50px
        screen_width = window.winfo_screenwidth()
        x = screen_width - 700 - 50
        y = 50
        window.geometry(f"700x500+{x}+{y}")
        
        window.minsize(700, 500)
        window.transient(self.root)
        window.attributes('-toolwindow', True)
        text = scrolledtext.ScrolledText(window, wrap=tk.WORD, font=("Consolas", 9))
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        errors = error_logger.get_last_n_errors(50)
        if errors:
            for err in errors:
                text.insert(tk.END, err + "\n")
        else:
            text.insert(tk.END, "No errors recorded.")
        text.config(state=tk.DISABLED)
        btn_frame = ttk.Frame(window)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        def open_full_log():
            import subprocess
            log_path = error_logger.errors_log_file
            if os.path.exists(log_path):
                subprocess.Popen(["notepad.exe", log_path])

        ttk.Button(btn_frame, text="Open full log", command=open_full_log).pack(side=tk.RIGHT)
        self._error_summary_window = window
        self.error_indicator.config(text="")
        self.settings["global"]["errors_last_read_pos"] = error_logger.get_file_size()
        self.save_config()

    # =========================================================
    # ====================== UTILS ============================
    # =========================================================
    def _get_free_space(self, path):
        try:
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(path), None, None, ctypes.pointer(free_bytes))
            return free_bytes.value
        except Exception:
            return None


def _tk_exception_handler(exc_type, exc_value, exc_traceback):
    log_exit_or_crash("Unhandled Tkinter exception", (exc_type, exc_value, exc_traceback))


if __name__ == "__main__":
    root = tk.Tk()
    root.report_callback_exception = _tk_exception_handler
    app = BackupApp(root)
    root.mainloop()