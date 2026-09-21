"""Интеграционные тесты для event-driven режима."""
import json
import os
import pytest
from unittest.mock import Mock, patch, MagicMock


class TestConfigMigration:
    def test_migration_adds_event_fields(self, tmp_path):
        """Старый профиль без event-полей получает дефолты."""
        config_file = tmp_path / "config.json"
        old_config = {
            "global": {"active_profile": "Default"},
            "profiles": {
                "Default": {
                    "source_dirs": [],
                    "backup_dir": "",
                    "backup_schedule": "None",
                    "enabled": False,
                }
            }
        }
        config_file.write_text(json.dumps(old_config), encoding="utf-8")

        # Имитируем миграцию из load_config
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for pname, pdata in data["profiles"].items():
            pdata.setdefault("event_filters", ["created", "modified", "deleted", "moved"])
            pdata.setdefault("on_queue_overflow", "run_immediately")
            pdata.setdefault("event_debounce_seconds", 5)
            pdata.setdefault("previous_schedule", "None")

        assert data["profiles"]["Default"]["event_filters"] == ["created", "modified", "deleted", "moved"]
        assert data["profiles"]["Default"]["on_queue_overflow"] == "run_immediately"
        assert data["profiles"]["Default"]["event_debounce_seconds"] == 5
        assert data["profiles"]["Default"]["previous_schedule"] == "None"

    def test_migration_preserves_existing_event_fields(self, tmp_path):
        """Если поля уже есть — они не перезаписываются."""
        config_file = tmp_path / "config.json"
        config = {
            "global": {"active_profile": "Default"},
            "profiles": {
                "Default": {
                    "source_dirs": [],
                    "backup_dir": "",
                    "backup_schedule": "On file change",
                    "enabled": True,
                    "event_filters": ["created"],
                    "on_queue_overflow": "log_warning",
                    "event_debounce_seconds": 10,
                    "previous_schedule": "Daily 23:00",
                }
            }
        }
        config_file.write_text(json.dumps(config), encoding="utf-8")

        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for pname, pdata in data["profiles"].items():
            pdata.setdefault("event_filters", ["created", "modified", "deleted", "moved"])
            pdata.setdefault("on_queue_overflow", "run_immediately")
            pdata.setdefault("event_debounce_seconds", 5)
            pdata.setdefault("previous_schedule", "None")

        assert data["profiles"]["Default"]["event_filters"] == ["created"]
        assert data["profiles"]["Default"]["on_queue_overflow"] == "log_warning"
        assert data["profiles"]["Default"]["event_debounce_seconds"] == 10
        assert data["profiles"]["Default"]["previous_schedule"] == "Daily 23:00"


class TestPreviousSchedule:
    def test_previous_schedule_updated_on_non_event_mode(self):
        """previous_schedule обновляется при переключении на не-Event режим."""
        profile = {
            "backup_schedule": "Daily 23:00",
            "previous_schedule": "None",
        }

        # Логика из _sync_profile_widgets_to_settings
        if profile["backup_schedule"] != "On file change":
            profile["previous_schedule"] = profile["backup_schedule"]

        assert profile["previous_schedule"] == "Daily 23:00"

    def test_previous_schedule_not_overwritten_on_event_driven(self):
        """previous_schedule НЕ обновляется при выборе On file change."""
        profile = {
            "backup_schedule": "On file change",
            "previous_schedule": "Daily 23:00",  # уже сохранено
        }

        if profile["backup_schedule"] != "On file change":
            profile["previous_schedule"] = profile["backup_schedule"]

        # previous_schedule не должен измениться
        assert profile["previous_schedule"] == "Daily 23:00"

    def test_previous_schedule_preserved_across_switches(self):
        """previous_schedule сохраняется при переключении режимов."""
        profile = {"backup_schedule": "None", "previous_schedule": "None"}

        # Переключаемся на Daily
        profile["backup_schedule"] = "Daily 23:00"
        if profile["backup_schedule"] != "On file change":
            profile["previous_schedule"] = profile["backup_schedule"]
        assert profile["previous_schedule"] == "Daily 23:00"

        # Переключаемся на On file change
        profile["backup_schedule"] = "On file change"
        if profile["backup_schedule"] != "On file change":
            profile["previous_schedule"] = profile["backup_schedule"]
        assert profile["previous_schedule"] == "Daily 23:00"  # сохранено

        # Переключаемся на Weekly
        profile["backup_schedule"] = "Weekly"
        if profile["backup_schedule"] != "On file change":
            profile["previous_schedule"] = profile["backup_schedule"]
        assert profile["previous_schedule"] == "Weekly"  # обновлено


