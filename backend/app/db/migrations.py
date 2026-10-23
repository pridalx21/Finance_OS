"""Idempotent, versioned schema migrations.

``Base.metadata.create_all()`` only creates *missing* tables. It never alters
a table that already exists, so a column that is added to a model would be
silently missing in an existing database. This module provides the missing
half: a small, versioned runner that applies every schema change exactly
once and records it in the table ``schema_migrations``.

Rules (deliberately few, the project only needed a handful of changes):

* every migration is applied at most once and is recorded in
  ``schema_migrations``;
* every migration inspects the current state before changing anything, so
  re-running the runner is safe;
* a migration never deletes financial data. Obsolete tables are only dropped
  when they are provably empty, otherwise the step is skipped and a warning is
  logged;
* a failed migration is not recorded and is retried on the next start. Each
  individual step is idempotent, so a retry completes the remaining work.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import Engine, inspect, text

logger = logging.getLogger(__name__)

VERSION_TABLE = "schema_migrations"


@dataclass(frozen=True)
class Migration:
    """One reversible-by-version schema step."""

    version: int
    name: str
    apply: Callable[[Engine], None]


# ----- low level helpers -------------------------------------------------

def _table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _column_names(engine: Engine, table: str) -> set[str]:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def _add_column(engine: Engine, table: str, column: str, ddl: str) -> bool:
    """Add a column if the table exists and the column is missing.

    ``ddl`` is the column definition used in ``ALTER TABLE ... ADD COLUMN``.
    """
    if table not in _table_names(engine):
        logger.info("Migration: Tabelle '%s' existiert noch nicht - Spalte übersprungen", table)
        return False
    if column in _column_names(engine, table):
        return False
    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
    logger.info("Migration: Spalte '%s.%s' ergänzt", table, column)
    return True


def _create_index(
    engine: Engine,
    name: str,
    table: str,
    columns: list[str],
    unique: bool = False,
) -> bool:
    """Create an index if the table exists (SQLite supports IF NOT EXISTS)."""
    if table not in _table_names(engine):
        return False
    unique_sql = "UNIQUE " if unique else ""
    with engine.begin() as conn:
        conn.execute(
            text(
                f'CREATE {unique_sql}INDEX IF NOT EXISTS "{name}" '
                f'ON "{table}" ({", ".join(columns)})'
            )
        )
    return True


def _drop_table_if_empty(engine: Engine, table: str) -> bool:
    """Drop a table only when it holds no rows. Never loses data."""
    if table not in _table_names(engine):
        return False
    with engine.begin() as conn:
        count = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
        if count:
            logger.warning(
                "Migration: Tabelle '%s' enthält %d Zeilen - wird nicht gelöscht", table, count
            )
            return False
        conn.execute(text(f'DROP TABLE "{table}"'))
    logger.info("Migration: leere Alt-Tabelle '%s' entfernt", table)
    return True


# ----- migrations --------------------------------------------------------

def _m1_core_and_debt_columns(engine: Engine) -> None:
    """Reversal link, idempotency fingerprint and the debt payment columns."""
    _add_column(
        engine,
        "transactions",
        "reverses_id",
        "VARCHAR REFERENCES transactions (id)",
    )
    _add_column(
        engine,
        "transactions",
        "idempotency_fingerprint",
        "VARCHAR(64)",
    )
    _add_column(
        engine,
        "plugin_debts_debts",
        "correction_cents",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column(
        engine,
        "plugin_debts_debts",
        "idempotency_fingerprint",
        "VARCHAR(64)",
    )
    _add_column(
        engine,
        "plugin_debts_payments",
        "idempotency_key",
        "VARCHAR",
    )
    _add_column(
        engine,
        "plugin_debts_payments",
        "transaction_id",
        "VARCHAR REFERENCES transactions (id)",
    )
    _add_column(
        engine,
        "plugin_debts_payments",
        "cancelled_at",
        "DATETIME",
    )
    _add_column(
        engine,
        "plugin_debts_payments",
        "cancel_reason",
        "VARCHAR(200)",
    )
    _add_column(
        engine,
        "plugin_reconciliation_reconciliations",
        "basis_transaction_ids",
        "TEXT",
    )

    # Backfill the reversal link for rows created before the column existed.
    if "transactions" in _table_names(engine):
        tx_columns = _column_names(engine, "transactions")
        if "reversed_by" not in tx_columns:
            logger.info("Migration: 'transactions.reversed_by' fehlt - Rückverweis nicht ergänzt")
            return
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE transactions
                       SET reverses_id = (
                           SELECT t2.id FROM transactions t2 WHERE t2.reversed_by = transactions.id
                       )
                     WHERE id IN (SELECT reversed_by FROM transactions WHERE reversed_by IS NOT NULL)
                       AND reverses_id IS NULL
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE transactions
                       SET reversed_by = (
                           SELECT t2.id FROM transactions t2 WHERE t2.reverses_id = transactions.id
                       )
                     WHERE reversed_by IS NULL
                       AND id IN (SELECT reverses_id FROM transactions WHERE reverses_id IS NOT NULL)
                    """
                )
            )


