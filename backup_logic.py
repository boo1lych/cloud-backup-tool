# backup_logic.py
"""Чистая бизнес-логика бэкапа, отделённая от UI для тестируемости.

Все функции в этом модуле не зависят от Tkinter и могут быть
протестированы без создания графического интерфейса.
"""

import os
import shutil
import fnmatch
import ctypes

FORBIDDEN_PROFILE_CHARS = '<>:"/\\|?*'
RESERVED_PROFILE_NAMES = (
    {'CON', 'PRN', 'AUX', 'NUL'}
    | {f'COM{i}' for i in range(1, 10)}
    | {f'LPT{i}' for i in range(1, 10)}
)


def validate_profile_name(name):
    """Проверяет, можно ли использовать name как имя профиля (и имя файла лога).
    Возвращает (ok: bool, error_message: str).
    """
    if not name or not name.strip():
        return False, "Name cannot be empty"
    stripped = name.strip()
    for ch in FORBIDDEN_PROFILE_CHARS:
        if ch in stripped:
            return False, f"Character '{ch}' is not allowed in profile name"
    if all(c in '. ' for c in stripped):
        return False, "Name cannot consist only of dots and spaces"
    base = stripped.rstrip('. ')
    if base.upper() in RESERVED_PROFILE_NAMES:
        return False, f"Name '{base}' is reserved by Windows"
    return True, ""


def is_reparse_point(path):
    """Проверяет, является ли путь точкой повторной обработки (симлинк, джанкшн)."""
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return False
        FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
        return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:
        return False


def validate_custom_time(custom):
    """Проверяет значение custom_time. Возвращает (ok, error_message)."""
    custom = custom.strip()
    if ":" in custom:
        parts = custom.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return True, ""
            return False, "Time out of range (use 00:00 - 23:59)"
        return False, "Invalid time format (use HH:MM)"
    if custom.isdigit():
        if int(custom) == 0:
            return False, "Interval must be greater than 0"
        return True, " "
    if not custom:
        return False, "Value is empty (use HH:MM or minutes)"
    return False, "Invalid value (use HH:MM or minutes)"


def validate_hhmm(time_str):
    """Проверяет время в формате HH:MM. Возвращает (ok, error_message)."""
    time_str = time_str.strip()
    if ":" not in time_str:
        return False, "Invalid time format (use HH:MM)"
    parts = time_str.split(":")
    if len(parts) != 2:
        return False, "Invalid time format (use HH:MM)"
    if not parts[0].isdigit() or not parts[1].isdigit():
        return False, "Invalid time format (use HH:MM)"
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23):
        return False, "Hours out of range (use 00-23)"
    if not (0 <= m <= 59):
        return False, "Minutes out of range (use 00-59)"
    return True, ""


