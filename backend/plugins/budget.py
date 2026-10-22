"""Budget Plugin — Sparziele und Budget-Überwachung.

Ergänzt Budget-Funktionalität ohne Änderungen am Kern.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Session, relationship

from app.db.database import Base, get_db
from app.plugins import FinancePlugin
from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.services.transaction_service import active_transactions


# ----- Datenmodell -----

class Budget(Base):
    __tablename__ = "plugin_budget_budgets"

    id = Column(String, primary_key=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    name = Column(String, nullable=False)
    limit_cents = Column(Integer, nullable=False)
    period = Column(String, nullable=False)  # "monthly", "yearly"
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("account_id", "category_id", "period", "start_date", name="uq_budget"),
    )

    account = relationship("Account")
    category = relationship("Category")


# ----- Schemas -----

class BudgetCreate(BaseModel):
    account_id: str
    category_id: str | None = None
    name: str = Field(..., min_length=1, max_length=100)
    limit_cents: int = Field(..., gt=0)
    period: str = Field(..., pattern="^(monthly|yearly)$")
    start_date: str  # ISO8601
    end_date: str | None = None


class BudgetRead(BaseModel):
    id: str
    account_id: str
    category_id: str | None
    name: str
    limit_cents: int
    period: str
    start_date: datetime
    end_date: datetime | None

    model_config = ConfigDict(from_attributes=True)

    def model_dump(self, *args, **kwargs):
        data = super().model_dump(*args, **kwargs)
        if data.get("start_date"):
            data["start_date"] = data["start_date"].isoformat()
        if data.get("end_date"):
            data["end_date"] = data["end_date"].isoformat()
        return data


class BudgetStatus(BaseModel):
    budget_id: str
    budget_name: str
    limit_cents: int
    spent_cents: int
    remaining_cents: int
    percentage_used: float


# ----- Router -----

router = APIRouter(prefix="/api/budget", tags=["budget"])


@router.post("", response_model=BudgetRead, status_code=201)
def create_budget(data: BudgetCreate, db: Session = Depends(get_db)):
    # Validate account exists
    account = db.query(Account).filter(Account.id == data.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")

    # Validate category if provided
    if data.category_id:
        cat = db.query(Category).filter(Category.id == data.category_id).first()
        if not cat:
            raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
        if cat.type != "EXPENSE":
            raise HTTPException(status_code=400, detail="Budget nur für Ausgaben-Kategorien möglich")

    from datetime import datetime
    from uuid import uuid4

    budget = Budget(
        id=str(uuid4()),
        account_id=data.account_id,
        category_id=data.category_id,
        name=data.name,
        limit_cents=data.limit_cents,
        period=data.period,
        start_date=datetime.fromisoformat(data.start_date),
        end_date=datetime.fromisoformat(data.end_date) if data.end_date else None,
    )
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


@router.get("", response_model=list[BudgetRead])
def list_budgets(account_id: str = Query(...), db: Session = Depends(get_db)):
    return db.query(Budget).filter(Budget.account_id == account_id).all()


@router.get("/status", response_model=list[BudgetStatus])
def budget_status(account_id: str = Query(...), db: Session = Depends(get_db)):
    """Calculate spent vs. limit for each budget."""
    from datetime import datetime, timezone

    budgets = db.query(Budget).filter(Budget.account_id == account_id).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    transactions = active_transactions(
        db.query(Transaction).filter(Transaction.account_id == account_id).all()
    )

    result = []
    for b in budgets:
        # Determine period start/end
        if b.period == "monthly":
            period_start = datetime(now.year, now.month, 1)
            if now.month == 12:
                period_end = datetime(now.year + 1, 1, 1)
            else:
                period_end = datetime(now.year, now.month + 1, 1)
        else:  # yearly
            period_start = datetime(now.year, 1, 1)
            period_end = datetime(now.year + 1, 1, 1)

        # Apply budget date range
        start = max(b.start_date, period_start)
        end = min(b.end_date, period_end) if b.end_date else period_end

        spent = sum(
            t.amount_cents for t in transactions
            if t.type == "EXPENSE"
            and start <= t.date < end
            and (not b.category_id or t.category_id == b.category_id)
        )
        remaining = max(0, b.limit_cents - spent)
        pct = (spent / b.limit_cents * 100) if b.limit_cents > 0 else 0

        result.append(BudgetStatus(
            budget_id=b.id,
            budget_name=b.name,
            limit_cents=b.limit_cents,
            spent_cents=spent,
            remaining_cents=remaining,
            percentage_used=round(pct, 1),
        ))
    return result


# ----- Plugin Class -----

class BudgetPlugin(FinancePlugin):
    name = "budget"
    version = "0.1.0"

    def register(self, app):
        # Create tables
        engine = app.state.db_engine
        from app.db.database import Base
        Base.metadata.create_all(bind=engine, tables=[Budget.__table__])

        # Register routes
        app.include_router(router)


PLUGIN = BudgetPlugin()