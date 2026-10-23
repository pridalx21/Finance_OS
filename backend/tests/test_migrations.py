"""Tests for the schema migrations (Phase E).

The migrations have to work on an empty database and on a database that was
created with an older schema - without losing data.
"""
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db.migrations import (
    MIGRATIONS,
    applied_versions,
    current_version,
    run_migrations,
)


# ----- helpers ------------------------------------------------------------

def _engine(tmp_path, name="test.db"):
    return create_engine(f"sqlite:///{tmp_path / name}")


def _create_old_schema(path):
    """Create a database with the schema of the version before the migrations."""
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
            archived_at DATETIME,
            FOREIGN KEY(parent_id) REFERENCES categories (id)
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
            reversed_by VARCHAR,
            FOREIGN KEY(account_id) REFERENCES accounts (id),
            FOREIGN KEY(category_id) REFERENCES categories (id),
            UNIQUE (idempotency_key)
        );
        CREATE TABLE plugin_debts_debts (
            id VARCHAR NOT NULL PRIMARY KEY,
            account_id VARCHAR,
            creditor VARCHAR(200) NOT NULL,
            type VARCHAR(20) NOT NULL,
            amount_cents INTEGER NOT NULL,
            remaining_cents INTEGER NOT NULL,
            interest_rate NUMERIC(6, 2),
            due_date DATETIME,
            status VARCHAR(20) NOT NULL,
            description VARCHAR(500),
            idempotency_key VARCHAR,
            created_at DATETIME NOT NULL,
            archived_at DATETIME,
            FOREIGN KEY(account_id) REFERENCES accounts (id),
            UNIQUE (idempotency_key)
        );
        CREATE TABLE plugin_debts_payments (
            id VARCHAR NOT NULL PRIMARY KEY,
            debt_id VARCHAR NOT NULL,
            amount_cents INTEGER NOT NULL,
            date DATETIME NOT NULL,
            note VARCHAR(500),
            created_at DATETIME NOT NULL,
            FOREIGN KEY(debt_id) REFERENCES plugin_debts_debts (id)
        );
        CREATE TABLE plugin_reconciliation_reconciliations (
            id VARCHAR NOT NULL PRIMARY KEY,
            account_id VARCHAR NOT NULL,
            reconciliation_date DATETIME NOT NULL,
            actual_balance_cents INTEGER NOT NULL,
            expected_balance_cents INTEGER NOT NULL,
            difference_cents INTEGER NOT NULL,
            note VARCHAR(500),
            idempotency_key VARCHAR,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(account_id) REFERENCES accounts (id),
            UNIQUE (idempotency_key)
        );
        """
    )
    conn.commit()
    conn.close()


def _insert_old_data(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        INSERT INTO accounts VALUES
            ('acc-1', 'Lohnkonto', 'CHF', 7095, '2026-01-01 00:00:00', NULL);
        INSERT INTO categories VALUES
            ('cat-1', 'Miete', 'EXPENSE', NULL, '#ff0000', 'home', '2026-01-01 00:00:00', NULL);
        INSERT INTO transactions VALUES
            ('tx-1', 'acc-1', 'EXPENSE', 1430, 'cat-1', 'Miete', '2026-05-01 10:00:00',
             '2026-05-01 10:00:00', NULL, NULL);
        INSERT INTO plugin_debts_debts VALUES
            ('debt-1', 'acc-1', 'Bank', 'OWED', 50000, 50000, NULL, NULL, 'OPEN', NULL,
             NULL, '2026-05-01 10:00:00', NULL);
        """
    )
    conn.commit()
    conn.close()


# ----- tests --------------------------------------------------------------

def test_migrations_on_an_empty_database(tmp_path):
    engine = _engine(tmp_path)
    applied = run_migrations(engine)

    assert applied == [m.version for m in MIGRATIONS]
    assert current_version(engine) == max(m.version for m in MIGRATIONS)
    assert "schema_migrations" in inspect(engine).get_table_names()


def test_migrations_are_idempotent(tmp_path):
    engine = _engine(tmp_path)
    run_migrations(engine)
    version = current_version(engine)

    assert run_migrations(engine) == []
    assert current_version(engine) == version
    assert applied_versions(engine) == {m.version for m in MIGRATIONS}


def test_migration_adds_the_missing_columns(tmp_path):
    path = tmp_path / "old.db"
    _create_old_schema(path)
    engine = create_engine(f"sqlite:///{path}")

    run_migrations(engine)
    inspector = inspect(engine)

    tx_columns = {c["name"] for c in inspector.get_columns("transactions")}
    assert "reverses_id" in tx_columns
    assert "idempotency_fingerprint" in tx_columns

    payment_columns = {c["name"] for c in inspector.get_columns("plugin_debts_payments")}
    assert "idempotency_key" in payment_columns
    assert "transaction_id" in payment_columns
    assert "cancelled_at" in payment_columns
    assert "cancel_reason" in payment_columns

    debt_columns = {c["name"] for c in inspector.get_columns("plugin_debts_debts")}
    assert "correction_cents" in debt_columns

    rec_columns = {
        c["name"] for c in inspector.get_columns("plugin_reconciliation_reconciliations")
    }
    assert "basis_transaction_ids" in rec_columns


