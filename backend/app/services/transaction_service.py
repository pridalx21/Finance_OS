"""Transaction service.

This module owns the rules that every balance in Finance OS relies on:

* which bookings count towards a balance (:func:`effective_transactions`),
* how a booking is voided (storno) without losing the history,
* how an idempotency key is checked.

Every module that needs a balance (accounts, reports, budgets, debts,
reconciliation) uses the helpers from here, so there is exactly one
calculation logic in the system.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable, Sequence

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.plugins import get_event_bus
from app.schemas.transaction import TransactionCreate

#: Prefix of the idempotency key that is used for storno entries.
REVERSAL_KEY_PREFIX = "reversal-"


class IdempotencyConflict(Exception):
    """Raised when an idempotency key is reused with a differing payload."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(value: datetime | None) -> datetime | None:
    """Normalise a datetime to naive UTC (the format used for storage)."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _fingerprint(payload: dict) -> str:
    """Stable hash of a request payload (used for idempotency checks)."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def transaction_fingerprint(data: TransactionCreate) -> str:
    """Fingerprint of the client payload of a booking request.

    Only client supplied fields are part of the fingerprint. Server assigned
    values (id, created_at, a date that was not sent by the client) are not,
    otherwise a retry of the same request could be reported as a conflict.
    """
    return _fingerprint(
        {
            "account_id": data.account_id,
            "type": data.type,
            "amount_cents": data.amount_cents,
            "category_id": data.category_id,
            "description": data.description,
            "date": _naive(data.date).isoformat() if data.date else None,
        }
    )


def _is_reversal(transaction: Transaction) -> bool:
    """True if the row is a storno entry (and therefore never counts)."""
    if getattr(transaction, "reverses_id", None):
        return True
    # Fallback for rows written before the `reverses_id` column existed.
    key = transaction.idempotency_key or ""
    return key.startswith(REVERSAL_KEY_PREFIX)


def effective_transactions(
    transactions: Iterable[Transaction],
    as_of: datetime | None = None,
) -> list[Transaction]:
    """Return the bookings that count towards a balance.

    Rules:

    * A booking counts only if its date is not after ``as_of``
      (``as_of=None`` means "no cut-off", i.e. the current state).
    * A booking that was reversed stops counting - but only from the moment
      the reversal itself is effective. A booking that was reversed *after*
      ``as_of`` therefore still counts at ``as_of``.
    * A storno entry never counts. It voids the original booking and exists
      as the traceable proof of that voiding.

    ``transactions`` must contain the complete set of bookings of one
    account, otherwise a reversal cannot be resolved.
    """
    items: Sequence[Transaction] = list(transactions)
    by_id = {t.id: t for t in items}
    result: list[Transaction] = []

    for t in items:
        if as_of is not None and t.date > as_of:
            continue
        if t.reversed_by:
            reversal = by_id.get(t.reversed_by)
            if reversal is None:
                # The reversal is unknown -> the booking counts as voided.
                continue
            if as_of is None or reversal.date <= as_of:
                continue
            # Not yet reversed at `as_of` -> the booking still counts.
        if _is_reversal(t):
            continue
        result.append(t)

    return result


def active_transactions(transactions: Iterable[Transaction]) -> list[Transaction]:
    """Drop voided bookings and their storno entries (current state)."""
    return effective_transactions(transactions)


def emit_transaction_created(transaction: Transaction, *, reversal: bool = False) -> None:
    """Emit the ``transaction.created`` event for a stored booking."""
    get_event_bus().emit(
        "transaction.created",
        {
            "id": transaction.id,
            "account_id": transaction.account_id,
            "type": transaction.type,
            "amount_cents": transaction.amount_cents,
            "reversal": reversal,
        },
    )