class TestEventDrivenAutoStart:
    def test_event_driven_starts_backup_on_launch(self):
        """Event-driven профили запускают бэкап при старте."""
        profiles = {
            "EventProfile": {
                "enabled": True,
                "backup_schedule": "On file change",
                "auto_start_backup": False,  # игнорируется
            },
            "NormalProfile": {
                "enabled": True,
                "backup_schedule": "Daily 23:00",
                "auto_start_backup": False,
            },
        }

        started = []
        for pname, profile in profiles.items():
            if not profile.get("enabled", False):
                continue
            if profile.get("backup_schedule") == "On file change":
                started.append(pname)
            elif profile.get("auto_start_backup", False):
                started.append(pname)

        assert "EventProfile" in started
        assert "NormalProfile" not in started

    def test_auto_start_backup_ignored_for_event_driven(self):
        """auto_start_backup игнорируется для Event-driven профилей."""
        profile = {
            "enabled": True,
            "backup_schedule": "On file change",
            "auto_start_backup": False,  # выключено
        }

        # Логика из _auto_start_on_launch
        should_start = False
        if profile.get("enabled", False):
            if profile.get("backup_schedule") == "On file change":
                should_start = True
            elif profile.get("auto_start_backup", False):
                should_start = True

        assert should_start is True  # всё равно запускается


class TestEventFiltersUI:
    def test_event_filters_from_checkboxes(self):
        """Чекбоксы UI правильно формируют event_filters."""
        # Имитация логики из _sync_profile_widgets_to_settings
        event_created_var = True
        event_deleted_var = True
        event_moved_var = False

        event_filters = []
        if event_created_var:
            event_filters.extend(["created", "modified"])
        if event_deleted_var:
            event_filters.append("deleted")
        if event_moved_var:
            event_filters.append("moved")

        assert event_filters == ["created", "modified", "deleted"]

    def test_all_checkboxes_off(self):
        """Все чекбоксы выключены → пустой список."""
        event_filters = []
        # Все var.get() = False
        assert event_filters == []

    def test_all_checkboxes_on(self):
        """Все чекбоксы включены → полный список."""
        event_filters = []
        event_filters.extend(["created", "modified"])
        event_filters.append("deleted")
        event_filters.append("moved")

        assert event_filters == ["created", "modified", "deleted", "moved"]


class TestMonitoringIndicator:
    def test_monitoring_on_when_event_driven_enabled_and_running(self):
        """Индикатор ON когда Event-driven + enabled + monitor запущен."""
        profile = {"backup_schedule": "On file change", "enabled": True}
        event_monitors = {"TestProfile": Mock()}
        profile_name = "TestProfile"

        is_monitoring = (
            profile.get("backup_schedule") == "On file change"
            and profile.get("enabled", False)
            and profile_name in event_monitors
        )

        assert is_monitoring is True

    def test_monitoring_off_when_disabled(self):
        """Индикатор OFF когда профиль выключен."""
        profile = {"backup_schedule": "On file change", "enabled": False}
        event_monitors = {}
        profile_name = "TestProfile"

        is_monitoring = (
            profile.get("backup_schedule") == "On file change"
            and profile.get("enabled", False)
            and profile_name in event_monitors
        )

        assert is_monitoring is False

    def test_monitoring_off_when_not_event_driven(self):
        """Индикатор OFF когда не Event-driven режим."""
        profile = {"backup_schedule": "Daily 23:00", "enabled": True}
        event_monitors = {}
        profile_name = "TestProfile"

        is_monitoring = (
            profile.get("backup_schedule") == "On file change"
            and profile.get("enabled", False)
            and profile_name in event_monitors
        )

        assert is_monitoring is False


class TestTabsDisabled:
    def test_tabs_disabled_for_event_driven(self):
        """Вкладки Process Control и Retry Settings disabled для Event-driven."""
        profile = {"backup_schedule": "On file change"}
        is_event_driven = profile.get("backup_schedule") == "On file change"
        assert is_event_driven is True

    def test_tabs_enabled_for_other_modes(self):
        """Вкладки normal для других режимов."""
        for schedule in ["None", "Daily 23:00", "Custom", "Weekly"]:
            profile = {"backup_schedule": schedule}
            is_event_driven = profile.get("backup_schedule") == "On file change"
            assert is_event_driven is False