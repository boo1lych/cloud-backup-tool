"""Тесты для проверки сохранения и загрузки настроек профилей."""
import unittest
import json
import os
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock
import sys

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from CloudBackupTool import BackupApp


class TestProfileSettings(unittest.TestCase):
    """Тесты для проверки корректности сохранения настроек профилей."""

    def _create_full_widget_mocks(self):
        """Создаёт полный набор моков для всех виджетов профиля."""
        widgets = {
            "source_listbox": Mock(),
            "backup_entry": Mock(),
            "skip_links_var": Mock(),
            "trigger_mode_var": Mock(),
            "schedule_var": Mock(),
            "schedule_menu": Mock(),
            "schedule_label": Mock(),
            "custom_time_entry": Mock(),
            "custom_hint_label": Mock(),
            "weekly_time_entry": Mock(),
            "weekly_days_frame": Mock(),
            "weekly_hint_label": Mock(),
            "event_frame": Mock(),
            "overflow_frame": Mock(),
            "exclude_entry": Mock(),
            "enabled_var": Mock(),
            "auto_start_backup_var": Mock(),
            "weekly_day_vars": {
                "Monday": Mock(),
                "Tuesday": Mock(),
                "Wednesday": Mock(),
                "Thursday": Mock(),
                "Friday": Mock(),
                "Saturday": Mock(),
                "Sunday": Mock(),
            },
            "pc_enabled_var": Mock(),
            "pc_close_listbox": Mock(),
            "pc_close_mode_var": Mock(),
            "pc_graceful_timeout_var": Mock(),
            "pc_on_close_failure_var": Mock(),
            "pc_restore_after_var": Mock(),
            "retry_enabled_var": Mock(),
            "retry_max_attempts_var": Mock(),
            "retry_interval_seconds_var": Mock(),
            "retry_on_vars": {
                "disk_unavailable": Mock(),
                "process_close_failed": Mock(),
                "copy_errors": Mock(),
                "low_disk_space": Mock(),
                "source_missing": Mock(),
                "timeout_exceeded": Mock(),
            },
            "retry_on_total_failure_actions": [],
            "total_timeout_minutes_var": Mock(),
            "event_created_var": Mock(),
            "event_modified_var": Mock(),
            "event_deleted_var": Mock(),
            "event_moved_var": Mock(),
            "on_overflow_var": Mock(),
        }
        
        # Настраиваем winfo_children для фреймов
        widgets["weekly_days_frame"].winfo_children.return_value = []
        
        # Устанавливаем дефолтные значения
        widgets["source_listbox"].get.return_value = []
        widgets["backup_entry"].get.return_value = ""
        widgets["skip_links_var"].get.return_value = True
        widgets["trigger_mode_var"].get.return_value = "schedule"
        widgets["schedule_var"].get.return_value = "None"
        widgets["custom_time_entry"].get.return_value = ""
        widgets["exclude_entry"].get.return_value = ""
        widgets["enabled_var"].get.return_value = False
        widgets["auto_start_backup_var"].get.return_value = False
        widgets["weekly_time_entry"].get.return_value = "23:00"
        widgets["pc_enabled_var"].get.return_value = False
        widgets["pc_close_listbox"].get.return_value = []
        widgets["pc_close_mode_var"].get.return_value = "graceful_then_force"
        widgets["pc_graceful_timeout_var"].get.return_value = "10"
        widgets["pc_on_close_failure_var"].get.return_value = "abort"
        widgets["pc_restore_after_var"].get.return_value = "only_if_was_running"
        widgets["retry_enabled_var"].get.return_value = False
        widgets["retry_max_attempts_var"].get.return_value = "3"
        widgets["retry_interval_seconds_var"].get.return_value = "300"
        widgets["total_timeout_minutes_var"].get.return_value = "0"
        widgets["event_created_var"].get.return_value = True
        widgets["event_modified_var"].get.return_value = True
        widgets["event_deleted_var"].get.return_value = True
        widgets["event_moved_var"].get.return_value = True
        widgets["on_overflow_var"].get.return_value = "run_immediately"
        
        # Все дни недели по умолчанию выключены
        for day, var in widgets["weekly_day_vars"].items():
            var.get.return_value = False
        
        # Все retry_on по умолчанию выключены
        for opt, var in widgets["retry_on_vars"].items():
            var.get.return_value = False
        
        return widgets

    def setUp(self):
        """Создаём временную директорию для тестов."""
        self.test_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.test_dir, "bt2_config.json")
        
        # Мокаем tkinter root
        self.mock_root = Mock()
        self.mock_root.title = Mock()
        self.mock_root.geometry = Mock()
        self.mock_root.minsize = Mock()
        self.mock_root.resizable = Mock()
        self.mock_root.iconbitmap = Mock()
        self.mock_root.iconphoto = Mock()
        self.mock_root.protocol = Mock()
        self.mock_root.after = Mock()
        self.mock_root.deiconify = Mock()
        self.mock_root.withdraw = Mock()
        self.mock_root.destroy = Mock()
        self.mock_root.winfo_exists = Mock(return_value=True)
        
        # Патчим CONFIG_FILE
        self.config_patcher = patch('CloudBackupTool.CONFIG_FILE', self.config_file)
        self.config_patcher.start()
        
        # Патчим создание виджетов и tray icon
        self.widgets_patcher = patch.object(BackupApp, 'create_widgets')
        self.widgets_patcher.start()
        
        self.tray_patcher = patch.object(BackupApp, 'create_tray_icon')
        self.tray_patcher.start()
        
        self.schedule_patcher = patch.object(BackupApp, 'setup_schedule')
        self.schedule_patcher.start()
        
        self.auto_start_patcher = patch.object(BackupApp, '_auto_start_on_launch')
        self.auto_start_patcher.start()

    def tearDown(self):
        """Удаляем временную директорию."""
        self.config_patcher.stop()
        self.widgets_patcher.stop()
        self.tray_patcher.stop()
        self.schedule_patcher.stop()
        self.auto_start_patcher.stop()
        
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_custom_time_preserved_on_profile_switch(self):
        """Проверяет, что custom_time не перезаписывается при переключении профилей."""
        # Создаём приложение
        app = BackupApp(self.mock_root)
        
        # Создаём профиль Outlook с Custom schedule
        app.settings["profiles"]["Outlook"] = {
            "source_dirs": ["C:/Test"],
            "backup_dir": "D:/Backup",
            "skip_links": True,
            "trigger_mode": "schedule",
            "backup_schedule": "Custom",
            "custom_time": "23:00",
            "exclude_patterns": "",
            "enabled": True,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
        }
        
        # Создаём профиль Default с Daily schedule
        app.settings["profiles"]["Default"] = {
            "source_dirs": [],
            "backup_dir": "",
            "skip_links": True,
            "trigger_mode": "schedule",
            "backup_schedule": "Daily 10:00",
            "custom_time": "",
            "exclude_patterns": "",
            "enabled": False,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
        }
        
        # Мокаем все виджеты
        app.profile_widgets = self._create_full_widget_mocks()
        
        # Загружаем Outlook
        app.current_profile_name = "Outlook"
        app.profile_widgets["schedule_var"].get.return_value = "Custom"
        app.profile_widgets["custom_time_entry"].get.return_value = "23:00"
        
        # Сохраняем настройки Outlook
        app._sync_profile_widgets_to_settings("Outlook")
        
        # Проверяем, что custom_time сохранён
        self.assertEqual(app.settings["profiles"]["Outlook"]["custom_time"], "23:00")
        
        # Переключаемся на Default
        app.current_profile_name = "Default"
        app.profile_widgets["schedule_var"].get.return_value = "Daily 10:00"
        app.profile_widgets["custom_time_entry"].get.return_value = "10"  # Мусорное значение
        
        # Сохраняем настройки Default
        app._sync_profile_widgets_to_settings("Default")
        
        # Проверяем, что custom_time в Outlook НЕ изменился
        self.assertEqual(app.settings["profiles"]["Outlook"]["custom_time"], "23:00")

    def test_custom_time_saved_only_for_custom_schedule(self):
        """Проверяет, что custom_time сохраняется только для Custom schedule."""
        app = BackupApp(self.mock_root)
        
        app.settings["profiles"]["TestProfile"] = {
            "source_dirs": [],
            "backup_dir": "",
            "skip_links": True,
            "trigger_mode": "schedule",
            "backup_schedule": "Custom",
            "custom_time": "23:00",
            "exclude_patterns": "",
            "enabled": False,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
        }
        
        app.profile_widgets = self._create_full_widget_mocks()
        
        # Настраиваем моки
        app.profile_widgets["schedule_var"].get.return_value = "Custom"
        app.profile_widgets["custom_time_entry"].get.return_value = "21:30"
        
        app.current_profile_name = "TestProfile"
        
        # Сохраняем настройки
        app._sync_profile_widgets_to_settings("TestProfile")
        
        # Проверяем, что custom_time сохранён
        self.assertEqual(app.settings["profiles"]["TestProfile"]["custom_time"], "21:30")
        
        # Меняем schedule на Daily
        app.profile_widgets["schedule_var"].get.return_value = "Daily 10:00"
        app.profile_widgets["custom_time_entry"].get.return_value = "99:99"  # Мусор
        
        # Сохраняем снова
        app._sync_profile_widgets_to_settings("TestProfile")
        
        # custom_time НЕ должен измениться (остался 21:30)
        self.assertEqual(app.settings["profiles"]["TestProfile"]["custom_time"], "21:30")

    def test_weekly_time_saved_correctly(self):
        """Проверяет, что weekly_time корректно сохраняется."""
        app = BackupApp(self.mock_root)
        
        app.settings["profiles"]["WeeklyProfile"] = {
            "source_dirs": [],
            "backup_dir": "",
            "skip_links": True,
            "trigger_mode": "schedule",
            "backup_schedule": "Weekly",
            "custom_time": "",
            "exclude_patterns": "",
            "enabled": False,
            "auto_start_backup": False,
            "weekly_days": ["Monday", "Friday"],
            "weekly_time": "23:00",
        }
        
        app.profile_widgets = self._create_full_widget_mocks()
        
        # Настраиваем моки
        app.profile_widgets["schedule_var"].get.return_value = "Weekly"
        app.profile_widgets["weekly_time_entry"].get.return_value = "18:30"
        
        # Настраиваем дни недели
        for day, var in app.profile_widgets["weekly_day_vars"].items():
            var.get.return_value = day in ["Monday", "Friday"]
        
        app.current_profile_name = "WeeklyProfile"
        
        # Сохраняем настройки
        app._sync_profile_widgets_to_settings("WeeklyProfile")
        
        # Проверяем
        self.assertEqual(app.settings["profiles"]["WeeklyProfile"]["weekly_time"], "18:30")
        self.assertEqual(app.settings["profiles"]["WeeklyProfile"]["weekly_days"], ["Monday", "Friday"])

    def test_config_save_and_load(self):
        """Проверяет, что конфиг корректно сохраняется и загружается."""
        app = BackupApp(self.mock_root)
        
        # Добавляем профиль
        app.settings["profiles"]["TestProfile"] = {
            "source_dirs": ["C:/Test"],
            "backup_dir": "D:/Backup",
            "skip_links": True,
            "trigger_mode": "schedule",
            "backup_schedule": "Custom",
            "custom_time": "23:00",
            "exclude_patterns": "*.tmp",
            "enabled": True,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
        }
        
        app.current_profile_name = "TestProfile"
        
        # Мокаем все виджеты
        app.profile_widgets = self._create_full_widget_mocks()
        app.profile_widgets["schedule_var"].get.return_value = "Custom"
        app.profile_widgets["custom_time_entry"].get.return_value = "23:00"
        
        # Сохраняем конфиг
        app.save_config()
        
        # Проверяем, что файл создан
        self.assertTrue(os.path.exists(self.config_file))
        
        # Загружаем конфиг
        with open(self.config_file, "r", encoding="utf-8") as f:
            loaded_config = json.load(f)
        
        # Проверяем данные
        self.assertIn("TestProfile", loaded_config["profiles"])
        self.assertEqual(loaded_config["profiles"]["TestProfile"]["custom_time"], "23:00")
        self.assertEqual(loaded_config["profiles"]["TestProfile"]["backup_schedule"], "Custom")


