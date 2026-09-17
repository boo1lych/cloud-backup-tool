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
import logging
from logging.handlers import RotatingFileHandler
import sys
import sv_ttk
import traceback
import atexit
import queue
from backup_logic import validate_custom_time, validate_hhmm, backup_saves, is_reparse_point

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
LOG_FILE = os.path.join(LOG_DIR, "backup.log")
CRASH_LOG_FILE = os.path.join(LOG_DIR, "crash_exit.log")

os.makedirs(LOG_DIR, exist_ok=True)

def log_exit_or_crash(reason, exc_info=None):
    """Логирует причины завершения работы или краха приложения."""
    msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CRITICAL] {reason}"
    if exc_info:
        msg += "\n" + " ".join(traceback.format_exception(*exc_info))
    msg += "\n" + "-" * 50 + "\n"
    try:
        with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        pass

def _global_exception_handler(exc_type, exc_value, exc_traceback):
    log_exit_or_crash("Unhandled exception in main thread", (exc_type, exc_value, exc_traceback))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

def _thread_exception_handler(args):
    thread_name = args.thread.name if args.thread else "Unknown"
    log_exit_or_crash(f"Unhandled exception in thread '{thread_name}'", (args.exc_type, args.exc_value, args.exc_traceback))

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
        sv_ttk.set_theme("light")
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

        # Состояние каждого профиля (запущен ли бэкап, поток, флаг остановки)
        self.profile_state = {}  # {profile_name: {"running": bool, "thread": Thread, "stop_flag": bool}}

        self.load_config()

        # Инициализируем состояние для всех профилей
        for pname in self.settings["profiles"]:
            self.profile_state[pname] = {"running": False, "thread": None, "stop_flag": False}

        # --- Ротируемый логгер ---
        self.logger = logging.getLogger("CloudBackupTool")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            rotating_handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            formatter = logging.Formatter(
                "[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
            rotating_handler.setFormatter(formatter)
            self.logger.addHandler(rotating_handler)

        self.sched_stop = threading.Event()
        self.sched_thread = None
        self.schedule_lock = threading.Lock()
        self.profile_tabs = {}
        self.profile_widgets = {}
        self.log_queue = queue.Queue()

        self.create_widgets()
        self.root.after(1000, self._flush_log_ui)
        self.create_tray_icon()

        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        active = self.settings["global"].get("active_profile", "Default")
        if active in self.profile_tabs:
            self.notebook.select(self.profile_tabs[active])

        self.setup_schedule()

        if self.settings["global"].get("start_minimized", False):
            self.hide_window()
        else:
            self.root.deiconify()

        # Автостарт: запускаем бэкап для профилей с enabled=True и auto_start_backup=True
        self.root.after(500, self._auto_start_on_launch)

    def _auto_start_on_launch(self):
        for pname, profile in self.settings["profiles"].items():
            if profile.get("enabled", False) and profile.get("auto_start_backup", False):
                self.start_profile_backup(pname, show_dialog=False)

    # =========================================================
    # ===================== UI CREATION =======================
    # =========================================================

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === Глобальная панель управления (самый верх) ===
        global_control = ttk.LabelFrame(main_frame, text="Global Control", padding=10)
        global_control.pack(fill=tk.X, pady=(0, 10))
        gbtn_frame = ttk.Frame(global_control)
        gbtn_frame.pack(fill=tk.X)
        ttk.Button(gbtn_frame, text="► Start All",
                   command=self.start_all_backups, width=15).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(gbtn_frame, text="■ Stop All",
                   command=self.stop_all_backups, width=15).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(gbtn_frame, text="✕ Exit",
                   command=self.exit_app, width=15).pack(side=tk.LEFT)

        # === Панель управления профилями ===
        profiles_toolbar = ttk.Frame(main_frame)
        profiles_toolbar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(profiles_toolbar, text="New Profile",
                   command=self.new_profile, width=15).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(profiles_toolbar, text="Rename",
                   command=self.rename_profile, width=15).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(profiles_toolbar, text="Duplicate",
                   command=self.duplicate_profile, width=15).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(profiles_toolbar, text="Delete",
                command=self.delete_profile, width=15).pack(side=tk.RIGHT)

        # === Notebook (вкладки профилей) ===
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        for profile_name in self.settings["profiles"].keys():
            self._create_profile_tab(profile_name)

        # === Глобальные настройки ===
        global_frame = ttk.LabelFrame(main_frame, text="Global Settings", padding=10)
        global_frame.pack(fill=tk.X, pady=(0, 10))
        self.log_to_file_var = tk.BooleanVar(
            value=self.settings["global"].get("log_to_file", True)
        )
        ttk.Checkbutton(global_frame, text="Save log to file",
                        variable=self.log_to_file_var,
                        command=self.toggle_log_to_file).pack(side=tk.LEFT, padx=(0, 15))
        self.autorun_var = tk.BooleanVar(value=self.check_autorun())
        ttk.Checkbutton(global_frame, text="Run at Windows startup",
                        variable=self.autorun_var,
                        command=self.toggle_autorun).pack(side=tk.LEFT, padx=(0, 15))
        self.start_minimized_var = tk.BooleanVar(
            value=self.settings["global"].get("start_minimized", False)
        )
        ttk.Checkbutton(global_frame, text="Start minimized",
                        variable=self.start_minimized_var,
                        command=self.toggle_start_minimized).pack(side=tk.LEFT)

        # === Log ===
        log_frame = ttk.LabelFrame(main_frame, text="Backup Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_display = scrolledtext.ScrolledText(
            log_frame, height=8, width=90, font=("Consolas", 9)
        )
        self.log_display.pack(fill=tk.BOTH, expand=True)

    def _create_profile_tab(self, profile_name):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text=profile_name)
        self.profile_tabs[profile_name] = tab

        profile_data = self.settings["profiles"][profile_name]
        widgets = {}

        # === Панель управления профилем (switch + кнопки + статус) ===
        ctrl_frame = ttk.LabelFrame(tab, text="Profile Control", padding=10)
        ctrl_frame.pack(fill=tk.X, pady=(0, 10))
        ctrl_inner = ttk.Frame(ctrl_frame)
        ctrl_inner.pack(fill=tk.X)

        # Switch (Enabled)
        widgets["enabled_var"] = tk.BooleanVar(value=profile_data.get("enabled", False))
        ttk.Checkbutton(ctrl_inner, text="Enabled",
                        variable=widgets["enabled_var"],
                        command=lambda pn=profile_name: self.on_profile_enabled_changed(pn)
                        ).pack(side=tk.LEFT, padx=(0, 20))

        # Кнопки Start/Stop профиля
        widgets["start_btn"] = ttk.Button(ctrl_inner, text="► Start",
                                          command=lambda pn=profile_name: self.start_profile_backup(pn),
                                          width=12)
        widgets["start_btn"].pack(side=tk.LEFT, padx=(0, 5))
        widgets["stop_btn"] = ttk.Button(ctrl_inner, text="■ Stop",
                                         command=lambda pn=profile_name: self.stop_profile_backup(pn),
                                         width=12, state=tk.DISABLED)
        widgets["stop_btn"].pack(side=tk.LEFT, padx=(0, 20))

        # Статус профиля
        widgets["status_label"] = ttk.Label(ctrl_inner, text="Idle", foreground="gray")
        widgets["status_label"].pack(side=tk.LEFT)

        # === Source Directories ===
        source_frame = ttk.LabelFrame(tab, text="Source Directories", padding=10)
        source_frame.pack(fill=tk.X, pady=(0, 10))
        widgets["source_listbox"] = tk.Listbox(
            source_frame, selectmode=tk.EXTENDED, height=4, width=80
        )
        widgets["source_listbox"].pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        for path in profile_data.get("source_dirs", []):
            widgets["source_listbox"].insert(tk.END, path)
        source_btns = ttk.Frame(source_frame)
        source_btns.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Button(source_btns, text="Add...",
                   command=lambda pn=profile_name: self.add_source(pn),
                   width=12).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(source_btns, text="Remove",
                   command=lambda pn=profile_name: self.remove_source(pn),
                   width=12).pack(fill=tk.X)

        # === Backup Destination ===
        dest_frame = ttk.LabelFrame(tab, text="Backup Destination", padding=10)
        dest_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(dest_frame, text="Directory:").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 10)
        )
        widgets["backup_entry"] = ttk.Entry(dest_frame, width=60)
        widgets["backup_entry"].insert(0, profile_data.get("backup_dir", ""))
        widgets["backup_entry"].grid(row=0, column=1, padx=(0, 10), sticky=tk.EW)
        ttk.Button(dest_frame, text="Browse...",
                   command=lambda pn=profile_name: self.browse_backup(pn)).grid(row=0, column=2)
        dest_frame.columnconfigure(1, weight=1)

        # === Profile Settings ===
        settings_frame = ttk.LabelFrame(tab, text="Profile Settings", padding=10)
        settings_frame.pack(fill=tk.X, pady=(0, 10))
        left_col = ttk.Frame(settings_frame)
        left_col.grid(row=0, column=0, sticky=tk.NW, padx=(0, 20))

        widgets["skip_links_var"] = tk.BooleanVar(
            value=profile_data.get("skip_links", True)
        )
        ttk.Checkbutton(left_col, text="Skip symbolic links/junctions",
                        variable=widgets["skip_links_var"],
                        command=lambda pn=profile_name: self.save_profile_settings(pn)
                        ).pack(anchor=tk.W, pady=2)

        widgets["auto_start_backup_var"] = tk.BooleanVar(
            value=profile_data.get("auto_start_backup", False)
        )
        ttk.Checkbutton(left_col, text="Run backup immediately on app start",
                        variable=widgets["auto_start_backup_var"],
                        command=lambda pn=profile_name: self.save_profile_settings(pn)
                        ).pack(anchor=tk.W, pady=2)

        right_col = ttk.Frame(settings_frame)
        right_col.grid(row=0, column=1, sticky=tk.NW)

        ttk.Label(right_col, text="Backup Schedule:").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 5)
        )
        widgets["schedule_var"] = tk.StringVar(
            value=profile_data.get("backup_schedule", "None")
        )
        widgets["schedule_menu"] = ttk.Combobox(
            right_col, textvariable=widgets["schedule_var"],
            values=["None", "Daily 23:00", "Daily 18:00", "Daily 10:00", "Custom", "Weekly"],
            state="readonly", width=15
        )
        widgets["schedule_menu"].grid(row=0, column=1, padx=(0, 10))
        widgets["schedule_menu"].bind(
            "<<ComboboxSelected>>",
            lambda e, pn=profile_name: self.schedule_changed(pn)
        )

        widgets["custom_time_entry"] = ttk.Entry(right_col, width=10)
        widgets["custom_time_entry"].insert(0, profile_data.get("custom_time", ""))
        widgets["custom_time_entry"].grid(row=0, column=2, padx=(0, 10))
        widgets["custom_time_entry"].bind(
            "<FocusOut>", lambda e, pn=profile_name: self.on_custom_time_changed(pn)
        )
        widgets["custom_time_entry"].bind(
            "<Return>", lambda e, pn=profile_name: self.on_custom_time_changed(pn)
        )
        if profile_data.get("backup_schedule") != "Custom":
            widgets["custom_time_entry"].grid_remove()

        widgets["weekly_time_entry"] = ttk.Entry(right_col, width=10)
        widgets["weekly_time_entry"].insert(0, profile_data.get("weekly_time", "23:00"))
        widgets["weekly_time_entry"].grid(row=0, column=2, padx=(0, 10))
        widgets["weekly_time_entry"].bind(
            "<FocusOut>", lambda e, pn=profile_name: self.on_weekly_settings_changed(pn)
        )
        widgets["weekly_time_entry"].bind(
            "<Return>", lambda e, pn=profile_name: self.on_weekly_settings_changed(pn)
        )
        if profile_data.get("backup_schedule") != "Weekly":
            widgets["weekly_time_entry"].grid_remove()

        widgets["custom_hint_label"] = tk.Label(
            right_col,
            text="Examples: 21:30 (daily at 21:30), 120 (every 120 minutes)",
            fg="gray"
        )
        widgets["custom_hint_label"].grid(row=1, column=1, columnspan=2,
                                        sticky=tk.W, pady=(0, 5))
        if profile_data.get("backup_schedule") != "Custom":
            widgets["custom_hint_label"].grid_remove()

        widgets["weekly_hint_label"] = tk.Label(
            right_col,
            text="Time format: HH:MM (e.g., 23:00)",
            fg="gray"
        )
        widgets["weekly_hint_label"].grid(row=1, column=1, columnspan=2,
                                        sticky=tk.W, pady=(0, 5))
        if profile_data.get("backup_schedule") != "Weekly":
            widgets["weekly_hint_label"].grid_remove()

        widgets["weekly_days_frame"] = ttk.Frame(right_col)
        widgets["weekly_days_frame"].grid(row=2, column=0, columnspan=3,
                                        sticky=tk.W, pady=(0, 5))
        widgets["weekly_day_vars"] = {}
        selected_days = profile_data.get("weekly_days", ["Monday"])
        for day in WEEK_DAYS:
            var = tk.BooleanVar(value=day in selected_days)
            widgets["weekly_day_vars"][day] = var
            ttk.Checkbutton(
                widgets["weekly_days_frame"],
                text=day[:3],
                variable=var,
                command=lambda pn=profile_name: self.on_weekly_settings_changed(pn)
            ).pack(side=tk.LEFT, padx=(0, 5))
        if profile_data.get("backup_schedule") != "Weekly":
            widgets["weekly_days_frame"].grid_remove()

        ttk.Label(right_col, text="Exclude patterns (comma-separated):").grid(
            row=3, column=0, sticky=tk.W, pady=(10, 0)
        )
        widgets["exclude_entry"] = ttk.Entry(right_col, width=40)
        widgets["exclude_entry"].insert(0, profile_data.get("exclude_patterns", ""))
        widgets["exclude_entry"].grid(row=3, column=1, columnspan=2,
                                    sticky=tk.EW, pady=(10, 0))
        widgets["exclude_hint_label"] = tk.Label(
            right_col, text="Masks: *$*.txt, ~$, *.tmp, logs/*", fg="gray"
        )
        widgets["exclude_hint_label"].grid(row=4, column=1, columnspan=2,
                                            sticky=tk.W, pady=(0, 5))

        self.profile_widgets[profile_name] = widgets
        self.update_profile_status(profile_name)
        self._update_custom_time_hint(profile_name)

    # =========================================================
    # ================= PROFILE STATUS / STATE ================
    # =========================================================

    def update_profile_status(self, profile_name, text=None, color=None):
        """Обновляет статус профиля в его вкладке."""
        w = self.profile_widgets.get(profile_name)
        if not w or "status_label" not in w:
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
        state = self.profile_state.setdefault(
            profile_name, {"running": False, "thread": None, "stop_flag": False}
        )
        state["running"] = running
        w = self.profile_widgets.get(profile_name)
        if w:
            if running:
                w["start_btn"].config(state=tk.DISABLED)
                w["stop_btn"].config(state=tk.NORMAL)
            else:
                w["start_btn"].config(state=tk.NORMAL)
                w["stop_btn"].config(state=tk.DISABLED)
        self.update_profile_status(profile_name)

    # =========================================================
    # ==================== PROFILE MANAGEMENT =================
    # =========================================================

    def get_active_profile_name(self):
        try:
            tab_id = self.notebook.select()
            for name, tab in self.profile_tabs.items():
                if str(tab) == tab_id:
                    return name
        except Exception:
            pass
        return self.settings["global"].get("active_profile", "Default")

    def on_tab_changed(self, event=None):
        prev_active = self.settings["global"].get("active_profile")
        if prev_active and prev_active in self.profile_widgets:
            self.save_profile_settings(prev_active)
        new_active = self.get_active_profile_name()
        self.settings["global"]["active_profile"] = new_active
        self.save_config()

    def new_profile(self):
        name = simpledialog.askstring(
            "New Profile", "Enter profile name:", parent=self.root
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self.settings["profiles"]:
            messagebox.showerror("Error", f"Profile '{name}' already exists.")
            return
        self.settings["profiles"][name] = {
            "source_dirs": [],
            "backup_dir": "",
            "skip_links": True,
            "backup_schedule": "None",
            "custom_time": "",
            "exclude_patterns": "",
            "enabled": False,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
        }
        self.profile_state[name] = {"running": False, "thread": None, "stop_flag": False}
        self._create_profile_tab(name)
        self.notebook.select(self.profile_tabs[name])
        self.save_config()
        self.setup_schedule()

    def rename_profile(self):
        old_name = self.get_active_profile_name()
        if old_name == "Default":
            messagebox.showwarning("Warning", "The 'Default' profile cannot be renamed.")
            return
        new_name = simpledialog.askstring(
            "Rename Profile",
            f"Enter new name for '{old_name}':",
            parent=self.root,
            initialvalue=old_name,
        )
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        if new_name in self.settings["profiles"]:
            messagebox.showerror("Error", f"Profile '{new_name}' already exists.")
            return
        self.settings["profiles"][new_name] = self.settings["profiles"].pop(old_name)
        self.profile_state[new_name] = self.profile_state.pop(old_name)
        old_tab = self.profile_tabs.pop(old_name)
        self.notebook.forget(old_tab)
        old_tab.destroy()
        del self.profile_widgets[old_name]
        self._create_profile_tab(new_name)
        self.notebook.select(self.profile_tabs[new_name])
        if self.settings["global"].get("active_profile") == old_name:
            self.settings["global"]["active_profile"] = new_name
        self.save_config()
        self.setup_schedule()

    def duplicate_profile(self):
        src_name = self.get_active_profile_name()
        new_name = simpledialog.askstring(
            "Duplicate Profile",
            f"Enter name for copy of '{src_name}':",
            parent=self.root,
            initialvalue=f"{src_name} (copy)",
        )
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        if new_name in self.settings["profiles"]:
            messagebox.showerror("Error", f"Profile '{new_name}' already exists.")
            return
        import copy
        self.settings["profiles"][new_name] = copy.deepcopy(
            self.settings["profiles"][src_name]
        )
        self.settings["profiles"][new_name]["enabled"] = False
        self.profile_state[new_name] = {"running": False, "thread": None, "stop_flag": False}
        self._create_profile_tab(new_name)
        self.notebook.select(self.profile_tabs[new_name])
        self.save_config()

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
        tab = self.profile_tabs.pop(name)
        self.notebook.forget(tab)
        tab.destroy()
        del self.profile_widgets[name]
        del self.settings["profiles"][name]
        self.profile_state.pop(name, None)
        if self.settings["global"].get("active_profile") == name:
            self.settings["global"]["active_profile"] = "Default"
            self.notebook.select(self.profile_tabs["Default"])
        self.save_config()
        self.setup_schedule()

    def on_profile_enabled_changed(self, profile_name):
        """Вызывается при изменении switch 'Enabled' профиля."""
        w = self.profile_widgets.get(profile_name)
        if not w:
            return
        enabled = w["enabled_var"].get()
        self.settings["profiles"][profile_name]["enabled"] = enabled
        self.save_config()
        self.setup_schedule()
        self.update_profile_status(profile_name)
        self.update_log(f"Profile '{profile_name}' {'enabled' if enabled else 'disabled'}")

    def _sync_profile_widgets_to_settings(self, profile_name):
        if profile_name not in self.profile_widgets:
            return
        w = self.profile_widgets[profile_name]
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

    def save_profile_settings(self, profile_name):
        self._sync_profile_widgets_to_settings(profile_name)
        self.save_config()

    # =========================================================
    # ================== PROFILE FIELD ACTIONS ================
    # =========================================================

    def add_source(self, profile_name):
        directory = filedialog.askdirectory()
        if directory:
            w = self.profile_widgets[profile_name]
            current = list(w["source_listbox"].get(0, tk.END))
            if directory not in current:
                w["source_listbox"].insert(tk.END, directory)
                self.save_profile_settings(profile_name)

    def remove_source(self, profile_name):
        w = self.profile_widgets[profile_name]
        selected = list(w["source_listbox"].curselection())
        for idx in reversed(selected):
            w["source_listbox"].delete(idx)
        self.save_profile_settings(profile_name)

    def browse_backup(self, profile_name):
        w = self.profile_widgets[profile_name]
        current = w["backup_entry"].get()
        initial = current if current else os.getcwd()
        directory = filedialog.askdirectory(initialdir=initial)
        if directory:
            w["backup_entry"].delete(0, tk.END)
            w["backup_entry"].insert(0, directory)
            self.save_profile_settings(profile_name)

    def on_custom_time_changed(self, profile_name):
        self.save_profile_settings(profile_name)
        self.setup_schedule()
        self._update_custom_time_hint(profile_name)

    def on_weekly_settings_changed(self, profile_name):
        self.save_profile_settings(profile_name)
        self.setup_schedule()
        self._update_custom_time_hint(profile_name)

    def schedule_changed(self, profile_name):
        w = self.profile_widgets[profile_name]
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
        self.save_profile_settings(profile_name)
        self.setup_schedule()
        self.update_tray_menu()

    def toggle_start_minimized(self):
        self.settings["global"]["start_minimized"] = self.start_minimized_var.get()
        self.save_config()

    def toggle_log_to_file(self):
        self.settings["global"]["log_to_file"] = self.log_to_file_var.get()
        self.save_config()

    # =========================================================
    # ======================= LOGGING =========================
    # =========================================================

    def update_log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        self.log_queue.put(log_line)
        if self.settings["global"].get("log_to_file", False):
            self.logger.info(message)

    def _flush_log_ui(self):
        """Периодически забирает накопленные строки лога из очереди и вставляет их в виджет одним пакетом."""
        lines = []
        try:
            while True:
                lines.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        if lines and hasattr(self, "log_display"):
            try:
                self.log_display.insert(tk.END, "".join(lines))
                self.log_display.see(tk.END)
            except tk.TclError:
                pass
        self.root.after(1000, self._flush_log_ui)

    # =========================================================
    # ====================== BACKUP ===========================
    # =========================================================

    def check_backup_dir_available(self, backup_dir):
        if not backup_dir:
            return False
        try:
            if not os.path.exists(backup_dir):
                return False
            if not os.access(backup_dir, os.W_OK):
                return False
            return True
        except Exception:
            return False

    def start_profile_backup(self, profile_name, show_dialog=True):
        """Запускает бэкап конкретного профиля."""
        state = self.profile_state.get(profile_name)
        if not state:
            return
        if state.get("running", False):
            self.update_log(f"Profile '{profile_name}': backup already running, skipping.")
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

        # Health Check
        if not self.check_backup_dir_available(backup_dir):
            msg = (f"Target path is not available: '{backup_dir}' "
                   f"(profile '{profile_name}'). Waiting for next cycle.")
            self.update_log(msg)
            if show_dialog:
                messagebox.showwarning("Backup Skipped", msg)
            return

        # Проверка свободного места
        free_bytes = self._get_free_space(backup_dir)
        if free_bytes is not None and free_bytes < MIN_FREE_BYTES:
            free_gb = free_bytes / (1024 ** 3)
            if show_dialog:
                if not messagebox.askyesno(
                    "Low Disk Space",
                    f"Only {free_gb:.2f} GB free on target disk.\nContinue backup?",
                ):
                    return
            else:
                self.update_log(f"Low disk space on target: {free_gb:.2f} GB free. Skipping.")
                return

        self.save_config()
        state["stop_flag"] = False
        self._set_profile_running(profile_name, True)
        self.update_log(f"=== Starting backup for profile '{profile_name}' ===")
        t = threading.Thread(
            target=self.run_backup, args=(profile_name,), daemon=True
        )
        state["thread"] = t
        t.start()

    def stop_profile_backup(self, profile_name):
        state = self.profile_state.get(profile_name)
        if state:
            state["stop_flag"] = True
            self.update_log(f"Backup stopped by user for profile '{profile_name}'.")
            self._set_profile_running(profile_name, False)

    def start_all_backups(self):
        """Запускает бэкап всех профилей с enabled=True."""
        started = 0
        for pname, profile in self.settings["profiles"].items():
            if profile.get("enabled", False):
                state = self.profile_state.get(pname, {})
                if not state.get("running", False):
                    self.start_profile_backup(pname, show_dialog=False)
                    started += 1
        self.update_log(f"Start All: launched {started} profile(s).")

    def stop_all_backups(self):
        """Останавливает все запущенные бэкапы."""
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

        start_time = time.time()
        total_stats = {
            "files_copied": 0,
            "files_skipped": 0,
            "total_size_mb": 0,
            "errors": 0,
        }
        all_copied_files = []

        try:
            for source_dir in source_dirs:
                if state.get("stop_flag", False):
                    break
                stats = backup_saves(
                    source_dir, backup_dir, skip_links, exclude_patterns_str,
                    source_dirs, state, log=self.update_log
                )
                for key in total_stats:
                    total_stats[key] += stats.get(key, 0)
                new_files = stats.get("copied_files", [])
                if len(all_copied_files) < MAX_COPIED_LIST:
                    room = MAX_COPIED_LIST - len(all_copied_files)
                    all_copied_files.extend(new_files[:room])
                total_stats["total_copied_count"] = (
                    total_stats.get("total_copied_count", 0) + len(new_files)
                )

            elapsed_time = time.time() - start_time
            speed = (
                total_stats["total_size_mb"] / elapsed_time
                if elapsed_time > 0
                else 0
            )

            if state.get("stop_flag", False):
                self.update_log(f"[{profile_name}] Backup stopped.")
            else:
                msg = (
                    f"[{profile_name}] Total files copied: {total_stats['files_copied']}\n"
                    f"Total files skipped: {total_stats['files_skipped']}\n"
                    f"Total size copied: {total_stats['total_size_mb']:.2f} MB\n"
                    f"Errors occurred: {total_stats['errors']}\n"
                    f"Time elapsed: {elapsed_time:.2f} seconds\n"
                    f"Average speed: {speed:.2f} MB/s"
                )
                self.update_log(msg)
                total_count = total_stats.get("total_copied_count", total_stats["files_copied"])
                if all_copied_files:
                    summary = f"\n=== Copied files ({total_count}) ===\n"
                    for f in all_copied_files:
                        summary += f"• {f}\n"
                    if total_count > len(all_copied_files):
                        summary += f"... and {total_count - len(all_copied_files)} more files (list truncated)\n"
                    self.update_log(summary)
                else:
                    self.update_log(f"\n=== [{profile_name}] Copied files: none (all files are up to date) ===\n")

        except Exception as e:
            self.update_log(f"[{profile_name}] Error: {str(e)}")
        finally:
            self.root.after(0, lambda pn=profile_name: self._set_profile_running(pn, False))

    # =========================================================
    # ===================== AUTORUN ===========================
    # =========================================================

    def toggle_autorun(self):
        if self.autorun_var.get():
            self.set_autorun(True)
        else:
            self.set_autorun(False)

    def set_autorun(self, enable):
        key = reg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with reg.OpenKey(key, key_path, 0, reg.KEY_ALL_ACCESS) as registry_key:
                if enable:
                    exe_path = (
                        sys.executable if getattr(sys, "frozen", False)
                        else os.path.abspath(__file__)
                    )
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
        """Регистрирует расписание для ВСЕХ профилей с enabled=True."""
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
                self.update_log(f"Error registering schedule for '{profile_name}': {e}")
        self.sched_thread = threading.Thread(target=self.run_scheduler, daemon=True)
        self.sched_thread.start()

    def _update_custom_time_hint(self, profile_name):
        """Обновляет подсказку под полем времени: серая при валидном значении, красная при ошибке."""
        w = self.profile_widgets.get(profile_name)
        if not w:
            return
        profile = self.settings["profiles"].get(profile_name, {})
        sched = profile.get("backup_schedule")
        if sched == "Custom" and "custom_hint_label" in w:
            custom = profile.get("custom_time", "")
            ok, err = validate_custom_time(custom)
            if ok:
                w["custom_hint_label"].config(
                    text="Examples: 21:30 (daily at 21:30), 120 (every 120 minutes)",
                    fg="gray",
                )
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
                w["weekly_hint_label"].config(
                    text="Time format: HH:MM (e.g., 23:00)",
                    fg="gray",
                )
            else:
                w["weekly_hint_label"].config(text=err, fg="red")

    def _register_schedule(self, profile_name, profile):
        sched = profile.get("backup_schedule", "None")
        if sched.startswith("Daily"):
            parts = sched.split()
            if len(parts) >= 2:
                time_str = parts[1]
                schedule.every().day.at(time_str).do(self.scheduled_backup, profile_name)
                self.update_log(f"Schedule (profile '{profile_name}'): daily at {time_str}")
            else:
                self.update_log(f"Error: invalid schedule format for '{profile_name}': '{sched}'")
        elif sched == "Custom":
            custom = profile.get("custom_time", "")
            ok, err = validate_custom_time(custom)
            if not ok:
                self.update_log(f"Error: {err} for '{profile_name}': '{custom}'")
            elif ":" in custom:
                schedule.every().day.at(custom).do(self.scheduled_backup, profile_name)
                self.update_log(f"Schedule (profile '{profile_name}'): daily at {custom}")
            else:
                schedule.every(int(custom)).minutes.do(self.scheduled_backup, profile_name)
                self.update_log(f"Schedule (profile '{profile_name}'): every {custom} minutes")
        elif sched == "Weekly":
            weekly_days = profile.get("weekly_days", [])
            weekly_time = profile.get("weekly_time", "")
            if not weekly_days:
                self.update_log(f"Error: no days selected for weekly schedule for '{profile_name}'")
                return
            ok, err = validate_hhmm(weekly_time)
            if not ok:
                self.update_log(f"Error: {err} for '{profile_name}': '{weekly_time}'")
                return
            for day in weekly_days:
                getattr(schedule.every(), day.lower()).at(weekly_time).do(
                    self.scheduled_backup, profile_name
                )
            days_str = ", ".join(weekly_days)
            self.update_log(f"Schedule (profile '{profile_name}'): weekly on {days_str} at {weekly_time}")

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
            self.update_log(f"[{profile_name}] Scheduled backup skipped: already running.")
            return
        self.start_profile_backup(profile_name, show_dialog=False)

    # =========================================================
    # ====================== CONFIG ===========================
    # =========================================================

    def save_config(self):
        active = self.settings["global"].get("active_profile", "Default")
        if active in self.profile_widgets:
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

        # --- Миграция со старого формата (без profiles) ---
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
                    "start_minimized": data.get("start_minimized", False),
                    "log_to_file": data.get("log_to_file", True),
                    "active_profile": "Default",
                },
                "profiles": {"Default": legacy_profile},
            }
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, ensure_ascii=False, indent=1)
            except Exception:
                pass
            return

        # --- Новый формат ---
        if "global" in data:
            self.settings["global"].update(data["global"])
        if "profiles" in data:
            self.settings["profiles"] = data["profiles"]
            # Гарантируем наличие полей "enabled", "weekly_days", "weekly_time" в каждом профиле
            for pname, pdata in self.settings["profiles"].items():
                if "enabled" not in pdata:
                    pdata["enabled"] = pdata.get("auto_start_backup", False)
                if "weekly_days" not in pdata:
                    pdata["weekly_days"] = ["Monday"]
                if "weekly_time" not in pdata:
                    pdata["weekly_time"] = "23:00"
            if "Default" not in self.settings["profiles"]:
                self.settings["profiles"]["Default"] = {
                    "source_dirs": [],
                    "backup_dir": "",
                    "skip_links": True,
                    "backup_schedule": "None",
                    "custom_time": "",
                    "exclude_patterns": "",
                    "enabled": False,
                    "auto_start_backup": False,
                    "weekly_days": ["Monday"],
                    "weekly_time": "23:00",
                }

    # =========================================================
    # ==================== TRAY ICON ==========================
    # =========================================================

    def create_tray_menu(self):
        return pystray.Menu(
            pystray.MenuItem("Open Window", self.show_window),
            pystray.MenuItem("Minimize to Tray", self.hide_window),
            pystray.MenuItem(
                "Run at Windows startup",
                self.toggle_autorun_from_tray,
                checked=lambda item: self.check_autorun(),
            ),
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
        self.tray_icon = pystray.Icon(
            "CloudBackupTool", image, "Cloud Backup Tool", self.create_tray_menu()
        )
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
        self.root.after(0, self.root.deiconify)

    def exit_app(self, *args):
        if hasattr(self, "sched_stop"):
            self.sched_stop.set()
        self.root.after(0, self._shutdown)

    def _shutdown(self):
        log_exit_or_crash("Normal shutdown initiated by user (exit_app called)")
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
        self.autorun_var.set(self.check_autorun())

    # =========================================================
    # ====================== UTILS ============================
    # =========================================================

    def _get_free_space(self, path):
        try:
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(path), None, None, ctypes.pointer(free_bytes)
            )
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