def _m2_drop_legacy_debt_tables(engine: Engine) -> None:
    """Remove the empty tables of the two deactivated duplicate debt plugins."""
    for table in (
        "plugin_debt_debts",
        "plugin_debt_payments",
        "plugin_schulden_debts",
        "plugin_schulden_payments",
    ):
        _drop_table_if_empty(engine, table)


def _m3_performance_indexes(engine: Engine) -> None:
    """Indices for the hot query paths (balances, payments, reconciliations)."""
    _create_index(engine, "ix_transactions_account_date", "transactions", ["account_id", "date"])
    _create_index(engine, "ix_plugin_debts_debts_account_id", "plugin_debts_debts", ["account_id"])
    _create_index(engine, "ix_plugin_debts_payments_debt_id", "plugin_debts_payments", ["debt_id"])
    _create_index(
        engine,
        "ux_plugin_debts_payments_idempotency_key",
        "plugin_debts_payments",
        ["idempotency_key"],
        unique=True,
    )
    _create_index(
        engine,
        "ix_plugin_reconciliation_reconciliations_account",
        "plugin_reconciliation_reconciliations",
        ["account_id", "reconciliation_date"],
    )


def _m4_idempotency_fingerprints(engine: Engine) -> None:
    """Fingerprint columns for the idempotency check of payments and reconciliations.

    These columns were missing in migration 1 - a database that was already
    migrated to version 3 therefore needs this follow-up migration.
    """
    _add_column(
        engine,
        "plugin_debts_payments",
        "idempotency_fingerprint",
        "VARCHAR(64)",
    )
    _add_column(
        engine,
        "plugin_reconciliation_reconciliations",
        "idempotency_fingerprint",
        "VARCHAR(64)",
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "core_and_debt_columns", _m1_core_and_debt_columns),
    Migration(2, "drop_legacy_debt_tables", _m2_drop_legacy_debt_tables),
    Migration(3, "performance_indexes", _m3_performance_indexes),
    Migration(4, "idempotency_fingerprints", _m4_idempotency_fingerprints),
)


# ----- runner ------------------------------------------------------------

def _ensure_version_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS "{VERSION_TABLE}" (
                    version INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    applied_at DATETIME NOT NULL
                )
                """
            )
        )


def applied_versions(engine: Engine) -> set[int]:
    """Versions already applied to this database."""
    _ensure_version_table(engine)
    with engine.begin() as conn:
        rows = conn.execute(text(f'SELECT version FROM "{VERSION_TABLE}"')).fetchall()
    return {int(row[0]) for row in rows}


def current_version(engine: Engine) -> int:
    """Highest applied migration version (0 = fresh database)."""
    versions = applied_versions(engine)
    return max(versions) if versions else 0


def run_migrations(engine: Engine) -> list[int]:
    """Apply all pending migrations. Returns the versions applied in this call."""
    _ensure_version_table(engine)
    done = applied_versions(engine)
    applied: list[int] = []
    for migration in sorted(MIGRATIONS, key=lambda m: m.version):
        if migration.version in done:
            continue
        logger.info("Migration %d (%s) wird angewendet", migration.version, migration.name)
        migration.apply(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    f'INSERT INTO "{VERSION_TABLE}" (version, name, applied_at) '
                    "VALUES (:version, :name, :applied_at)"
                ),
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": datetime.now(timezone.utc).replace(tzinfo=None),
                },
            )
        applied.append(migration.version)
    return applied
