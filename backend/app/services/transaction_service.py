"""Transaction service."""
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionCreate


class TransactionService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: TransactionCreate) -> Transaction:
        # Check idempotency
        if data.idempotency_key:
            existing = (
                self.db.query(Transaction)
                .filter(Transaction.idempotency_key == data.idempotency_key)
                .first()
            )
            if existing:
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

        reversal = Transaction(
            account_id=original.account_id,
            type="EXPENSE" if original.type == "INCOME" else "INCOME",
            amount_cents=original.amount_cents,
            category_id=original.category_id,
            description=f"Storno: {original.description or ''}",
            date=datetime.now(timezone.utc).replace(tzinfo=None),
            idempotency_key=f"reversal-{original.id}",
        )
        self.db.add(reversal)
        self.db.commit()
        self.db.refresh(reversal)

        original.reversed_by = reversal.id
        self.db.commit()

        return reversal
