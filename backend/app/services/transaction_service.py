"""Transaction service."""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.plugins import get_event_bus
from app.schemas.transaction import TransactionCreate


class IdempotencyConflict(Exception):
    """Raised when an idempotency key is reused with a differing payload."""


def active_transactions(transactions: list[Transaction]) -> list[Transaction]:
    """Drop reversed originals and their reversal entries."""
    reversed_ids = {t.reversed_by for t in transactions if t.reversed_by}
    return [
        t for t in transactions
        if t.reversed_by is None and t.id not in reversed_ids
    ]


class TransactionService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: TransactionCreate) -> Transaction:
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

        # Check idempotency
        if data.idempotency_key:
            existing = (
                self.db.query(Transaction)
                .filter(Transaction.idempotency_key == data.idempotency_key)
                .first()
            )
            if existing:
                # Verify the repeated request matches the original payload.
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
                return existing

        transaction = Transaction(
            account_id=data.account_id,
            type=data.type,
            amount_cents=data.amount_cents,
            category_id=data.category_id,
            description=data.description,
            date=data.date or datetime.now(timezone.utc).replace(tzinfo=None),
            idempotency_key=data.idempotency_key,
        )
        self.db.add(transaction)
        self.db.commit()
        self.db.refresh(transaction)
        get_event_bus().emit(
            "transaction.created",
            {
                "id": transaction.id,
                "account_id": transaction.account_id,
                "type": transaction.type,
                "amount_cents": transaction.amount_cents,
                "reversal": False,
            },
        )
        return transaction

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

    def reverse(self, transaction_id: str) -> Transaction | None:
        """Create a reversal (storno) for a transaction."""
        original = self.get(transaction_id)
        if not original or original.reversed_by:
            return None

        reversal_key = f"reversal-{original.id}"
        existing_reversal = (
            self.db.query(Transaction)
            .filter(Transaction.idempotency_key == reversal_key)
            .first()
        )
        if existing_reversal is not None:
            # Reuse the existing reversal entry (idempotent repeat).
            original.reversed_by = existing_reversal.id
            self.db.commit()
            self.db.refresh(existing_reversal)
            return existing_reversal

        reversal = Transaction(
            account_id=original.account_id,
            type="EXPENSE" if original.type == "INCOME" else "INCOME",
            amount_cents=original.amount_cents,
            category_id=original.category_id,
            description=f"Storno: {original.description or ''}",
            date=datetime.now(timezone.utc).replace(tzinfo=None),
            idempotency_key=reversal_key,
        )
        self.db.add(reversal)
        self.db.flush()
        original.reversed_by = reversal.id
        self.db.commit()
        self.db.refresh(reversal)
        get_event_bus().emit(
            "transaction.created",
            {
                "id": reversal.id,
                "account_id": reversal.account_id,
                "type": reversal.type,
                "amount_cents": reversal.amount_cents,
                "reversal": True,
            },
        )

        return reversal
