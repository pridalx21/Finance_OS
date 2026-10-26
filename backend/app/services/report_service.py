"""Report service."""
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta

from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.models.category import Category
from app.services.transaction_service import effective_transactions


class ReportService:
    def __init__(self, db: Session):
        self.db = db

    # ----- helpers -------------------------------------------------------

    def _all_transactions(self, account_id: str) -> list[Transaction]:
        return (
            self.db.query(Transaction)
            .filter(Transaction.account_id == account_id)
            .all()
        )

    def _categories(self) -> dict[str, Category]:
        return {c.id: c for c in self.db.query(Category).all()}

    def _expenses_by_category(self, transactions: list[Transaction]) -> list[dict]:
        categories = self._categories()
        totals: dict[str, int] = defaultdict(int)
        for t in transactions:
            if t.type == "EXPENSE":
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

    def _aggregate_period(self, account_id: str, start: datetime, end: datetime) -> dict:
        """Aggregate income/expense/net for ``[start, end)``.

        Historical correctness: only bookings that are effective at the end
        of the period are considered, so a later storno does not rewrite a
        past period.
        """
        as_of = end - timedelta(microseconds=1)
        effective = effective_transactions(self._all_transactions(account_id), as_of=as_of)
        period_tx = [t for t in effective if start <= t.date < end]

        income = sum(t.amount_cents for t in period_tx if t.type == "INCOME")
        expense = sum(t.amount_cents for t in period_tx if t.type == "EXPENSE")

        return {
            "income_cents": income,
            "expense_cents": expense,
            "net_cents": income - expense,
            "transaction_count": len(period_tx),
            "expenses_by_category": self._expenses_by_category(period_tx),
        }

    @staticmethod
    def _week_key(value: datetime | date) -> str:
        d = value.date() if isinstance(value, datetime) else value
        iso = d.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"

    @staticmethod
    def _parse_week(week: str) -> tuple[datetime, datetime]:
        if not isinstance(week, str) or "-W" not in week:
            raise ValueError("Ungültiges Wochenformat, erwartet YYYY-Www")
        year_str, week_str = week.split("-W")
        try:
            year = int(year_str)
            week_no = int(week_str)
            monday = date.fromisocalendar(year, week_no, 1)
        except (ValueError, TypeError) as exc:
            raise ValueError("Ungültiges Wochenformat, erwartet YYYY-Www") from exc
        start = datetime(monday.year, monday.month, monday.day)
        end = start + timedelta(days=7)
        return start, end

    @staticmethod
    def _parse_month(month: str) -> tuple[datetime, datetime]:
        if not isinstance(month, str):
            raise ValueError("Ungültiges Monatsformat, erwartet YYYY-MM")
        parts = month.split("-")
        if len(parts) != 2:
            raise ValueError("Ungültiges Monatsformat, erwartet YYYY-MM")
        try:
            year = int(parts[0])
            month_no = int(parts[1])
            if month_no < 1 or month_no > 12:
                raise ValueError
            start = datetime(year, month_no, 1)
        except ValueError as exc:
            raise ValueError("Ungültiges Monatsformat, erwartet YYYY-MM") from exc
        if month_no == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month_no + 1, 1)
        return start, end

    @staticmethod
    def _prev_month_key(year: int, month: int) -> str:
        if month == 1:
            return f"{year - 1:04d}-12"
        return f"{year:04d}-{month - 1:02d}"

    # ----- existing reports ---------------------------------------------

    def expenses_by_category(self, account_id: str) -> list[dict]:
        """Aggregate expenses by category."""
        transactions = effective_transactions(
            self.db.query(Transaction)
            .filter(Transaction.account_id == account_id)
            .all()
        )
        transactions = [t for t in transactions if t.type == "EXPENSE"]

        categories = self._categories()

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
        transactions = effective_transactions(
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
        """Aggregate income and expense per month for the last N months."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        start_year = now.year
        start_month = now.month - (months - 1)
        while start_month <= 0:
            start_month += 12
            start_year -= 1

        result: list[dict] = []
        y, m = start_year, start_month
        for _ in range(months):
            start = datetime(y, m, 1)
            if m == 12:
                end = datetime(y + 1, 1, 1)
            else:
                end = datetime(y, m + 1, 1)
            agg = self._aggregate_period(account_id, start, end)
            result.append({
                "month": f"{y:04d}-{m:02d}",
                "income_cents": agg["income_cents"],
                "expense_cents": agg["expense_cents"],
            })
            m += 1
            if m > 12:
                m = 1
                y += 1

        return result

    # ----- weekly / monthly reports ------------------------------------

    def weekly_report(self, account_id: str, week: str | None = None) -> dict:
        if week is None:
            today = datetime.now(timezone.utc).replace(tzinfo=None).date()
            monday = today - timedelta(days=today.weekday())
            week = self._week_key(datetime(monday.year, monday.month, monday.day))

        start, end = self._parse_week(week)
        agg = self._aggregate_period(account_id, start, end)

        prev_start = start - timedelta(days=7)
        prev_end = start
        prev_week = self._week_key(prev_start)
        prev_agg = self._aggregate_period(account_id, prev_start, prev_end)

        return {
            "week": week,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_income_cents": agg["income_cents"],
            "total_expense_cents": agg["expense_cents"],
            "net_cents": agg["net_cents"],
            "transaction_count": agg["transaction_count"],
            "expenses_by_category": agg["expenses_by_category"],
            "previous_period": prev_week,
            "previous_total_income_cents": prev_agg["income_cents"],
            "previous_total_expense_cents": prev_agg["expense_cents"],
            "previous_net_cents": prev_agg["net_cents"],
        }

    def weekly_trend(self, account_id: str, weeks: int = 8) -> list[dict]:
        today = datetime.now(timezone.utc).replace(tzinfo=None).date()
        current_monday = today - timedelta(days=today.weekday())
        oldest_monday = current_monday - timedelta(weeks=weeks - 1)

        result: list[dict] = []
        for i in range(weeks):
            monday = oldest_monday + timedelta(weeks=i)
            start = datetime(monday.year, monday.month, monday.day)
            end = start + timedelta(days=7)
            agg = self._aggregate_period(account_id, start, end)
            result.append({
                "week": self._week_key(start),
                "income_cents": agg["income_cents"],
                "expense_cents": agg["expense_cents"],
            })
        return result

    def monthly_report(self, account_id: str, month: str | None = None) -> dict:
        if month is None:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            month = f"{now.year:04d}-{now.month:02d}"

        start, end = self._parse_month(month)
        agg = self._aggregate_period(account_id, start, end)

        # previous month
        year = start.year
        month_no = start.month
        prev_key = self._prev_month_key(year, month_no)
        prev_start, prev_end = self._parse_month(prev_key)
        prev_agg = self._aggregate_period(account_id, prev_start, prev_end)

        return {
            "month": month,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_income_cents": agg["income_cents"],
            "total_expense_cents": agg["expense_cents"],
            "net_cents": agg["net_cents"],
            "transaction_count": agg["transaction_count"],
            "expenses_by_category": agg["expenses_by_category"],
            "previous_period": prev_key,
            "previous_total_income_cents": prev_agg["income_cents"],
            "previous_total_expense_cents": prev_agg["expense_cents"],
            "previous_net_cents": prev_agg["net_cents"],
        }