def backup_saves(source_dir, backup_dir, skip_links, exclude_patterns_str,
all_sources_in_profile, state, log=None):
    """Копирует файлы из источника в приёмник.

    Параметры:
        source_dir: путь к исходной папке.
        backup_dir: путь к целевой папке.
        skip_links: пропускать ли символические ссылки.
        exclude_patterns_str: строка с паттернами исключений через запятую.
        all_sources_in_profile: список всех источников профиля
            (для определения имени папки при конфликте имён).
        state: словарь состояния профиля (используется поле "stop_flag").
        log: опциональный колбэк для логирования, принимает строку.

    Возвращает словарь со статистикой:
        files_copied, files_skipped, total_size_mb, errors, copied_files.
    """
    if not os.path.exists(source_dir):
        if log:
            log(f"Source directory does not exist: {source_dir}")
        return {
            "files_copied": 0,
            "files_skipped": 0,
            "total_size_mb": 0,
            "errors": 0,
            "copied_files": [],
            "error_details": [],
        }
    files_copied = 0
    files_skipped = 0
    total_size = 0
    errors = 0
    copied_files = []
    error_details = []
    exclude_patterns = [p.strip() for p in exclude_patterns_str.split(",") if p.strip()]
    normalized_patterns = []
    for p in exclude_patterns:
        if "*" in p or "?" in p:
            normalized_patterns.append(p)
        else:
            normalized_patterns.append(f"*{p}*")
    src_base = os.path.basename(os.path.normpath(source_dir))
    same_name_sources = [
        d for d in all_sources_in_profile
        if os.path.basename(os.path.normpath(d)) == src_base
    ]
    if len(same_name_sources) > 1:
        src_folder_name = os.path.normpath(source_dir)
        for ch in '<>:"/\\|?*':
            src_folder_name = src_folder_name.replace(ch, "_")
    else:
        src_folder_name = src_base
    dest_root = os.path.join(backup_dir, src_folder_name)
    os.makedirs(dest_root, exist_ok=True)

    def walk_error(err):
        nonlocal errors
        errors += 1
        error_details.append(f"Directory access error: {err}")
        if log:
            log(f"Error accessing path: {err}")

    for root, dirs, files in os.walk(source_dir, topdown=True, onerror=walk_error):
        if skip_links:
            dirs[:] = [d for d in dirs if not is_reparse_point(os.path.join(root, d))]
        rel_path = os.path.relpath(root, source_dir)
        dest_path = os.path.join(dest_root, rel_path) if rel_path != "." else dest_root
        os.makedirs(dest_path, exist_ok=True)
        for file in files:
            file_path = os.path.join(rel_path, file) if rel_path != "." else file
            if any(
                fnmatch.fnmatch(file, pattern) or fnmatch.fnmatch(file_path, pattern)
                for pattern in normalized_patterns
            ):
                files_skipped += 1
                if log:
                    log(f"Skipped (excluded by pattern): {os.path.join(root, file)}")
                continue
            if state.get("stop_flag", False):
                return {
                    "files_copied": files_copied,
                    "files_skipped": files_skipped,
                    "total_size_mb": total_size / 1024 / 1024,
                    "errors": errors,
                    "copied_files": copied_files,
                    "error_details": error_details,
                }
            src_file = os.path.join(root, file)
            dst_file = os.path.join(dest_path, file)
            if skip_links and is_reparse_point(src_file):
                files_skipped += 1
                if log:
                    log(f"Skipped (symbolic link): {src_file}")
                continue
            copy_needed = True
            if os.path.exists(dst_file):
                src_stat = os.stat(src_file)
                dst_stat = os.stat(dst_file)
                time_diff = src_stat.st_mtime - dst_stat.st_mtime
                if abs(time_diff) < 2.0 and src_stat.st_size == dst_stat.st_size:
                    copy_needed = False
                elif time_diff < 0:
                    copy_needed = False
                    if log:
                        log(f"Skipped (destination is newer): {src_file}")
            if copy_needed:
                try:
                    shutil.copy2(src_file, dst_file)
                    files_copied += 1
                    total_size += os.path.getsize(src_file)
                    copied_files.append(src_file)
                    if log:
                        log(f"Copied: {src_file}")
                except Exception as e:
                    errors += 1
                    error_details.append(f"{src_file}: {e}")
                    if log:
                        log(f"Error copying {src_file}: {str(e)}")
            else:
                files_skipped += 1
                if log:
                    log(f"Skipped (unchanged): {src_file}")
    return {
        "files_copied": files_copied,
        "files_skipped": files_skipped,
        "total_size_mb": total_size / 1024 / 1024,
        "errors": errors,
        "copied_files": copied_files,
        "error_details": error_details,
    }

