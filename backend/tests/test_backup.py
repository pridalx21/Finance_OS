"""Tests for the backup and restore of the database (Phase E)."""
import sqlite3

import pytest

from app.db.backup import (
    BackupError,
    backup_database,
    restore_database,
    verify_database,
)


def _create_database(path, rows=("Lohnkonto",)):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE accounts (
            id VARCHAR NOT NULL PRIMARY KEY,
            name VARCHAR NOT NULL,
            currency VARCHAR NOT NULL,
            initial_balance_cents INTEGER NOT NULL,
            created_at DATETIME NOT NULL,
            archived_at DATETIME
        );
        CREATE TABLE categories (
            id VARCHAR NOT NULL PRIMARY KEY,
            name VARCHAR NOT NULL,
            type VARCHAR NOT NULL,
            parent_id VARCHAR,
            color VARCHAR,
            icon VARCHAR,
            created_at DATETIME NOT NULL,
            archived_at DATETIME
        );
        CREATE TABLE transactions (
            id VARCHAR NOT NULL PRIMARY KEY,
            account_id VARCHAR NOT NULL,
            type VARCHAR NOT NULL,
            amount_cents INTEGER NOT NULL,
            category_id VARCHAR,
            description VARCHAR,
            date DATETIME NOT NULL,
            created_at DATETIME NOT NULL,
            idempotency_key VARCHAR,
            reversed_by VARCHAR
        );
        """
    )
    for index, name in enumerate(rows):
        conn.execute(
            "INSERT INTO accounts VALUES (?, ?, 'CHF', 0, '2026-01-01 00:00:00', NULL)",
            (f"acc-{index}", name),
        )
    conn.commit()
    conn.close()
    return path


def _count_accounts(path):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    finally:
        conn.close()


def test_backup_creates_a_copy_with_the_data(tmp_path):
    source = _create_database(tmp_path / "finance.db", rows=("A", "B"))
    target = backup_database(source, tmp_path / "backup.db")

    assert target.exists()
    assert _count_accounts(target) == 2
    # The original is untouched
    assert _count_accounts(source) == 2


def test_backup_to_the_default_folder(tmp_path):
    source = _create_database(tmp_path / "finance.db")
    target = backup_database(source, None)
    try:
        assert target.exists()
        assert target.parent.name == "backups"
    finally:
        target.unlink(missing_ok=True)


def test_restore_brings_the_data_back(tmp_path):
    source = _create_database(tmp_path / "finance.db", rows=("A", "B", "C"))
    backup = backup_database(source, tmp_path / "backup.db")

    # The live database loses its data
    conn = sqlite3.connect(str(source))
    conn.execute("DELETE FROM accounts")
    conn.commit()
    conn.close()
    assert _count_accounts(source) == 0

    restore_database(backup, source)
    assert _count_accounts(source) == 3


def test_restore_keeps_a_copy_of_the_previous_state(tmp_path):
    source = _create_database(tmp_path / "finance.db", rows=("A",))
    backup = backup_database(source, tmp_path / "backup.db")

    restore_database(backup, source)
    backup_copy = tmp_path / "finance.db.bak"
    assert backup_copy.exists()
    assert _count_accounts(backup_copy) == 1


def test_restore_of_a_broken_file_is_refused(tmp_path):
    broken = tmp_path / "broken.db"
    broken.write_text("this is not a database")

    target = _create_database(tmp_path / "finance.db")
    with pytest.raises(BackupError):
        restore_database(broken, target)

    # The target is unchanged
    assert _count_accounts(target) == 1


def test_restore_of_a_file_with_missing_tables_is_refused(tmp_path):
    incomplete = tmp_path / "incomplete.db"
    conn = sqlite3.connect(str(incomplete))
    conn.execute("CREATE TABLE something (id VARCHAR PRIMARY KEY)")
    conn.commit()
    conn.close()

    with pytest.raises(BackupError):
        verify_database(incomplete)


def test_verify_reports_the_tables(tmp_path):
    path = _create_database(tmp_path / "finance.db")
    report = verify_database(path)
    assert report["integrity"] == "ok"
    assert "accounts" in report["tables"]
    assert report["size_bytes"] > 0


def test_backup_of_a_missing_file_is_refused(tmp_path):
    with pytest.raises(BackupError):
        backup_database(tmp_path / "does-not-exist.db", tmp_path / "backup.db")
