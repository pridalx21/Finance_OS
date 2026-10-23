"""Account service.

The balance of an account is always calculated the same way:

    balance = initial balance + valid income - valid expenses

"Valid" means: not voided (storno) and - when a cut-off date is given -
not dated after that date. The calculation itself lives in
:func:`app.services.transaction_service.effective_transactions`, so accounts,
reports, budgets, debts and reconciliation can never drift apart.
"""
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.transaction import Transaction
from app.schemas.account import AccountCreate, AccountBalance
from app.services.transaction_service import effective_transactions


@dataclass(frozen=True)
class BalanceResult:
    """Balance of an account with the bookings that produced it."""

    account_id: str
    account_name: str
    currency: str
    initial_balance_cents: int
    total_income_cents: int
    total_expense_cents: int
    balance_cents: int
    transaction_ids: list[str] = field(default_factory=list)

    def to_schema(self) -> AccountBalance:
        return AccountBalance(
            account_id=self.account_id,
            account_name=self.account_name,
            currency=self.currency,
            initial_balance_cents=self.initial_balance_cents,
            total_income_cents=self.total_income_cents,
            total_expense_cents=self.total_expense_cents,
            balance_cents=self.balance_cents,
        )


def compute_balance(
    db: Session,
    account_id: str,
    as_of: datetime | None = None,
) -> BalanceResult | None:
    """Calculate the balance of an account.

    ``as_of`` limits the calculation to a cut-off date. Bookings after that
    date are ignored, and a booking that was voided only after that date
    still counts (see :func:`effective_transactions`).
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if account is None:
        return None

    all_tx = db.query(Transaction).filter(Transaction.account_id == account_id).all()
    active = effective_transactions(all_tx, as_of=as_of)

    income = sum(t.amount_cents for t in active if t.type == "INCOME")
    expense = sum(t.amount_cents for t in active if t.type == "EXPENSE")

    return BalanceResult(
        account_id=account.id,
        account_name=account.name,
        currency=account.currency,
        initial_balance_cents=account.initial_balance_cents,
        total_income_cents=income,
        total_expense_cents=expense,
        balance_cents=account.initial_balance_cents + income - expense,
        transaction_ids=[t.id for t in active],
    )


class AccountService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: AccountCreate) -> Account:
        account = Account(
            name=data.name,
            currency=data.currency,
            initial_balance_cents=data.initial_balance_cents,
        )
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account

    def get(self, account_id: str) -> Account | None:
        return self.db.query(Account).filter(Account.id == account_id).first()

    def list_all(self) -> list[Account]:
        return self.db.query(Account).filter(Account.archived_at.is_(None)).all()

    def balance(self, account_id: str, as_of: datetime | None = None) -> AccountBalance | None:
        result = compute_balance(self.db, account_id, as_of=as_of)
        return result.to_schema() if result else None