def test_migration_keeps_the_data(tmp_path):
    path = tmp_path / "old.db"
    _create_old_schema(path)
    _insert_old_data(path)
    engine = create_engine(f"sqlite:///{path}")

    run_migrations(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM accounts")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM transactions")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM plugin_debts_debts")).scalar_one() == 1
        row = conn.execute(
            text("SELECT amount_cents, remaining_cents FROM plugin_debts_debts")
        ).fetchone()
        assert row == (50000, 50000)
        assert (
            conn.execute(
                text("SELECT initial_balance_cents FROM accounts WHERE id = 'acc-1'")
            ).scalar_one()
            == 7095
        )


def test_migration_backfills_the_reversal_link(tmp_path):
    path = tmp_path / "old.db"
    _create_old_schema(path)
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        INSERT INTO accounts VALUES
            ('acc-1', 'Lohnkonto', 'CHF', 0, '2026-01-01 00:00:00', NULL);
        INSERT INTO transactions VALUES
            ('tx-1', 'acc-1', 'EXPENSE', 1000, NULL, 'original', '2026-01-01 10:00:00',
             '2026-01-01 10:00:00', NULL, 'tx-2');
        INSERT INTO transactions VALUES
            ('tx-2', 'acc-1', 'INCOME', 1000, NULL, 'Storno', '2026-01-02 10:00:00',
             '2026-01-02 10:00:00', 'reversal-tx-1', NULL);
        """
    )
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{path}")
    run_migrations(engine)

    with engine.connect() as conn:
        reverses = conn.execute(
            text("SELECT reverses_id FROM transactions WHERE id = 'tx-2'")
        ).scalar_one()
        assert reverses == "tx-1"


def test_migration_drops_empty_legacy_tables(tmp_path):
    path = tmp_path / "old.db"
    _create_old_schema(path)
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE plugin_debt_debts (id VARCHAR PRIMARY KEY, amount_cents INTEGER);
        CREATE TABLE plugin_debt_payments (id VARCHAR PRIMARY KEY, amount_cents INTEGER);
        CREATE TABLE plugin_schulden_debts (id VARCHAR PRIMARY KEY, amount_cents INTEGER);
        CREATE TABLE plugin_schulden_payments (id VARCHAR PRIMARY KEY, amount_cents INTEGER);
        """
    )
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{path}")
    run_migrations(engine)

    tables = set(inspect(engine).get_table_names())
    assert "plugin_debt_debts" not in tables
    assert "plugin_debt_payments" not in tables
    assert "plugin_schulden_debts" not in tables
    assert "plugin_schulden_payments" not in tables


def test_migration_never_drops_a_legacy_table_with_data(tmp_path):
    path = tmp_path / "old.db"
    _create_old_schema(path)
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE plugin_debt_debts (id VARCHAR PRIMARY KEY, amount_cents INTEGER);
        INSERT INTO plugin_debt_debts VALUES ('keep-me', 100);
        """
    )
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{path}")
    run_migrations(engine)

    assert "plugin_debt_debts" in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT COUNT(*) FROM plugin_debt_debts")).scalar_one() == 1
        )


def test_migration_creates_the_indexes(tmp_path):
    path = tmp_path / "old.db"
    _create_old_schema(path)
    engine = create_engine(f"sqlite:///{path}")
    run_migrations(engine)

    with engine.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index'")
            )
        }
    assert "ix_transactions_account_date" in names
    assert "ux_plugin_debts_payments_idempotency_key" in names


def test_foreign_keys_are_enforced_after_the_migration(tmp_path):
    """A booking with an unknown account must not be storable."""
    from sqlalchemy.exc import IntegrityError

    path = tmp_path / "old.db"
    _create_old_schema(path)
    engine = create_engine(f"sqlite:///{path}")
    run_migrations(engine)

    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO transactions "
                    "(id, account_id, type, amount_cents, date, created_at) "
                    "VALUES ('tx-x', 'unknown', 'EXPENSE', 100, '2026-01-01', '2026-01-01')"
                )
            )


def test_migrated_database_matches_the_models(tmp_path):
    """No column of a model may be missing in a migrated database.

    This guards against a column that was added to a model but not to a
    migration - the database would then fail at runtime.
    """
    # Make sure the plugin models are part of Base.metadata. The canonical
    # module name is used, so a plugin that was already loaded by another
    # test is reused instead of being registered a second time.
    import importlib.util
    import sys

    plugins_dir = Path(__file__).parent.parent / "plugins"
    for name in ("debts", "reconciliation"):
        module_name = f"finance_plugin_{name}"
        if module_name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(
            module_name, plugins_dir / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

    from app.db.database import Base

    path = tmp_path / "old.db"
    _create_old_schema(path)
    engine = create_engine(f"sqlite:///{path}")
    run_migrations(engine)

    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in db_tables:
            continue
        db_columns = {c["name"] for c in inspector.get_columns(table.name)}
        model_columns = {c.name for c in table.columns}
        missing = model_columns - db_columns
        assert not missing, (
            f"Tabelle '{table.name}' fehlen im migrierten Schema: {sorted(missing)}"
        )

