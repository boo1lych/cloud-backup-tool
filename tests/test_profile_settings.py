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
            "custom_time_entry": Mock(),
            "exclude_entry": Mock(),
            "enabled_var": Mock(),
            "auto_start_backup_var": Mock(),
            "weekly_time_entry": Mock(),
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
            "event_deleted_var": Mock(),
            "event_moved_var": Mock(),
            "on_overflow_var": Mock(),
        }
        
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
        
        app.profile_widgets = {
            "source_listbox": Mock(),
            "backup_entry": Mock(),
            "skip_links_var": Mock(),
            "trigger_mode_var": Mock(),
            "schedule_var": Mock(),
            "custom_time_entry": Mock(),
            "exclude_entry": Mock(),
            "enabled_var": Mock(),
            "auto_start_backup_var": Mock(),
            "weekly_time_entry": Mock(),
            "weekly_day_vars": {},
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
            "total_timeout_minutes_var": Mock(),
            "event_created_var": Mock(),
            "event_deleted_var": Mock(),
            "event_moved_var": Mock(),
            "on_overflow_var": Mock(),
        }
        
        # Настраиваем моки
        app.profile_widgets["source_listbox"].get.return_value = []
        app.profile_widgets["backup_entry"].get.return_value = ""
        app.profile_widgets["skip_links_var"].get.return_value = True
        app.profile_widgets["trigger_mode_var"].get.return_value = "schedule"
        app.profile_widgets["schedule_var"].get.return_value = "Custom"
        app.profile_widgets["custom_time_entry"].get.return_value = "21:30"
        app.profile_widgets["exclude_entry"].get.return_value = ""
        app.profile_widgets["enabled_var"].get.return_value = False
        app.profile_widgets["auto_start_backup_var"].get.return_value = False
        app.profile_widgets["weekly_time_entry"].get.return_value = "23:00"
        app.profile_widgets["pc_enabled_var"].get.return_value = False
        app.profile_widgets["pc_close_listbox"].get.return_value = []
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
        app.profile_widgets["on_overflow_var"].get.return_value = "run_immediately"
        
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
        
        app.profile_widgets = {
            "source_listbox": Mock(),
            "backup_entry": Mock(),
            "skip_links_var": Mock(),
            "trigger_mode_var": Mock(),
            "schedule_var": Mock(),
            "custom_time_entry": Mock(),
            "exclude_entry": Mock(),
            "enabled_var": Mock(),
            "auto_start_backup_var": Mock(),
            "weekly_time_entry": Mock(),
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
            "retry_on_vars": {},
            "total_timeout_minutes_var": Mock(),
            "event_created_var": Mock(),
            "event_deleted_var": Mock(),
            "event_moved_var": Mock(),
            "on_overflow_var": Mock(),
        }
        
        # Настраиваем моки
        app.profile_widgets["source_listbox"].get.return_value = []
        app.profile_widgets["backup_entry"].get.return_value = ""
        app.profile_widgets["skip_links_var"].get.return_value = True
        app.profile_widgets["trigger_mode_var"].get.return_value = "schedule"
        app.profile_widgets["schedule_var"].get.return_value = "Weekly"
        app.profile_widgets["custom_time_entry"].get.return_value = ""
        app.profile_widgets["exclude_entry"].get.return_value = ""
        app.profile_widgets["enabled_var"].get.return_value = False
        app.profile_widgets["auto_start_backup_var"].get.return_value = False
        app.profile_widgets["weekly_time_entry"].get.return_value = "18:30"
        
        # Настраиваем дни недели
        for day, var in app.profile_widgets["weekly_day_vars"].items():
            var.get.return_value = day in ["Monday", "Friday"]
        
        app.profile_widgets["pc_enabled_var"].get.return_value = False
        app.profile_widgets["pc_close_listbox"].get.return_value = []
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
        app.profile_widgets["on_overflow_var"].get.return_value = "run_immediately"
        
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


if __name__ == "__main__":
    unittest.main()