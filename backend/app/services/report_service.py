"""Report service."""
from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.transaction import Transaction
from app.models.category import Category
from app.services.transaction_service import active_transactions


class ReportService:
    def __init__(self, db: Session):
        self.db = db

    def expenses_by_category(self, account_id: str) -> list[dict]:
        """Aggregate expenses by category."""
        transactions = active_transactions(
            self.db.query(Transaction)
            .filter(Transaction.account_id == account_id)
            .all()
        )
        transactions = [t for t in transactions if t.type == "EXPENSE"]

        categories = {c.id: c for c in self.db.query(Category).all()}

        totals: dict[str, int] = defaultdict(int)
        for t in transactions:
            key = t.category_id or "uncategorized"
            totals[key] += t.amount_cents

        result = []
        for cat_id, amount in totals.items():
            cat = categories.get(cat_id)
            result.append({
                "category_id": cat_id,
                "category_name": cat.name if cat else "Ohne Kategorie",
                "category_color": cat.color if cat else "#6b7280",
                "category_icon": cat.icon if cat else "more-horizontal",
                "total_cents": amount,
            })

        result.sort(key=lambda x: x["total_cents"], reverse=True)
        return result

    def income_vs_expense(self, account_id: str) -> dict:
        """Compare total income vs total expense."""
        transactions = active_transactions(
            self.db.query(Transaction)
            .filter(Transaction.account_id == account_id)
            .all()
        )
        income = sum(t.amount_cents for t in transactions if t.type == "INCOME")
        expense = sum(t.amount_cents for t in transactions if t.type == "EXPENSE")
        return {
            "total_income_cents": income,
            "total_expense_cents": expense,
            "net_cents": income - expense,
        }

    def monthly_trend(self, account_id: str, months: int = 6) -> list[dict]:
        """Aggregate income and expense per month for the last N months.

        Returns a list ordered oldest to newest, one entry per month, even if
        a month has no transactions (zeros).
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # First day of the oldest month in the window
        start_year = now.year
        start_month = now.month - (months - 1)
        while start_month <= 0:
            start_month += 12
            start_year -= 1

        # Build the ordered list of month keys, e.g. "2026-05"
        month_keys: list[str] = []
        y, m = start_year, start_month
        for _ in range(months):
            month_keys.append(f"{y:04d}-{m:02d}")
            m += 1
            if m > 12:
                m = 1
                y += 1

        window_start = datetime(start_year, start_month, 1)

        transactions = active_transactions(
            self.db.query(Transaction)
            .filter(Transaction.account_id == account_id)
            .all()
        )
        transactions = [t for t in transactions if t.date >= window_start]

        income_by_month: dict[str, int] = defaultdict(int)
        expense_by_month: dict[str, int] = defaultdict(int)
        for t in transactions:
            key = f"{t.date.year:04d}-{t.date.month:02d}"
            if t.type == "INCOME":
                income_by_month[key] += t.amount_cents
            elif t.type == "EXPENSE":
                expense_by_month[key] += t.amount_cents

        return [
            {
                "month": key,
                "income_cents": income_by_month.get(key, 0),
                "expense_cents": expense_by_month.get(key, 0),
            }
            for key in month_keys
        ]
