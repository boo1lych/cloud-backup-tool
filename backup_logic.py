# backup_logic.py
"""Чистая бизнес-логика бэкапа, отделённая от UI для тестируемости.

Все функции в этом модуле не зависят от Tkinter и могут быть
протестированы без создания графического интерфейса.
"""

import os
import shutil
import fnmatch
import ctypes


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
        return True, ""
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
    files_copied = 0
    files_skipped = 0
    total_size = 0
    errors = 0
    copied_files = []
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
    }