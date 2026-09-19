"""Модуль отправки уведомлений об ошибках бэкапа в VK Teams (Mail.ru)."""
import os
import sys
import json
import logging
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from urllib.parse import quote

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "error_notifications.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "error_notifications.log")
MAX_MESSAGE_LENGTH = 3800
MAX_DETAILS_LINES = 10

os.makedirs(LOG_DIR, exist_ok=True)

# --- Логгер для ошибок отправки ---
_notifier_logger = logging.getLogger("error_notifier")
_notifier_logger.setLevel(logging.INFO)
_notifier_logger.propagate = False
_notifier_logger.handlers.clear()
_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=2 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
_notifier_logger.addHandler(_handler)


def load_config():
    """Загружает конфигурацию уведомлений. Возвращает dict."""
    if not os.path.exists(CONFIG_FILE):
        return {"enabled": False, "bot_token": "", "chat_ids": []}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("enabled", False)
        data.setdefault("bot_token", "")
        data.setdefault("chat_ids", [])
        return data
    except Exception as e:
        _notifier_logger.warning(f"Failed to load config: {e}")
        return {"enabled": False, "bot_token": "", "chat_ids": []}


def save_config(cfg):
    """Сохраняет конфигурацию уведомлений."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        _notifier_logger.warning(f"Failed to save config: {e}")
        return False


def _send_to_chats(text):
    """Отправляет текст во все настроенные чаты. Не бросает исключений."""
    cfg = load_config()
    if not cfg.get("enabled", False):
        _notifier_logger.info("Notifications disabled in config")
        return False
    bot_token = (cfg.get("bot_token") or "").strip()
    chat_ids = cfg.get("chat_ids") or []
    if not bot_token:
        _notifier_logger.warning("bot_token is empty")
        return False
    if not chat_ids:
        _notifier_logger.warning("chat_ids list is empty")
        return False

    # Обрезаем до лимита VK Teams
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH - 60] + "\n\n... (message truncated due to length limit)"

    try:
        import requests
    except ImportError:
        _notifier_logger.warning("Module 'requests' is not installed. Cannot send notifications.")
        return False

    sent_any = False
    for chat_id in chat_ids:
        url = (
            f"https://myteam.mail.ru/bot/v1/messages/sendText"
            f"?token={bot_token}"
            f"&chatId={quote(str(chat_id))}"
            f"&text={quote(text)}"
        )
        try:
            resp = requests.get(url, timeout=15, verify=False)
            if resp.status_code == 200:
                sent_any = True
                _notifier_logger.info(f"Sent to chat {chat_id}")
            else:
                _notifier_logger.warning(
                    f"HTTP {resp.status_code} for chat {chat_id}: {resp.text[:150]}"
                )
        except Exception as e:
            _notifier_logger.warning(f"Send error for chat {chat_id}: {e}")
    return sent_any


def _format_details_block(details, header="🔻 Подробности"):
    """Формирует блок с подробностями (список файлов/ошибок)."""
    if not details:
        return ""
    lines = [f"{header} ({len(details)}):"]
    shown = details[:MAX_DETAILS_LINES]
    for d in shown:
        lines.append(f"  • {d}")
    if len(details) > MAX_DETAILS_LINES:
        lines.append(f"  ... и ещё {len(details) - MAX_DETAILS_LINES} файлов")
    return "\n".join(lines)


def send_test_message():
    """Отправляет тестовое сообщение. Возвращает (ok, message)."""
    cfg = load_config()
    if not cfg.get("enabled", False):
        return False, "Notifications disabled in config"
    bot_token = (cfg.get("bot_token") or "").strip()
    chat_ids = cfg.get("chat_ids") or []
    if not bot_token:
        return False, "bot_token is empty"
    if not chat_ids:
        return False, "chat_ids list is empty"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = (
        f"✅ Test message from Cloud Backup Tool\n"
        f"⏰ Time: {now_str}\n"
        f"🔧 Bot configuration is working correctly"
    )
    ok = _send_to_chats(text)
    if ok:
        return True, "Test message sent successfully"
    return False, "Failed to send test message (see logs/error_notifications.log)"


def send_pre_backup_alert(profile_name, error_type, error_message, details=None):
    """Отправляет алерт для ошибок, возникших ДО запуска run_backup()
    (например, disk_unavailable, low_disk_space)."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"🚨 Ошибка: {error_type}",
        f"📁 Профиль: {profile_name}",
        f"📝 Детали: {error_message}",
    ]
    if details:
        lines.append("")
        lines.append(_format_details_block(details))
    lines.append(f"⏰ Время: {now_str}")
    text = "\n".join(lines)
    try:
        _send_to_chats(text)
    except Exception as e:
        _notifier_logger.warning(f"send_pre_backup_alert error: {e}")


