"""Backup and restore of the SQLite database.

The backup uses the SQLite backup API, which produces a consistent copy even
while the database is being written to. The restore works on a copy as well:
the backup file is verified before it replaces the target, and the target is
kept as ``<target>.bak`` so a failed restore can be undone.

Command line::

    python -m app.db.backup backup            # -> backups/finance-<timestamp>.db
    python -m app.db.backup backup -o FILE.db
    python -m app.db.backup restore FILE.db   # -> data/finance.db
    python -m app.db.backup verify FILE.db
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

#: Tables that have to exist for a file to be a usable Finance OS database.
REQUIRED_TABLES = ("accounts", "categories", "transactions")


class BackupError(Exception):
    """Raised when a backup or restore cannot be completed safely."""


def _default_db_path() -> Path:
    from app.db.database import default_database_path

    return default_database_path()


def verify_database(path: Path) -> dict:
    """Check a database file and return a short report.

    Raises :class:`BackupError` if the file is not a usable database.
    """
    path = Path(path)
    if not path.is_file():
        raise BackupError(f"Datei existiert nicht: {path}")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        raise BackupError(f"Datei kann nicht geöffnet werden: {exc}") from exc
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise BackupError(f"Integritätsprüfung fehlgeschlagen: {integrity}")
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = [t for t in REQUIRED_TABLES if t not in tables]
        if missing:
            raise BackupError(
                "Fehlende Tabellen in der Sicherung: " + ", ".join(missing)
            )
        return {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "tables": sorted(tables),
            "integrity": integrity,
        }
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"Ungültige Datenbankdatei: {exc}") from exc
    finally:
        conn.close()


def backup_database(source: Path | None = None, target: Path | None = None) -> Path:
    """Create a consistent copy of the database."""
    source = Path(source) if source else _default_db_path()
    if target is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = source.parent.parent / "backups" / f"finance-{stamp}.db"
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    if not source.is_file():
        raise BackupError(f"Datenbank existiert nicht: {source}")

    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    except sqlite3.Error as exc:
        raise BackupError(f"Sicherung fehlgeschlagen: {exc}") from exc
    finally:
        dst.close()
        src.close()

    verify_database(target)
    return target


def restore_database(backup: Path, target: Path | None = None) -> Path:
    """Restore a backup into the database file.

    The backup is verified first. The previous content of the target is kept
    as ``<target>.bak``.
    """
    backup = Path(backup)
    target = Path(target) if target else _default_db_path()
    verify_database(backup)

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))

    shutil.copy2(backup, target)
    verify_database(target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.db.backup",
        description="Sicherung und Wiederherstellung der Finance OS Datenbank",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="Sicherung erstellen")
    p_backup.add_argument("-s", "--source", type=Path, default=None)
    p_backup.add_argument("-o", "--output", type=Path, default=None)

    p_restore = sub.add_parser("restore", help="Sicherung zurückspielen")
    p_restore.add_argument("backup", type=Path)
    p_restore.add_argument("-t", "--target", type=Path, default=None)

    p_verify = sub.add_parser("verify", help="Sicherungsdatei prüfen")
    p_verify.add_argument("file", type=Path)

    args = parser.parse_args(argv)

    try:
        if args.command == "backup":
            path = backup_database(args.source, args.output)
            print(f"Sicherung erstellt: {path}")
        elif args.command == "restore":
            path = restore_database(args.backup, args.target)
            print(f"Wiederhergestellt: {path}")
        elif args.command == "verify":
            report = verify_database(args.file)
            print(f"OK: {report['path']} ({report['size_bytes']} Bytes)")
            print(f"Tabellen: {', '.join(report['tables'])}")
    except BackupError as exc:
        print(f"Fehler: {exc}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