class TransactionService:
    """Create and void bookings.

    The service can run without committing (``commit=False``). It is used by
    the debts plugin, which has to store a booking and the payment that
    caused it in one single transaction.
    """

    def __init__(self, db: Session):
        self.db = db

    # ----- create ---------------------------------------------------------

    def create(self, data: TransactionCreate, *, commit: bool = True) -> Transaction:
        # The idempotency check comes first: a repeated request must return
        # the original result even if the referenced account was archived
        # in the meantime.
        if data.idempotency_key:
            existing = (
                self.db.query(Transaction)
                .filter(Transaction.idempotency_key == data.idempotency_key)
                .first()
            )
            if existing:
                self._check_idempotency(existing, data)
                return existing

        account = self.db.query(Account).filter(Account.id == data.account_id).first()
        if account is None or account.archived_at is not None:
            raise LookupError("Konto nicht gefunden")

        if data.category_id:
            category = self.db.query(Category).filter(Category.id == data.category_id).first()
            if category is None:
                raise LookupError("Kategorie nicht gefunden")
            if category.archived_at is not None:
                raise ValueError("Kategorie ist archiviert")
            if category.type != data.type:
                raise ValueError("Kategorie-Typ passt nicht zur Buchung")

        transaction = Transaction(
            account_id=data.account_id,
            type=data.type,
            amount_cents=data.amount_cents,
            category_id=data.category_id,
            description=data.description,
            date=_naive(data.date) or _utcnow(),
            idempotency_key=data.idempotency_key,
            idempotency_fingerprint=(
                transaction_fingerprint(data) if data.idempotency_key else None
            ),
        )
        self.db.add(transaction)
        if commit:
            self.db.commit()
            self.db.refresh(transaction)
            emit_transaction_created(transaction, reversal=False)
        else:
            self.db.flush()
        return transaction

    def _check_idempotency(self, existing: Transaction, data: TransactionCreate) -> None:
        """Raise :class:`IdempotencyConflict` if the payload differs."""
        if existing.idempotency_fingerprint:
            if existing.idempotency_fingerprint != transaction_fingerprint(data):
                raise IdempotencyConflict(
                    "Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet"
                )
            return

        # Row without a fingerprint (written before the column existed):
        # compare the fields that are available.
        if (
            existing.account_id != data.account_id
            or existing.type != data.type
            or existing.amount_cents != data.amount_cents
            or existing.category_id != data.category_id
            or (existing.description or None) != (data.description or None)
        ):
            raise IdempotencyConflict(
                "Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet"
            )
        if data.date is not None and existing.date != _naive(data.date):
            raise IdempotencyConflict(
                "Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet"
            )

    # ----- read -----------------------------------------------------------

    def get(self, transaction_id: str) -> Transaction | None:
        return self.db.query(Transaction).filter(Transaction.id == transaction_id).first()

    def list_by_account(
        self,
        account_id: str,
        type_filter: str | None = None,
        category_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        query = self.db.query(Transaction).filter(Transaction.account_id == account_id)
        if type_filter:
            query = query.filter(Transaction.type == type_filter)
        if category_id:
            query = query.filter(Transaction.category_id == category_id)
        total = query.count()
        items = query.order_by(Transaction.date.desc()).offset(offset).limit(limit).all()
        return items, total

    # ----- void (storno) --------------------------------------------------

    def reverse(self, transaction_id: str, *, commit: bool = True) -> Transaction | None:
        """Create a storno entry for a booking.

        The original booking stays in the database and is marked as voided
        (``reversed_by``). The storno entry points back at it (``reverses_id``),
        so the history stays traceable in both directions.
        """
        original = self.get(transaction_id)
        if not original or original.reversed_by:
            return None

        reversal_key = f"{REVERSAL_KEY_PREFIX}{original.id}"
        existing_reversal = (
            self.db.query(Transaction)
            .filter(Transaction.idempotency_key == reversal_key)
            .first()
        )
        if existing_reversal is not None:
            # Reuse the existing reversal entry (idempotent repeat).
            original.reversed_by = existing_reversal.id
            if commit:
                self.db.commit()
                self.db.refresh(existing_reversal)
            else:
                self.db.flush()
            return existing_reversal

        reversal = Transaction(
            account_id=original.account_id,
            type="EXPENSE" if original.type == "INCOME" else "INCOME",
            amount_cents=original.amount_cents,
            category_id=original.category_id,
            description=f"Storno: {original.description or ''}",
            date=_utcnow(),
            idempotency_key=reversal_key,
            reverses_id=original.id,
        )
        self.db.add(reversal)
        self.db.flush()
        original.reversed_by = reversal.id
        if commit:
            self.db.commit()
            self.db.refresh(reversal)
            emit_transaction_created(reversal, reversal=True)
        else:
            self.db.flush()
        return reversal