def send_session_alert(profile_name, session_errors, outcome,
                       successful_attempt=None, total_timeout_minutes=None,
                       elapsed_minutes=None):
    """Отправляет агрегированный алерт по итогам сеанса run_backup().
    
    Args:
        profile_name: имя профиля
        session_errors: список словарей с ошибками сеанса
            [{"error_type", "error_message", "attempt", "max_attempts", "details"}, ...]
        outcome: "total_failure" | "success_after_retry" | "timeout"
        successful_attempt: номер попытки, на которой завершилось успешно (для success_after_retry)
        total_timeout_minutes: лимит таймаута (для timeout)
        elapsed_minutes: фактическое время (для timeout)
    """
    if not session_errors:
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []

    if outcome == "timeout":
        lines.append("⏱️ Таймаут: бэкап превысил лимит времени")
        lines.append(f"📁 Профиль: {profile_name}")
        if total_timeout_minutes is not None:
            lines.append(f"⏰ Лимит: {total_timeout_minutes} минут")
        if elapsed_minutes is not None:
            lines.append(f"⏰ Фактически: {elapsed_minutes:.1f} минут")
        lines.append("")
        lines.append("🔻 Ошибки в ходе выполнения:")
        for err in session_errors:
            attempt_str = f"{err['attempt']}/{err['max_attempts']}"
            lines.append(f"  • Попытка {attempt_str}: {err['error_type']} — {err['error_message']}")
        lines.append(f"⏰ Время: {now_str}")

    elif outcome == "success_after_retry":
        lines.append("⚠️ Бэкап завершён успешно (были ошибки)")
        lines.append(f"📁 Профиль: {profile_name}")
        lines.append("")
        lines.append("🔻 Ошибки в ходе выполнения:")
        for err in session_errors:
            attempt_str = f"{err['attempt']}/{err['max_attempts']}"
            lines.append(f"  • Попытка {attempt_str}: {err['error_type']} — {err['error_message']}")
        lines.append("")
        if successful_attempt is not None:
            max_att = session_errors[0]["max_attempts"] if session_errors else "?"
            lines.append(f"✅ Итог: бэкап успешно завершён на попытке {successful_attempt}/{max_att}")
        lines.append(f"⏰ Время: {now_str}")

    elif outcome == "total_failure":
        # Берём последнюю ошибку как основную
        last_err = session_errors[-1]
        lines.append(f"🚨 Ошибка: {last_err['error_type']}")
        lines.append(f"📁 Профиль: {profile_name}")
        lines.append(f"📝 Детали: {last_err['error_message']}")
        # Собираем все details из всех ошибок сеанса
        all_details = []
        for err in session_errors:
            if err.get("details"):
                all_details.extend(err["details"])
        if all_details:
            lines.append("")
            lines.append(_format_details_block(all_details))
        attempt_str = f"{last_err['attempt']}/{last_err['max_attempts']}"
        lines.append(f"⏰ Время: {now_str}")
        lines.append(f"🔄 Попытка: {attempt_str}")

    else:
        return

    text = "\n".join(lines)
    try:
        _send_to_chats(text)
    except Exception as e:
        _notifier_logger.warning(f"send_session_alert error: {e}")