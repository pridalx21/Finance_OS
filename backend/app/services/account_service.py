"""Account service."""
from sqlalchemy.orm import Session
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountBalance
from app.models.transaction import Transaction


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

    def balance(self, account_id: str) -> AccountBalance | None:
        account = self.get(account_id)
        if not account:
            return None

        income = (
            self.db.query(Transaction)
            .filter(Transaction.account_id == account_id, Transaction.type == "INCOME")
            .all()
        )
        expense = (
            self.db.query(Transaction)
            .filter(Transaction.account_id == account_id, Transaction.type == "EXPENSE")
            .all()
        )

        total_income = sum(t.amount_cents for t in income)
        total_expense = sum(t.amount_cents for t in expense)
        balance = account.initial_balance_cents + total_income - total_expense

        return AccountBalance(
            account_id=account.id,
            account_name=account.name,
            currency=account.currency,
            initial_balance_cents=account.initial_balance_cents,
            total_income_cents=total_income,
            total_expense_cents=total_expense,
            balance_cents=balance,
        )