def backup_changed_files(source_dirs, backup_dir, skip_links, exclude_patterns_str,
                         all_sources_in_profile, state, events, log=None):
    """Копирует только изменённые файлы из событий watchdog.
    
    Параметры:
        source_dirs: список всех source_dirs профиля
        backup_dir: путь к целевой папке
        skip_links: пропускать ли символические ссылки
        exclude_patterns_str: строка с паттернами исключений через запятую
        all_sources_in_profile: список всех источников профиля
        state: словарь состояния профиля (используется поле "stop_flag")
        events: dict с ключами:
            - changed: список путей файлов для копирования
            - deleted: список путей файлов для удаления
            - moved: список кортежей (old_path, new_path)
            - dirs_created: список путей директорий для создания
            - dirs_deleted: список путей директорий для удаления
            - dirs_moved: список кортежей (old_path, new_path)
        log: опциональный колбэк для логирования
    
    Возвращает словарь со статистикой:
        files_copied, files_deleted, files_moved, dirs_created, dirs_deleted,
        dirs_moved, total_size_mb, errors, copied_files, deleted_files, error_details
    """
    files_copied = 0
    files_deleted = 0
    files_moved = 0
    dirs_created = 0
    dirs_deleted = 0
    dirs_moved = 0
    total_size = 0
    errors = 0
    copied_files = []
    deleted_files = []
    error_details = []

    # Парсим exclude patterns
    exclude_patterns = [p.strip() for p in exclude_patterns_str.split(",") if p.strip()]
    normalized_patterns = []
    for p in exclude_patterns:
        if "*" in p or "?" in p:
            normalized_patterns.append(p)
        else:
            normalized_patterns.append(f"*{p}*")

    def is_excluded(path):
        """Проверяет, попадает ли путь под exclude patterns."""
        filename = os.path.basename(path)
        rel_path = path  # Для простоты используем полный путь
        return any(
            fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(rel_path, pattern)
            for pattern in normalized_patterns
        )

    def get_source_dir_for_path(path):
        """Определяет, к какому source_dir относится путь."""
        for src in source_dirs:
            src_norm = os.path.normpath(src)
            path_norm = os.path.normpath(path)
            if path_norm.startswith(src_norm + os.sep) or path_norm == src_norm:
                return src
        return None

    def get_dest_path(src_file, source_dir):
        """Вычисляет путь в backup_dir для файла из source_dir."""
        src_base = os.path.basename(os.path.normpath(source_dir))
        same_name_sources = [
            d for d in all_sources_in_profile
            if os.path.basename(os.path.normpath(d)) == src_base
        ]
        if len(same_name_sources) > 1:
            src_folder_name = os.path.normpath(source_dir)
            for ch in '<>:"/\\|?*':
                src_folder_name = src_folder_name.replace(ch, "_")
        else:
            src_folder_name = src_base

        rel_path = os.path.relpath(src_file, source_dir)
        return os.path.join(backup_dir, src_folder_name, rel_path)

    # ── Обработка директорий ────────────────────────────────────────────

    # Создание директорий
    for dir_path in events.get("dirs_created", []):
        if state.get("stop_flag", False):
            break
        source_dir = get_source_dir_for_path(dir_path)
        if not source_dir:
            continue
        if is_excluded(dir_path):
            if log:
                log(f"Skipped (excluded by pattern): {dir_path}")
            continue
        dest_dir = get_dest_path(dir_path, source_dir)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dirs_created += 1
            if log:
                log(f"Created dir: {dest_dir}")
        except Exception as e:
            errors += 1
            error_details.append(f"{dir_path}: {e}")
            if log:
                log(f"Error creating dir {dir_path}: {e}")

    # Удаление директорий
    for dir_path in events.get("dirs_deleted", []):
        if state.get("stop_flag", False):
            break
        source_dir = get_source_dir_for_path(dir_path)
        if not source_dir:
            continue
        if is_excluded(dir_path):
            continue
        dest_dir = get_dest_path(dir_path, source_dir)
        try:
            if os.path.exists(dest_dir):
                shutil.rmtree(dest_dir)
                dirs_deleted += 1
                if log:
                    log(f"Deleted dir: {dest_dir}")
        except Exception as e:
            errors += 1
            error_details.append(f"{dir_path}: {e}")
            if log:
                log(f"Error deleting dir {dir_path}: {e}")

    # Переименование директорий
    for old_path, new_path in events.get("dirs_moved", []):
        if state.get("stop_flag", False):
            break
        source_dir = get_source_dir_for_path(old_path) or get_source_dir_for_path(new_path)
        if not source_dir:
            continue
        if is_excluded(old_path) or is_excluded(new_path):
            continue
        old_dest = get_dest_path(old_path, source_dir)
        new_dest = get_dest_path(new_path, source_dir)
        try:
            if os.path.exists(old_dest):
                os.makedirs(os.path.dirname(new_dest), exist_ok=True)
                shutil.move(old_dest, new_dest)
                dirs_moved += 1
                if log:
                    log(f"Moved dir: {old_dest} -> {new_dest}")
        except Exception as e:
            errors += 1
            error_details.append(f"{old_path}: {e}")
            if log:
                log(f"Error moving dir {old_path}: {e}")

    # ── Обработка файлов ────────────────────────────────────────────────

    # Удаление файлов
    for file_path in events.get("deleted", []):
        if state.get("stop_flag", False):
            break
        source_dir = get_source_dir_for_path(file_path)
        if not source_dir:
            continue
        if is_excluded(file_path):
            continue
        dest_file = get_dest_path(file_path, source_dir)
        try:
            if os.path.exists(dest_file):
                os.remove(dest_file)
                files_deleted += 1
                deleted_files.append(dest_file)
                if log:
                    log(f"Deleted: {dest_file}")
        except Exception as e:
            errors += 1
            error_details.append(f"{file_path}: {e}")
            if log:
                log(f"Error deleting {file_path}: {e}")

    # Переименование файлов
    for old_path, new_path in events.get("moved", []):
        if state.get("stop_flag", False):
            break
        source_dir = get_source_dir_for_path(old_path) or get_source_dir_for_path(new_path)
        if not source_dir:
            continue
        if is_excluded(old_path) or is_excluded(new_path):
            continue
        old_dest = get_dest_path(old_path, source_dir)
        new_dest = get_dest_path(new_path, source_dir)
        try:
            if os.path.exists(old_dest):
                os.makedirs(os.path.dirname(new_dest), exist_ok=True)
                shutil.move(old_dest, new_dest)
                files_moved += 1
                if log:
                    log(f"Moved: {old_dest} -> {new_dest}")
        except Exception as e:
            errors += 1
            error_details.append(f"{old_path}: {e}")
            if log:
                log(f"Error moving {old_path}: {e}")

    # Копирование изменённых файлов
    for file_path in events.get("changed", []):
        if state.get("stop_flag", False):
            break
        if not os.path.exists(file_path):
            continue  # Файл был создан и удалён
        source_dir = get_source_dir_for_path(file_path)
        if not source_dir:
            continue
        if is_excluded(file_path):
            if log:
                log(f"Skipped (excluded by pattern): {file_path}")
            continue
        if skip_links and is_reparse_point(file_path):
            if log:
                log(f"Skipped (symbolic link): {file_path}")
            continue

        dest_file = get_dest_path(file_path, source_dir)
        try:
            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
            shutil.copy2(file_path, dest_file)
            files_copied += 1
            total_size += os.path.getsize(file_path)
            copied_files.append(file_path)
            if log:
                log(f"Copied: {file_path}")
        except Exception as e:
            errors += 1
            error_details.append(f"{file_path}: {e}")
            if log:
                log(f"Error copying {file_path}: {e}")

    return {
        "files_copied": files_copied,
        "files_deleted": files_deleted,
        "files_moved": files_moved,
        "dirs_created": dirs_created,
        "dirs_deleted": dirs_deleted,
        "dirs_moved": dirs_moved,
        "total_size_mb": total_size / 1024 / 1024,
        "errors": errors,
        "copied_files": copied_files,
        "deleted_files": deleted_files,
        "error_details": error_details,
    }