class MockEntry:
    """Умный мок для ttk.Entry, который эмулирует поведение state='disabled'.
    
    В реальном tkinter Entry с state='disabled' игнорирует delete/insert —
    значение не меняется. Это критично для воспроизведения бага, когда
    _update_trigger_mode_state() не был вызван до изменения значений,
    и Entry оставался заблокированным от предыдущего профиля.
    """
    def __init__(self, initial_value=""):
        self.value = initial_value
        self.state = "normal"
    
    def get(self):
        return self.value
    
    def delete(self, first, last):
        if self.state == "disabled":
            return  # Реальный Entry игнорирует delete при disabled
        self.value = ""
    
    def insert(self, index, text):
        if self.state == "disabled":
            return  # Реальный Entry игнорирует insert при disabled
        self.value = text
    
    def config(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]


class TestProfileSettingsRealConfig(TestProfileSettings):
    """Тесты с реальным конфигом пользователя."""

    def test_custom_time_preserved_when_switching_through_event_driven_profile(self):
        """Воспроизводит реальный баг:
        
        1. Пользователь в Outlook (Custom, trigger_mode=schedule, custom_time='23:00')
        2. Переключается на Default (Weekly, trigger_mode=file_change, on_overflow='run_immediately')
           → _update_trigger_mode_state() блокирует custom_time_entry (state='disabled')
        3. Возвращается на Outlook
           → Если _update_trigger_mode_state() не вызван ДО insert в custom_time_entry,
             то Entry остаётся заблокированным от Default, и insert('23:00') игнорируется.
           → custom_time_entry остаётся '10' от Default.
           → save_config() записывает '10' в Outlook.
        
        Фикс: _update_trigger_mode_state() вызывается сразу после trigger_mode_var.set(),
        ДО изменения значений виджетов.
        """
        app = BackupApp(self.mock_root)
        
        # Настраиваем профили
        app.settings["profiles"]["Outlook"] = {
            "source_dirs": ["C:/Test"],
            "backup_dir": "D:/Backup",
            "skip_links": True,
            "trigger_mode": "schedule",
            "backup_schedule": "Custom",
            "custom_time": "23:00",
            "exclude_patterns": "",
            "enabled": True,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
            "on_queue_overflow": "run_immediately",
        }
        
        app.settings["profiles"]["Default"] = {
            "source_dirs": [],
            "backup_dir": "",
            "skip_links": True,
            "trigger_mode": "file_change",
            "backup_schedule": "Weekly",
            "custom_time": "10",
            "exclude_patterns": "",
            "enabled": True,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
            "on_queue_overflow": "run_immediately",  # → Entry будет заблокирован
        }
        
        # Используем реальные MockEntry, которые эмулируют state='disabled'
        custom_time_entry = MockEntry()
        weekly_time_entry = MockEntry()
        backup_entry = MockEntry()
        exclude_entry = MockEntry()
        
        # Listbox с поддержкой insert/delete
        source_listbox = Mock()
        source_listbox._items = []
        source_listbox.delete = Mock(side_effect=lambda *a: source_listbox._items.clear())
        source_listbox.insert = Mock(side_effect=lambda idx, val: source_listbox._items.append(val))
        source_listbox.get = Mock(side_effect=lambda *a: list(source_listbox._items))
        
        pc_close_listbox = Mock()
        pc_close_listbox._items = []
        pc_close_listbox.delete = Mock(side_effect=lambda *a: pc_close_listbox._items.clear())
        pc_close_listbox.insert = Mock(side_effect=lambda idx, val: pc_close_listbox._items.append(val))
        pc_close_listbox.get = Mock(side_effect=lambda *a: list(pc_close_listbox._items))
        
        retry_failure_listbox = Mock()
        retry_failure_listbox._items = []
        retry_failure_listbox.delete = Mock(side_effect=lambda *a: retry_failure_listbox._items.clear())
        retry_failure_listbox.insert = Mock(side_effect=lambda idx, val: retry_failure_listbox._items.append(val))
        
        # Умные моки для Var-виджетов, которые используются в _update_trigger_mode_state
        # Они должны запоминать значение после set()
        def make_smart_var(initial=""):
            var = Mock()
            var._value = initial
            var.get = lambda: var._value
            var.set = lambda v: setattr(var, '_value', v)
            return var
        
        trigger_mode_var = make_smart_var("schedule")
        on_overflow_var = make_smart_var("run_immediately")
        
        app.profile_widgets = {
            "enabled_var": Mock(),
            "source_listbox": source_listbox,
            "backup_entry": backup_entry,
            "skip_links_var": Mock(),
            "auto_start_backup_var": Mock(),
            "trigger_mode_var": trigger_mode_var,
            "schedule_var": Mock(),
            "schedule_menu": Mock(),
            "custom_time_entry": custom_time_entry,
            "weekly_time_entry": weekly_time_entry,
            "exclude_entry": exclude_entry,
            "weekly_day_vars": {
                "Monday": Mock(), "Tuesday": Mock(), "Wednesday": Mock(),
                "Thursday": Mock(), "Friday": Mock(), "Saturday": Mock(), "Sunday": Mock(),
            },
            "weekly_days_frame": Mock(),
            "event_created_var": Mock(),
            "event_modified_var": Mock(),
            "event_deleted_var": Mock(),
            "event_moved_var": Mock(),
            "on_overflow_var": on_overflow_var,
            "pc_enabled_var": Mock(),
            "pc_close_listbox": pc_close_listbox,
            "pc_close_mode_var": Mock(),
            "pc_graceful_timeout_var": Mock(),
            "pc_on_close_failure_var": Mock(),
            "pc_restore_after_var": Mock(),
            "retry_enabled_var": Mock(),
            "retry_max_attempts_var": Mock(),
            "retry_interval_seconds_var": Mock(),
            "retry_on_vars": {},
            "retry_failure_listbox": retry_failure_listbox,
            "total_timeout_minutes_var": Mock(),
        }
        
        # Настраиваем winfo_children
        app.profile_widgets["weekly_days_frame"].winfo_children.return_value = []
        
        # Настраиваем return_value для всех Var-виджетов, чтобы _sync не падал на int()
        app.profile_widgets["enabled_var"].get.return_value = True
        app.profile_widgets["skip_links_var"].get.return_value = True
        app.profile_widgets["auto_start_backup_var"].get.return_value = False
        app.profile_widgets["schedule_var"].get.return_value = "Custom"
        app.profile_widgets["pc_enabled_var"].get.return_value = False
        app.profile_widgets["pc_close_mode_var"].get.return_value = "graceful_then_force"
        app.profile_widgets["pc_graceful_timeout_var"].get.return_value = "10"
        app.profile_widgets["pc_on_close_failure_var"].get.return_value = "abort"
        app.profile_widgets["pc_restore_after_var"].get.return_value = "only_if_was_running"
        app.profile_widgets["retry_enabled_var"].get.return_value = False
        app.profile_widgets["retry_max_attempts_var"].get.return_value = "3"
        app.profile_widgets["retry_interval_seconds_var"].get.return_value = "300"
        app.profile_widgets["total_timeout_minutes_var"].get.return_value = "0"
        app.profile_widgets["event_created_var"].get.return_value = True
        app.profile_widgets["event_deleted_var"].get.return_value = True
        app.profile_widgets["event_moved_var"].get.return_value = True
        
        # Мокаем методы обновления UI, КРОМЕ _update_trigger_mode_state
        # (он должен работать реально, чтобы управлять состоянием Entry)
        app._update_schedule_visibility = Mock()
        app.update_profile_status = Mock()
        app._update_custom_time_hint = Mock()
        app._refresh_log_display = Mock()
        app._update_monitoring_indicator = Mock()
        app._update_failure_listbox = Mock()
        app._start_event_monitor = Mock()
        app._stop_event_monitor = Mock()
        app._update_tabs_state = Mock()
        
        # Загружаем Outlook (первоначальная загрузка)
        app._load_profile_to_widgets("Outlook")
        self.assertEqual(custom_time_entry.get(), "23:00",
                        "После загрузки Outlook custom_time_entry должен содержать '23:00'")
        self.assertEqual(custom_time_entry.state, "normal",
                        "Для schedule-профиля Entry должен быть разблокирован")
        
        # Сохраняем Outlook
        app._sync_profile_widgets_to_settings("Outlook")
        self.assertEqual(app.settings["profiles"]["Outlook"]["custom_time"], "23:00")
        
        # Переключаемся на Default (event-driven, Entry будет заблокирован)
        app._load_profile_to_widgets("Default")
        self.assertEqual(custom_time_entry.state, "disabled",
                        "Для event-driven профиля Entry должен быть заблокирован")
        # custom_time_entry остался '23:00' — insert игнорируется из-за disabled
        # Это нормальное поведение реального Entry
        
        # Возвращаемся на Outlook — ключевой момент теста!
        app._load_profile_to_widgets("Outlook")
        
        # ПРОВЕРКА: custom_time_entry должен содержать '23:00'
        # Если _update_trigger_mode_state() вызывается ПОСЛЕ insert,
        # то Entry остаётся disabled, insert игнорируется, и значение остаётся '23:00'
        # от предыдущей загрузки Outlook (что случайно правильно).
        # Но если Entry был заблокирован от Default, а insert('23:00') игнорируется,
        # то значение осталось бы от Default.
        self.assertEqual(custom_time_entry.get(), "23:00",
                        "После возврата на Outlook custom_time_entry должен содержать '23:00'")
        self.assertEqual(custom_time_entry.state, "normal",
                        "Для schedule-профиля Entry должен быть разблокирован")
        
        # Сохраняем Outlook
        app._sync_profile_widgets_to_settings("Outlook")
        self.assertEqual(app.settings["profiles"]["Outlook"]["custom_time"], "23:00",
                        "custom_time в Outlook должен остаться '23:00' после переключения")

    def test_custom_time_not_overwritten_by_schedule_change_during_load(self):
        """Проверяет, что custom_time не перезаписывается при переключении профилей
        через on_profile_selected, который вызывает save_config() после загрузки."""
        app = BackupApp(self.mock_root)
        
        # Настраиваем профили
        app.settings["profiles"]["Outlook"] = {
            "source_dirs": ["C:/Test"],
            "backup_dir": "D:/Backup",
            "skip_links": True,
            "trigger_mode": "schedule",
            "backup_schedule": "Custom",
            "custom_time": "23:00",
            "exclude_patterns": "",
            "enabled": True,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
        }
        
        app.settings["profiles"]["Default"] = {
            "source_dirs": [],
            "backup_dir": "",
            "skip_links": True,
            "trigger_mode": "schedule",
            "backup_schedule": "Weekly",
            "custom_time": "10",
            "exclude_patterns": "",
            "enabled": False,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
        }
        
        # Мокаем виджеты
        app.profile_widgets = self._create_full_widget_mocks()
        
        # Мокаем listbox для on_profile_selected
        app.profiles_listbox = Mock()
        app.profiles_listbox.curselection = Mock(return_value=[0])
        app.profiles_listbox.get = Mock(side_effect=lambda idx: ["Default", "Outlook"][idx])
        
        # Мокаем методы обновления UI
        app._update_trigger_mode_state = Mock()
        app._update_schedule_visibility = Mock()
        app.update_profile_status = Mock()
        app._update_custom_time_hint = Mock()
        app._refresh_log_display = Mock()
        app._update_monitoring_indicator = Mock()
        app._update_failure_listbox = Mock()
        app._start_event_monitor = Mock()
        app._stop_event_monitor = Mock()
        app._update_tabs_state = Mock()
        
        # Начинаем с Default
        app.current_profile_name = "Default"
        
        # Устанавливаем начальное значение _value для schedule_var
        app.profile_widgets["schedule_var"]._value = "Weekly"
        app.profile_widgets["schedule_var"].get = lambda: getattr(app.profile_widgets["schedule_var"], '_value', 'None')
        
        app.profile_widgets["custom_time_entry"].get.return_value = "10"
        
        # Сохраняем Default
        app._sync_profile_widgets_to_settings("Default")
        
        # Переключаемся на Outlook через on_profile_selected
        app.profiles_listbox.get = Mock(return_value="Outlook")
        
        # Мокаем save_config, чтобы избежать реальной записи в файл
        app.save_config = Mock()
        
        # Эмулируем, что при загрузке Outlook виджеты обновляются правильно
        # но schedule_var.set() триггерит callback, который сохраняет настройки
        original_schedule_var = app.profile_widgets["schedule_var"]
        original_custom_time_entry = app.profile_widgets["custom_time_entry"]
        
        # Счётчик вызовов для отслеживания порядка
        call_order = []
        
        def mock_schedule_set(value):
            call_order.append(f"schedule_set({value})")
            original_schedule_var._value = value
            # Эмулируем <<ComboboxSelected>> → schedule_changed → save_current_profile_settings
            # В этот момент custom_time_entry ещё содержит "10" от Default!
            call_order.append("schedule_changed_callback")
            app.save_current_profile_settings()
        
        def mock_custom_time_get():
            call_order.append(f"custom_time_get() -> {original_custom_time_entry._value}")
            return original_custom_time_entry._value
        
        def mock_custom_time_insert(index, text):
            call_order.append(f"custom_time_insert({text})")
            original_custom_time_entry._value = text
        
        app.profile_widgets["schedule_var"].set = mock_schedule_set
        app.profile_widgets["schedule_var"].get = lambda: getattr(app.profile_widgets["schedule_var"], '_value', 'None')
        app.profile_widgets["custom_time_entry"].get = mock_custom_time_get
        app.profile_widgets["custom_time_entry"].insert = mock_custom_time_insert
        app.profile_widgets["custom_time_entry"]._value = "10"  # Начальное значение от Default
        
        # Вызываем on_profile_selected
        app.on_profile_selected()
        
        # Проверяем порядок вызовов
        print("\nПорядок вызовов:")
        for i, call in enumerate(call_order, 1):
            print(f"{i}. {call}")
        
        # Проверяем, что custom_time в Outlook НЕ изменился
        self.assertEqual(app.settings["profiles"]["Outlook"]["custom_time"], "23:00",
                        f"custom_time был перезаписан! Порядок вызовов: {call_order}")
        
    def test_custom_time_preserved_on_real_config_switch(self):
        """Проверяет, что custom_time не меняется при переключении между профилями с реальным конфигом."""
        # Записываем реальный конфиг пользователя
        config = {
            "global": {
                "autorun": False,
                "start_minimized": True,
                "log_to_file": True,
                "active_profile": "Outlook",
                "theme": "dark",
                "errors_last_read_pos": 1353,
                "profiles_collapsed": False
            },
            "profiles": {
                "Default": {
                    "source_dirs": ["C:/Users/aantonov/Documents/aantonov-documents"],
                    "backup_dir": "O:/",
                    "skip_links": True,
                    "backup_schedule": "Weekly",
                    "custom_time": "10",
                    "exclude_patterns": "~$, *.tmp",
                    "auto_start_backup": True,
                    "enabled": True,
                    "weekly_days": ["Monday"],
                    "weekly_time": "23:00",
                    "process_control": {
                        "enabled": False,
                        "close_before": [],
                        "close_mode": "graceful_then_force",
                        "graceful_timeout_sec": 10,
                        "on_close_failure": "abort",
                        "restore_after": "only_if_was_running"
                    },
                    "retry": {
                        "enabled": False,
                        "max_attempts": 3,
                        "interval_seconds": 300,
                        "retry_on": ["disk_unavailable", "process_close_failed", "copy_errors"],
                        "on_total_failure": []
                    },
                    "total_timeout_minutes": 0,
                    "event_filters": ["created", "modified", "deleted", "moved"],
                    "on_queue_overflow": "run_immediately",
                    "event_debounce_seconds": 5,
                    "previous_schedule": "Custom",
                    "trigger_mode": "file_change"
                },
                "Outlook": {
                    "source_dirs": ["C:/Users/aantonov/Documents/Файлы Outlook"],
                    "backup_dir": "O:/",
                    "skip_links": True,
                    "backup_schedule": "Custom",
                    "custom_time": "23:00",
                    "exclude_patterns": "~, *.tmp",
                    "enabled": True,
                    "auto_start_backup": False,
                    "weekly_days": ["Tuesday", "Friday"],
                    "weekly_time": "23:00",
                    "process_control": {
                        "enabled": True,
                        "close_before": ["OUTLOOK.EXE"],
                        "close_mode": "graceful_then_force",
                        "graceful_timeout_sec": 20,
                        "on_close_failure": "abort",
                        "restore_after": "only_if_was_running"
                    },
                    "retry": {
                        "enabled": True,
                        "max_attempts": 6,
                        "interval_seconds": 120,
                        "retry_on": ["disk_unavailable", "process_close_failed", "copy_errors", "source_missing"],
                        "on_total_failure": []
                    },
                    "total_timeout_minutes": 0,
                    "event_filters": ["created", "modified", "deleted", "moved"],
                    "on_queue_overflow": "run_immediately",
                    "event_debounce_seconds": 5,
                    "previous_schedule": "Custom",
                    "trigger_mode": "schedule"
                }
            }
        }
        
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=1)
        
        # Создаём приложение
        app = BackupApp(self.mock_root)
        
        # Проверяем, что конфиг загружен правильно
        self.assertEqual(app.settings["profiles"]["Outlook"]["custom_time"], "23:00")
        self.assertEqual(app.settings["profiles"]["Default"]["custom_time"], "10")
        
        # Мокаем виджеты
        app.profile_widgets = self._create_full_widget_mocks()
        
        # Эмулируем загрузку Outlook в виджеты
        app.current_profile_name = "Outlook"
        app.profile_widgets["schedule_var"].get.return_value = "Custom"
        app.profile_widgets["custom_time_entry"].get.return_value = "23:00"
        app.profile_widgets["trigger_mode_var"].get.return_value = "schedule"
        app.profile_widgets["source_listbox"].get.return_value = ["C:/Users/aantonov/Documents/Файлы Outlook"]
        app.profile_widgets["backup_entry"].get.return_value = "O:/"
        app.profile_widgets["exclude_entry"].get.return_value = "~, *.tmp"
        app.profile_widgets["enabled_var"].get.return_value = True
        app.profile_widgets["auto_start_backup_var"].get.return_value = False
        app.profile_widgets["weekly_time_entry"].get.return_value = "23:00"
        for day, var in app.profile_widgets["weekly_day_vars"].items():
            var.get.return_value = day in ["Tuesday", "Friday"]
        app.profile_widgets["pc_enabled_var"].get.return_value = True
        app.profile_widgets["pc_close_listbox"].get.return_value = ["OUTLOOK.EXE"]
        app.profile_widgets["pc_close_mode_var"].get.return_value = "graceful_then_force"
        app.profile_widgets["pc_graceful_timeout_var"].get.return_value = "20"
        app.profile_widgets["pc_on_close_failure_var"].get.return_value = "abort"
        app.profile_widgets["pc_restore_after_var"].get.return_value = "only_if_was_running"
        app.profile_widgets["retry_enabled_var"].get.return_value = True
        app.profile_widgets["retry_max_attempts_var"].get.return_value = "6"
        app.profile_widgets["retry_interval_seconds_var"].get.return_value = "120"
        for opt, var in app.profile_widgets["retry_on_vars"].items():
            var.get.return_value = opt in ["disk_unavailable", "process_close_failed", "copy_errors", "source_missing"]
        app.profile_widgets["total_timeout_minutes_var"].get.return_value = "0"
        app.profile_widgets["event_created_var"].get.return_value = True
        app.profile_widgets["event_deleted_var"].get.return_value = True
        app.profile_widgets["event_moved_var"].get.return_value = True
        app.profile_widgets["on_overflow_var"].get.return_value = "run_immediately"
        
        # Сохраняем Outlook
        app._sync_profile_widgets_to_settings("Outlook")
        self.assertEqual(app.settings["profiles"]["Outlook"]["custom_time"], "23:00")
        
        # Эмулируем переключение на Default
        app.current_profile_name = "Default"
        app.profile_widgets["schedule_var"].get.return_value = "Weekly"
        app.profile_widgets["custom_time_entry"].get.return_value = "10"  # Мусорное значение от Default
        app.profile_widgets["trigger_mode_var"].get.return_value = "file_change"
        app.profile_widgets["source_listbox"].get.return_value = ["C:/Users/aantonov/Documents/aantonov-documents"]
        app.profile_widgets["backup_entry"].get.return_value = "O:/"
        app.profile_widgets["exclude_entry"].get.return_value = "~$, *.tmp"
        app.profile_widgets["enabled_var"].get.return_value = True
        app.profile_widgets["auto_start_backup_var"].get.return_value = True
        app.profile_widgets["weekly_time_entry"].get.return_value = "23:00"
        for day, var in app.profile_widgets["weekly_day_vars"].items():
            var.get.return_value = day in ["Monday"]
        app.profile_widgets["pc_enabled_var"].get.return_value = False
        app.profile_widgets["pc_close_listbox"].get.return_value = []
        app.profile_widgets["pc_close_mode_var"].get.return_value = "graceful_then_force"
        app.profile_widgets["pc_graceful_timeout_var"].get.return_value = "10"
        app.profile_widgets["pc_on_close_failure_var"].get.return_value = "abort"
        app.profile_widgets["pc_restore_after_var"].get.return_value = "only_if_was_running"
        app.profile_widgets["retry_enabled_var"].get.return_value = False
        app.profile_widgets["retry_max_attempts_var"].get.return_value = "3"
        app.profile_widgets["retry_interval_seconds_var"].get.return_value = "300"
        for opt, var in app.profile_widgets["retry_on_vars"].items():
            var.get.return_value = opt in ["disk_unavailable", "process_close_failed", "copy_errors"]
        app.profile_widgets["total_timeout_minutes_var"].get.return_value = "0"
        app.profile_widgets["event_created_var"].get.return_value = True
        app.profile_widgets["event_deleted_var"].get.return_value = True
        app.profile_widgets["event_moved_var"].get.return_value = True
        app.profile_widgets["on_overflow_var"].get.return_value = "run_immediately"
        
        # Сохраняем Default
        app._sync_profile_widgets_to_settings("Default")
        
        # Проверяем, что custom_time в Outlook НЕ изменился
        self.assertEqual(app.settings["profiles"]["Outlook"]["custom_time"], "23:00")
        
        # Эмулируем переключение обратно на Outlook
        app.current_profile_name = "Outlook"
        app.profile_widgets["schedule_var"].get.return_value = "Custom"
        app.profile_widgets["custom_time_entry"].get.return_value = "23:00"  # Должно быть 23:00 после загрузки Outlook
        app.profile_widgets["trigger_mode_var"].get.return_value = "schedule"
        app.profile_widgets["source_listbox"].get.return_value = ["C:/Users/aantonov/Documents/Файлы Outlook"]
        app.profile_widgets["backup_entry"].get.return_value = "O:/"
        app.profile_widgets["exclude_entry"].get.return_value = "~, *.tmp"
        app.profile_widgets["enabled_var"].get.return_value = True
        app.profile_widgets["auto_start_backup_var"].get.return_value = False
        app.profile_widgets["weekly_time_entry"].get.return_value = "23:00"
        for day, var in app.profile_widgets["weekly_day_vars"].items():
            var.get.return_value = day in ["Tuesday", "Friday"]
        app.profile_widgets["pc_enabled_var"].get.return_value = True
        app.profile_widgets["pc_close_listbox"].get.return_value = ["OUTLOOK.EXE"]
        app.profile_widgets["pc_close_mode_var"].get.return_value = "graceful_then_force"
        app.profile_widgets["pc_graceful_timeout_var"].get.return_value = "20"
        app.profile_widgets["pc_on_close_failure_var"].get.return_value = "abort"
        app.profile_widgets["pc_restore_after_var"].get.return_value = "only_if_was_running"
        app.profile_widgets["retry_enabled_var"].get.return_value = True
        app.profile_widgets["retry_max_attempts_var"].get.return_value = "6"
        app.profile_widgets["retry_interval_seconds_var"].get.return_value = "120"
        for opt, var in app.profile_widgets["retry_on_vars"].items():
            var.get.return_value = opt in ["disk_unavailable", "process_close_failed", "copy_errors", "source_missing"]
        app.profile_widgets["total_timeout_minutes_var"].get.return_value = "0"
        app.profile_widgets["event_created_var"].get.return_value = True
        app.profile_widgets["event_deleted_var"].get.return_value = True
        app.profile_widgets["event_moved_var"].get.return_value = True
        app.profile_widgets["on_overflow_var"].get.return_value = "run_immediately"
        
        # Сохраняем Outlook
        app._sync_profile_widgets_to_settings("Outlook")
        
        # Проверяем, что custom_time в Outlook всё ещё "23:00"
        self.assertEqual(app.settings["profiles"]["Outlook"]["custom_time"], "23:00")

    def test_load_profile_to_widgets_sets_custom_time(self):
        """Проверяет, что _load_profile_to_widgets правильно загружает custom_time в виджет."""
        app = BackupApp(self.mock_root)
        
        # Настраиваем профили
        app.settings["profiles"]["Outlook"] = {
            "source_dirs": [],
            "backup_dir": "",
            "skip_links": True,
            "trigger_mode": "schedule",
            "backup_schedule": "Custom",
            "custom_time": "23:00",
            "exclude_patterns": "",
            "enabled": False,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
        }
        
        app.settings["profiles"]["Default"] = {
            "source_dirs": [],
            "backup_dir": "",
            "skip_links": True,
            "trigger_mode": "schedule",
            "backup_schedule": "Weekly",
            "custom_time": "10",
            "exclude_patterns": "",
            "enabled": False,
            "auto_start_backup": False,
            "weekly_days": ["Monday"],
            "weekly_time": "23:00",
        }
        
        # Создаём умные моки для виджетов
        custom_time_entry = MockEntry()
        weekly_time_entry = MockEntry()
        backup_entry = MockEntry()
        exclude_entry = MockEntry()
        
        # Настраиваем source_listbox с поддержкой insert/delete
        source_listbox = Mock()
        source_listbox._items = []
        source_listbox.delete = Mock(side_effect=lambda *a: source_listbox._items.clear())
        source_listbox.insert = Mock(side_effect=lambda idx, val: source_listbox._items.append(val))
        source_listbox.get = Mock(side_effect=lambda *a: list(source_listbox._items))
        
        app.profile_widgets = {
            "enabled_var": Mock(),
            "source_listbox": source_listbox,
            "backup_entry": backup_entry,
            "skip_links_var": Mock(),
            "auto_start_backup_var": Mock(),
            "trigger_mode_var": Mock(),
            "schedule_var": Mock(),
            "schedule_menu": Mock(),
            "custom_time_entry": custom_time_entry,
            "weekly_time_entry": weekly_time_entry,
            "exclude_entry": exclude_entry,
            "weekly_days_frame": Mock(),
            "weekly_day_vars": {
                "Monday": Mock(),
                "Tuesday": Mock(),
                "Wednesday": Mock(),
                "Thursday": Mock(),
                "Friday": Mock(),
                "Saturday": Mock(),
                "Sunday": Mock(),
            },
            "event_created_var": Mock(),
            "event_modified_var": Mock(),
            "event_deleted_var": Mock(),
            "event_moved_var": Mock(),
            "on_overflow_var": Mock(),
            "pc_enabled_var": Mock(),
            "pc_close_listbox": Mock(),
            "pc_close_mode_var": Mock(),
            "pc_graceful_timeout_var": Mock(),
            "pc_on_close_failure_var": Mock(),
            "pc_restore_after_var": Mock(),
            "retry_enabled_var": Mock(),
            "retry_max_attempts_var": Mock(),
            "retry_interval_seconds_var": Mock(),
            "retry_on_vars": {},
            "retry_failure_listbox": Mock(),
            "total_timeout_minutes_var": Mock(),
        }
        
        # Настраиваем winfo_children для weekly_days_frame
        app.profile_widgets["weekly_days_frame"].winfo_children.return_value = []
        
        # Мокаем методы
        app.profile_widgets["pc_close_listbox"].delete = Mock()
        app.profile_widgets["pc_close_listbox"].insert = Mock()
        app.profile_widgets["retry_failure_listbox"].delete = Mock()
        app.profile_widgets["retry_failure_listbox"].insert = Mock()
        
        # ВАЖНО: _update_trigger_mode_state НЕ мокаем — он должен работать реально,
        # чтобы управлять состоянием custom_time_entry (disabled/normal).
        app._update_schedule_visibility = Mock()
        app.update_profile_status = Mock()
        app._update_custom_time_hint = Mock()
        app._refresh_log_display = Mock()
        app._update_monitoring_indicator = Mock()
        app._update_failure_listbox = Mock()
        app._start_event_monitor = Mock()
        app._stop_event_monitor = Mock()
        
        # Загружаем Outlook
        app._load_profile_to_widgets("Outlook")
        self.assertEqual(custom_time_entry.get(), "23:00")
        
        # Загружаем Default
        app._load_profile_to_widgets("Default")
        self.assertEqual(custom_time_entry.get(), "10")
        
        # Загружаем Outlook снова
        app._load_profile_to_widgets("Outlook")
        self.assertEqual(custom_time_entry.get(), "23:00")


if __name__ == "__main__":
    unittest.main()