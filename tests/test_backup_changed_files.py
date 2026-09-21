"""Тесты для backup_changed_files — копирование только изменённых файлов."""
import os
import pytest
from backup_logic import backup_changed_files


def _make_events(changed=None, deleted=None, moved=None,
                 dirs_created=None, dirs_deleted=None, dirs_moved=None):
    return {
        "changed": changed or [],
        "deleted": deleted or [],
        "moved": moved or [],
        "dirs_created": dirs_created or [],
        "dirs_deleted": dirs_deleted or [],
        "dirs_moved": dirs_moved or [],
    }


class TestBackupChangedFilesCopy:
    def test_copy_changed_files(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        f = src / "file.txt"
        f.write_text("hello")

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(changed=[str(f)]),
        )

        assert result["files_copied"] == 1
        assert result["errors"] == 0
        assert (backup / "source" / "file.txt").exists()
        assert (backup / "source" / "file.txt").read_text() == "hello"

    def test_skip_nonexistent_files(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        nonexistent = src / "missing.txt"

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(changed=[str(nonexistent)]),
        )

        assert result["files_copied"] == 0
        assert result["errors"] == 0

    def test_skip_excluded_files(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        f = src / "temp.tmp"
        f.write_text("data")

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="*.tmp",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(changed=[str(f)]),
        )

        assert result["files_copied"] == 0
        assert not (backup / "source" / "temp.tmp").exists()

    def test_multiple_files_copied(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        f1 = src / "a.txt"
        f1.write_text("aaa")
        f2 = src / "b.txt"
        f2.write_text("bbb")

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(changed=[str(f1), str(f2)]),
        )

        assert result["files_copied"] == 2
        assert (backup / "source" / "a.txt").exists()
        assert (backup / "source" / "b.txt").exists()


class TestBackupChangedFilesDelete:
    def test_delete_existing_file(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup" / "source"
        backup.mkdir(parents=True)
        f_src = src / "file.txt"
        f_backup = backup / "file.txt"
        f_src.write_text("data")
        f_backup.write_text("data")

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(tmp_path / "backup"),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(deleted=[str(f_src)]),
        )

        assert result["files_deleted"] == 1
        assert not f_backup.exists()

    def test_delete_nonexistent_no_error(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        f_src = src / "missing.txt"

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(deleted=[str(f_src)]),
        )

        assert result["files_deleted"] == 0
        assert result["errors"] == 0


class TestBackupChangedFilesMove:
    def test_move_existing_file(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup" / "source"
        backup.mkdir(parents=True)
        old_src = src / "old.txt"
        new_src = src / "new.txt"
        old_backup = backup / "old.txt"
        old_backup.write_text("data")

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(tmp_path / "backup"),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(moved=[(str(old_src), str(new_src))]),
        )

        assert result["files_moved"] == 1
        assert not old_backup.exists()
        assert (backup / "new.txt").exists()
        assert (backup / "new.txt").read_text() == "data"


class TestBackupChangedFilesDirectories:
    def test_create_directory(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        new_dir = src / "newdir"
        new_dir.mkdir()

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(dirs_created=[str(new_dir)]),
        )

        assert result["dirs_created"] == 1
        assert (backup / "source" / "newdir").is_dir()

    def test_delete_directory(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup" / "source"
        backup.mkdir(parents=True)
        old_dir = src / "olddir"
        old_dir.mkdir()
        old_backup = backup / "olddir"
        old_backup.mkdir()

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(tmp_path / "backup"),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(dirs_deleted=[str(old_dir)]),
        )

        assert result["dirs_deleted"] == 1
        assert not old_backup.exists()

    def test_move_directory(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup" / "source"
        backup.mkdir(parents=True)
        old_dir = src / "old"
        new_dir = src / "new"
        old_backup = backup / "old"
        old_backup.mkdir()

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(tmp_path / "backup"),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(dirs_moved=[(str(old_dir), str(new_dir))]),
        )

        assert result["dirs_moved"] == 1
        assert not old_backup.exists()
        assert (backup / "new").is_dir()


class TestBackupChangedFilesSourceDir:
    def test_multiple_source_dirs_correct_mapping(self, tmp_path):
        src1 = tmp_path / "src1"
        src1.mkdir()
        src2 = tmp_path / "src2"
        src2.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        f1 = src1 / "a.txt"
        f1.write_text("1")
        f2 = src2 / "b.txt"
        f2.write_text("2")

        result = backup_changed_files(
            source_dirs=[str(src1), str(src2)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src1), str(src2)],
            state={},
            events=_make_events(changed=[str(f1), str(f2)]),
        )

        assert result["files_copied"] == 2
        assert (backup / "src1" / "a.txt").exists()
        assert (backup / "src2" / "b.txt").exists()

    def test_path_outside_source_dirs_skipped(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        outside = tmp_path / "outside" / "file.txt"
        outside.parent.mkdir()
        outside.write_text("data")

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(changed=[str(outside)]),
        )

        assert result["files_copied"] == 0


class TestBackupChangedFilesStopFlag:
    def test_stop_flag_stops_processing(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        files = []
        for i in range(5):
            f = src / f"f{i}.txt"
            f.write_text(f"data{i}")
            files.append(str(f))

        state = {"stop_flag": True}

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state=state,
            events=_make_events(changed=files),
        )

        # При stop_flag обработка прерывается до первого файла
        assert result["files_copied"] == 0


class TestBackupChangedFilesEmpty:
    def test_empty_events(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(),
        )

        assert result["files_copied"] == 0
        assert result["files_deleted"] == 0
        assert result["files_moved"] == 0
        assert result["dirs_created"] == 0
        assert result["errors"] == 0

    def test_stats_returned(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        f = src / "file.txt"
        f.write_text("x" * 100)

        result = backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(changed=[str(f)]),
        )

        assert "files_copied" in result
        assert "files_deleted" in result
        assert "files_moved" in result
        assert "dirs_created" in result
        assert "dirs_deleted" in result
        assert "dirs_moved" in result
        assert "total_size_mb" in result
        assert "errors" in result
        assert "copied_files" in result
        assert "deleted_files" in result
        assert "error_details" in result
        assert result["total_size_mb"] > 0


class TestBackupChangedFilesLogging:
    def test_log_callback_called(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        f = src / "file.txt"
        f.write_text("data")

        logs = []
        backup_changed_files(
            source_dirs=[str(src)],
            backup_dir=str(backup),
            skip_links=True,
            exclude_patterns_str="",
            all_sources_in_profile=[str(src)],
            state={},
            events=_make_events(changed=[str(f)]),
            log=lambda m: logs.append(m),
        )

        assert any("Copied" in m for m in logs)