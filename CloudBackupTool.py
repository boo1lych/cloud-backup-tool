import os
import shutil
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox, simpledialog
from datetime import datetime
import threading
import json
import ctypes
import winreg as reg
import time
import schedule

CONFIG_FILE = "bt2_config.json"

def is_reparse_point(path):
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return False
        FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
        return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:
        return False

import pystray
from PIL import Image

class BackupApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Cloud Backup Tool")
        self.root.geometry("1500x800")
        self.root.resizable(True, True)

        # --- Добавление иконки для главного окна ---
        icon_path_ico = os.path.join(os.path.dirname(__file__), "backup.ico")
        icon_path_png = os.path.join(os.path.dirname(__file__), "backup.png")
        try:
            if os.path.exists(icon_path_ico):
                self.root.iconbitmap(icon_path_ico)
            elif os.path.exists(icon_path_png):
                self.icon_img = tk.PhotoImage(file=icon_path_png)  # Сохраняем как атрибут!
                self.root.iconphoto(True, self.icon_img)
        except Exception as e:
            print(f"Не удалось установить иконку окна: {e}")
        # --- Новая настройка: запускать свернутым ---
        self.settings = {
            "source_dirs": [],
            "backup_dir": "",
            "skip_links": True,
            "start_minimized": False
        }
        self.stop_backup_flag = False

        self.load_config()
        self.sched_stop = threading.Event()
        self.sched_thread = None
        self.create_widgets()
        self.create_tray_icon()

        # Обработчик закрытия окна
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.setup_schedule()
        # Если автозапуск и start_minimized - сразу в трей
        if self.settings.get("start_minimized", False):
            self.hide_window()
        else:
            self.root.deiconify()

    def create_widgets(self):
        # Список исходных папок
        source_frame = tk.Frame(self.root, padx=10, pady=10)
        source_frame.pack(fill=tk.X, pady=5)

        tk.Label(source_frame, text="Source Directories:").pack(anchor='w')
        self.source_listbox = tk.Listbox(source_frame, selectmode=tk.EXTENDED, width=60)
        self.source_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        for path in self.settings["source_dirs"]:
            self.source_listbox.insert(tk.END, path)

        source_btns = tk.Frame(source_frame)
        source_btns.pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(source_btns, text="Add...", command=self.add_source).pack(fill=tk.X)
        tk.Button(source_btns, text="Remove", command=self.remove_source).pack(fill=tk.X)

        # Целевая папка
        dir_frame = tk.Frame(self.root, padx=10, pady=10)
        dir_frame.pack(fill=tk.X, pady=5)

        tk.Label(dir_frame, text="Backup Directory:").grid(row=0, column=0, sticky=tk.W)
        self.backup_entry = tk.Entry(dir_frame, width=60)
        self.backup_entry.insert(0, self.settings["backup_dir"])
        self.backup_entry.grid(row=0, column=1, padx=5)
        tk.Button(dir_frame, text="Browse...", command=self.browse_backup).grid(row=0, column=2)

        # Чекбокс "Пропускать линки"
        self.skip_links_var = tk.BooleanVar(value=self.settings.get("skip_links", True))
        self.skip_links_cb = tk.Checkbutton(dir_frame, text="Skip symbolic links/junctions", variable=self.skip_links_var, command=self.toggle_skip_links)
        self.skip_links_cb.grid(row=2, column=0, sticky=tk.W)

        # Чекбокс "Сохранять лог в файл"
        self.log_to_file_var = tk.BooleanVar(value=self.settings.get("log_to_file", False))
        self.log_to_file_cb = tk.Checkbutton(dir_frame, text="Сохранять лог в файл", variable=self.log_to_file_var)
        self.log_to_file_cb.grid(row=3, column=0, sticky=tk.W)

        # Чекбокс автозагрузки
        self.autorun_var = tk.BooleanVar(value=self.check_autorun())
        self.autorun_cb = tk.Checkbutton(dir_frame, text="Запускать при старте Windows", variable=self.autorun_var, command=self.toggle_autorun)
        self.autorun_cb.grid(row=4, column=0, sticky=tk.W)

        # Чекбокс "Запускать свернутым"
        self.start_minimized_var = tk.BooleanVar(value=self.settings.get("start_minimized", False))
        self.start_minimized_cb = tk.Checkbutton(dir_frame, text="Запускать свернутым", variable=self.start_minimized_var, command=self.toggle_start_minimized)
        self.start_minimized_cb.grid(row=5, column=0, sticky=tk.W)

        # Настройка расписания
        tk.Label(dir_frame, text="Backup Schedule:").grid(row=6, column=0, sticky=tk.W)
        self.schedule_var = tk.StringVar(value=self.settings.get("backup_schedule", "None"))
        self.schedule_menu = tk.OptionMenu(dir_frame, self.schedule_var, "None", "Daily 23:00", "Daily 18:00", "Daily 10:00", "Custom", command=self.schedule_changed)
        self.schedule_menu.grid(row=6, column=1, sticky=tk.W)
        self.custom_time_entry = tk.Entry(dir_frame, width=10)
        self.custom_time_entry.grid(row=6, column=2, sticky=tk.W)
        self.custom_time_entry.insert(0, self.settings.get("custom_time", ""))
        self.custom_time_entry.grid_remove()
        self.custom_hint_label = tk.Label(dir_frame, text="Примеры: 21:30 (ежедневно в 21:30), 120 (каждые 120 минут)", fg="gray")
        self.custom_hint_label.grid(row=7, column=1, columnspan=2, sticky=tk.W)
        self.custom_hint_label.grid_remove()

        # Кнопки управления
        btn_frame = tk.Frame(self.root, padx=10, pady=5)
        btn_frame.pack(fill=tk.X)
        self.backup_button = tk.Button(btn_frame, text="Start Backup", command=self.start_backup, bg="#4CAF50", fg="white", height=2, width=15)
        self.backup_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = tk.Button(btn_frame, text="Stop", command=self.stop_backup, bg="#F44336", fg="white", height=2, width=15, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        self.exit_button = tk.Button(btn_frame, text="Выход", command=self.exit_app, bg="#888888", fg="white", height=2, width=15)
        self.exit_button.pack(side=tk.LEFT, padx=5)

        # Статус
        status_frame = tk.Frame(self.root, padx=10, pady=5)
        status_frame.pack(fill=tk.X)
        tk.Label(status_frame, text="Status:").pack(side=tk.LEFT)
        self.status_label = tk.Label(status_frame, text="Ready", fg="blue")
        self.status_label.pack(side=tk.LEFT, padx=5)

        # Лог
        results_frame = tk.Frame(self.root, padx=10, pady=5)
        results_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(results_frame, text="Backup Results:").pack(anchor=tk.W)
        self.log_display = scrolledtext.ScrolledText(results_frame, height=10, width=90, font=("Arial", 10))
        self.log_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_display.insert(tk.END, "")
        

        # Чекбокс "Запускать свернутым"
        #self.start_minimized_var = tk.BooleanVar(value=self.settings.get("start_minimized", False))
        #self.start_minimized_cb = tk.Checkbutton(dir_frame, text="Запускать свернутым", variable=self.start_minimized_var, command=self.toggle_start_minimized)
        #self.start_minimized_cb.grid(row=3, column=2, sticky=tk.W)
        
        # Чекбокс "Сохранять лог в файл"
        #self.log_to_file_var = tk.BooleanVar(value=self.settings.get("log_to_file", False))
        #self.log_to_file_cb = tk.Checkbutton(dir_frame, text="Сохранять лог в файл", variable=self.log_to_file_var)
        #self.log_to_file_cb.grid(row=2, column=2, sticky=tk.W)

        # Поле для масок исключения файлов/папок
        tk.Label(dir_frame, text="Исключить (маски через запятую):").grid(row=8, column=0, sticky=tk.W)
        self.exclude_entry = tk.Entry(dir_frame, width=60)
        self.exclude_entry.insert(0, self.settings.get("exclude_patterns", ""))
        self.exclude_entry.grid(row=8, column=1, padx=5, pady=5, columnspan=2, sticky=tk.W)

    def toggle_start_minimized(self):
        self.settings["start_minimized"] = self.start_minimized_var.get()
        self.save_config()

    def add_source(self):
        directory = filedialog.askdirectory()
        if directory and directory not in self.settings["source_dirs"]:
            self.settings["source_dirs"].append(directory)
            self.source_listbox.insert(tk.END, directory)
            self.save_config()

    def remove_source(self):
        selected = list(self.source_listbox.curselection())
        for idx in reversed(selected):
            self.settings["source_dirs"].pop(idx)
            self.source_listbox.delete(idx)
        self.save_config()

    def browse_backup(self):
        directory = filedialog.askdirectory(initialdir=self.settings["backup_dir"] or os.getcwd())
        if directory:
            self.settings["backup_dir"] = directory
            self.backup_entry.delete(0, tk.END)
            self.backup_entry.insert(0, directory)
            self.save_config()

    def toggle_skip_links(self):
        self.settings["skip_links"] = self.skip_links_var.get()
        self.save_config()

    def update_log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        self.log_display.insert(tk.END, log_line)
        self.log_display.see(tk.END)
        # Сохранять лог в файл, если включено
        if self.log_to_file_var.get():
            try:
                with open("backup.log", "a", encoding="utf-8") as f:
                    f.write(log_line)
            except Exception as e:
                # Можно добавить вывод ошибки в лог, если не удалось записать
                self.log_display.insert(tk.END, f"[{timestamp}] Ошибка записи лога в файл: {e}\n")

    def update_status(self, message, color="blue"):
        self.status_label.config(text=message, fg=color)

    def start_backup(self):
        if not self.settings["source_dirs"]:
            messagebox.showerror("Error", "No source directories specified.")
            return
        if not self.settings["backup_dir"]:
            messagebox.showerror("Error", "No backup directory specified.")
            return
        if not os.path.exists(self.settings["backup_dir"]):
            messagebox.showerror("Error", "Backup directory is not accessible.")
            return
        self.stop_backup_flag = False
        self.backup_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.update_status("Backup in progress...", "orange")
        threading.Thread(target=self.run_backup, daemon=True).start()

    def stop_backup(self):
        self.stop_backup_flag = True
        self.stop_button.config(state=tk.DISABLED)
        self.update_status("Backup stopped", "red")
        self.update_log("Backup process stopped by user.")

    def run_backup(self):
        start_time = time.time()
        total_stats = {"files_copied": 0, "files_skipped": 0, "total_size_mb": 0, "errors": 0}
        all_copied_files = []
        try:
            self.root.after(0, lambda: self.log_display.delete(1.0, tk.END))
            for source_dir in self.settings["source_dirs"]:
                if self.stop_backup_flag:
                    break
                stats = self.backup_saves(source_dir, self.settings["backup_dir"])
                for key in total_stats:
                    total_stats[key] += stats.get(key, 0)
                all_copied_files.extend(stats.get("copied_files", []))    
            elapsed_time = time.time() - start_time
            speed = total_stats["total_size_mb"] / elapsed_time if elapsed_time > 0 else 0
            if self.stop_backup_flag:
                self.update_status("Backup stopped", "red")
            else:
                msg = (f"Total files copied: {total_stats['files_copied']}\n"
                       f"Total files skipped: {total_stats['files_skipped']}\n"
                       f"Total size copied: {total_stats['total_size_mb']:.2f} MB\n"
                       f"Errors occurred: {total_stats['errors']}\n"
                       f"Time elapsed: {elapsed_time:.2f} seconds\n"
                       f"Average speed: {speed:.2f} MB/s")
                self.update_log(msg)

                # Итоговая сводка по скопированным файлам
                if all_copied_files:
                    summary = f"\n=== Скопированные файлы ({len(all_copied_files)} шт) ===\n"
                    for f in all_copied_files:
                        summary += f"• {f}\n"
                    self.update_log(summary)
                else:
                    self.update_log("\n=== Скопированные файлы: нет (все файлы актуальны) ===\n")

                self.update_status(f"Done - {total_stats['files_copied']} files backed up", "green")
        except Exception as e:
            self.update_log(f"Error: {str(e)}")
            self.update_status("Backup failed", "red")
            # Попытка вывести статистику даже при ошибке
            try:
                elapsed_time = time.time() - start_time
                speed = total_stats["total_size_mb"] / elapsed_time if elapsed_time > 0 else 0
                msg = (f"Total files copied: {total_stats.get('files_copied', 0)}\n"
                       f"Total files skipped: {total_stats.get('files_skipped', 0)}\n"
                       f"Total size copied: {total_stats.get('total_size_mb', 0):.2f} MB\n"
                       f"Errors occurred: {total_stats.get('errors', 0)}\n"
                       f"Time elapsed: {elapsed_time:.2f} seconds\n"
                       f"Average speed: {speed:.2f} MB/s")
                self.update_log(msg)
                if all_copied_files:
                    summary = f"\n=== Скопированные файлы ({len(all_copied_files)} шт) ===\n"
                    for f in all_copied_files:
                        summary += f"• {f}\n"
                    self.update_log(summary)                
            except Exception:
                pass
        finally:
            self.root.after(0, lambda: self.backup_button.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_button.config(state=tk.DISABLED))

    def backup_saves(self, source_dir, backup_dir):
        files_copied = 0
        files_skipped = 0
        total_size = 0
        copied_files = []
        exclude_patterns = [p.strip() for p in self.settings.get("exclude_patterns", "").split(",") if p.strip()]
        # Имя подпапки для этого источника
        src_folder_name = os.path.basename(os.path.normpath(source_dir))
        dest_root = os.path.join(backup_dir, src_folder_name)
        os.makedirs(dest_root, exist_ok=True)
        for root, dirs, files in os.walk(source_dir, topdown=True):
            # Пропускать линки, если включено
            if self.settings.get("skip_links", True):
                dirs[:] = [d for d in dirs if not is_reparse_point(os.path.join(root, d))]
            rel_path = os.path.relpath(root, source_dir)
            dest_path = os.path.join(dest_root, rel_path) if rel_path != '.' else dest_root
            os.makedirs(dest_path, exist_ok=True)
            for file in files:
                # Пропуск по маске
                if any(pattern in file for pattern in exclude_patterns):
                    files_skipped += 1
                    self.update_log(f"Skipped (excluded by pattern): {os.path.join(root, file)}")
                    continue
                if self.stop_backup_flag:
                    return {
                        "files_copied": files_copied,
                        "files_skipped": files_skipped,
                        "total_size_mb": total_size / 1024 / 1024,
                        "copied_files": copied_files
                    }
                src_file = os.path.join(root, file)
                dst_file = os.path.join(dest_path, file)
                # Пропускать линки-файлы, если включено
                if self.settings.get("skip_links", True) and is_reparse_point(src_file):
                    files_skipped += 1
                    self.update_log(f"Skipped (symbolic link): {src_file}")
                    continue
                copy_needed = True
                if os.path.exists(dst_file):
                    src_stat = os.stat(src_file)
                    dst_stat = os.stat(dst_file)
                    # Добавляем допуск в 2 секунды для st_mtime.
                    # Сетевые диски, облачные синхронизации и FAT32/exFAT часто округляют время модификации,
                    # из-за чего строгое равенство (==) всегда возвращает False и файл копируется по кругу.
                    mtime_diff = abs(src_stat.st_mtime - dst_stat.st_mtime)
                    if mtime_diff < 2.0 and src_stat.st_size == dst_stat.st_size:
                        copy_needed = False
                if copy_needed:
                    try:
                        shutil.copy2(src_file, dst_file)
                        files_copied += 1
                        total_size += os.path.getsize(src_file)
                        copied_files.append(src_file)
                        self.update_log(f"Copied: {src_file}")
                    except Exception as e:
                        self.update_log(f"Error copying {src_file}: {str(e)}")
                else:
                    files_skipped += 1
                    self.update_log(f"Skipped (unchanged): {src_file}")
        return {
            "files_copied": files_copied,
            "files_skipped": files_skipped,
            "total_size_mb": total_size / 1024 / 1024,
            "copied_files": copied_files
        }

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
                    import sys
                    exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
                    reg.SetValueEx(
                        registry_key,
                        "CloudBackupTool",
                        0,
                        reg.REG_SZ,
                        f'"{exe_path}"'
                    )
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

    def schedule_changed(self, value):
        if value == "Custom":
            self.custom_time_entry.grid()
            self.custom_hint_label.grid()
        else:
            self.custom_time_entry.grid_remove()
            self.custom_hint_label.grid_remove()
        self.settings["backup_schedule"] = value
        self.save_config()
        self.setup_schedule()
        self.update_tray_menu()  # <--- добавьте этот вызов

    def setup_schedule(self):
        self.sched_stop.set()
        if self.sched_thread and self.sched_thread.is_alive():
            self.sched_thread.join()
        self.sched_stop.clear()
        schedule.clear()
        sched = self.settings.get("backup_schedule", "None")
        if sched == "None":
            return
        elif sched.startswith("Daily"):
            time_str = sched.split()[1]
            schedule.every().day.at(time_str).do(self.scheduled_backup)
        elif sched == "Custom":
            custom = self.custom_time_entry.get()
            if ":" in custom:
                schedule.every().day.at(custom).do(self.scheduled_backup)
            elif custom.isdigit():
                schedule.every(int(custom)).minutes.do(self.scheduled_backup)
        self.sched_thread = threading.Thread(target=self.run_scheduler, daemon=True)
        self.sched_thread.start()

    def run_scheduler(self):
        while not self.sched_stop.is_set():
            schedule.run_pending()
            time.sleep(1)

    def scheduled_backup(self):
        if self.backup_button["state"] == tk.NORMAL:
            self.root.after(0, self.start_backup)

    def save_config(self):
        self.settings["backup_dir"] = self.backup_entry.get()
        self.settings["backup_schedule"] = self.schedule_var.get()
        self.settings["custom_time"] = self.custom_time_entry.get()
        self.settings["start_minimized"] = self.start_minimized_var.get()
        self.settings["log_to_file"] = self.log_to_file_var.get()
        self.settings["exclude_patterns"] = self.exclude_entry.get()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=2)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                self.settings = json.load(f)
        if hasattr(self, "start_minimized_var"):
            self.start_minimized_var.set(self.settings.get("start_minimized", False))
        if hasattr(self, "log_to_file_var"):
            self.log_to_file_var.set(self.settings.get("log_to_file", False))
        if hasattr(self, "exclude_entry"):
            self.exclude_entry.delete(0, tk.END)
            self.exclude_entry.insert(0, self.settings.get("exclude_patterns", ""))

    def create_tray_menu(self):
        return pystray.Menu(
            pystray.MenuItem("Открыть окно", self.show_window),
            pystray.MenuItem("Свернуть в трей", self.hide_window),
            pystray.MenuItem(
                "Автозагрузка",
                self.toggle_autorun_from_tray,
                checked=lambda item: self.check_autorun()
            ),
            pystray.MenuItem(
                "Периодический запуск",
                self.toggle_schedule_from_tray,
                checked=lambda item: self.settings.get("backup_schedule", "None") != "None"
            ),
            pystray.MenuItem("Выход", self.exit_app)
        )

    def create_tray_icon(self):
        icon_path_ico = os.path.join(os.path.dirname(__file__), "backup.ico")
        icon_path_png = os.path.join(os.path.dirname(__file__), "backup.png")
        image = None
        try:
            if os.path.exists(icon_path_ico):
                image = Image.open(icon_path_ico)
            elif os.path.exists(icon_path_png):
                image = Image.open(icon_path_png)
        except Exception as e:
            print(f"Не удалось загрузить иконку для трея: {e}")
        if image is None:
            image = Image.new('RGB', (16, 16), color='white')

        self.tray_icon = pystray.Icon("CloudBackupTool", image, "Cloud Backup Tool", self.create_tray_menu())
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_window(self, *args):
        self.root.withdraw()

    def show_window(self, *args):
        self.root.after(0, self.root.deiconify)

    def exit_app(self):
        self.root.destroy()
        if hasattr(self, "tray_icon"):
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    def toggle_autorun_from_tray(self, icon, item):
        if self.check_autorun():
            self.set_autorun(False)
        else:
            self.set_autorun(True)
        # Обновить чекбокс в интерфейсе
        self.autorun_var.set(self.check_autorun())

    def toggle_schedule_from_tray(self, icon, item):
        # Включить/отключить расписание
        if self.settings.get("backup_schedule", "None") == "None":
            self.schedule_var.set("Daily 23:00")
        else:
            self.schedule_var.set("None")
        self.schedule_changed(self.schedule_var.get())

if __name__ == "__main__":
    root = tk.Tk()
    app = BackupApp(root)
    root.mainloop()
    
    
'''
REBUILDING THE EXE FILE:

To convert your Python backup application into an executable (.exe) file and then package it into a ZIP file, you can use PyInstaller. Here's a step-by-step guide:
Step 1: Install PyInstaller in command prompt

pip install pyinstaller

Step 2: Create the Executable
- Open a command prompt in the folder where your Python script is located and run:


pyinstaller --onefile --windowed  your_script.py


Step 3: Find Your Executable
- The executable will be created in the dist folder within your project directory.

Step 4: Create a ZIP Archive
You can create a ZIP file manually by:
- Right-clicking the executable in the dist folder
- Selecting "Send to" > "Compressed (zipped) folder"

'''