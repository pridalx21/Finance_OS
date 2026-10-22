"""Debts Plugin — Erfassen und Verwalten von Schulden.

Ergänzt Schulden-Tracking (Verbindlichkeiten und Forderungen) ohne
Änderungen am Kern.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Session, relationship

from app.db.database import Base, get_db
from app.plugins import FinancePlugin
from app.models.account import Account


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _norm_type(value: Optional[str]) -> str:
    if not value:
        return "OWED"
    v = str(value).strip().upper()
    if v in {"OWED", "DEBT", "LIABILITY", "PAYABLE", "SCHULD", "VERBINDLICHKEIT"}:
        return "OWED"
    if v in {"RECEIVABLE", "CREDIT", "OWED_TO_ME", "FORDERUNG", "ASSET"}:
        return "RECEIVABLE"
    return v


def _norm_status(value: Optional[str]) -> str:
    if not value:
        return "OPEN"
    v = str(value).strip().upper()
    mapping = {
        "OPEN": "OPEN", "OFFEN": "OPEN",
        "PAID": "PAID", "BEZAHLT": "PAID",
        "CANCELLED": "CANCELLED", "CANCELED": "CANCELLED", "STORNIERT": "CANCELLED",
        "OVERDUE": "OVERDUE", "ÜBERFÄLLIG": "OVERDUE", "UEBERFAELLIG": "OVERDUE",
    }
    return mapping.get(v, v)


# ----- Datenmodell -----

class DebtDebt(Base):
    __tablename__ = "plugin_debt_debts"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    creditor = Column(String(200), nullable=False)
    type = Column(String(20), nullable=False, default="OWED")  # OWED / RECEIVABLE
    amount_cents = Column(Integer, nullable=False)
    remaining_cents = Column(Integer, nullable=False)
    interest_rate = Column(Numeric(precision=6, scale=2), nullable=True)  # Prozent
    due_date = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="OPEN")
    description = Column(String(500), nullable=True)
    idempotency_key = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    archived_at = Column(DateTime, nullable=True)

    account = relationship("Account")
    payments = relationship("DebtDebtPayment", back_populates="debt", cascade="all, delete-orphan")


class DebtDebtPayment(Base):
    __tablename__ = "plugin_debt_payments"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    debt_id = Column(String, ForeignKey("plugin_debt_debts.id"), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    date = Column(DateTime, nullable=False, default=_utcnow)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    debt = relationship("DebtDebt", back_populates="payments")


# ----- Schemas -----

class DebtCreate(BaseModel):
    account_id: Optional[str] = None
    creditor: Optional[str] = None
    counterparty: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    type: Optional[str] = None
    amount_cents: Optional[int] = Field(None, gt=0)
    amount: Optional[int] = None  # Alias (in Rappen/Cent)
    interest_rate: Optional[Decimal] = None
    interest_rate_percent: Optional[Decimal] = None
    due_date: Optional[str] = None
    due: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    note: Optional[str] = None
    idempotency_key: Optional[str] = None


class DebtUpdate(BaseModel):
    creditor: Optional[str] = None
    counterparty: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    amount_cents: Optional[int] = Field(None, gt=0)
    remaining_cents: Optional[int] = Field(None, ge=0)
    interest_rate: Optional[Decimal] = None
    due_date: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    note: Optional[str] = None
    archived: Optional[bool] = None


class DebtRead(BaseModel):
    id: str
    account_id: Optional[str] = None
    creditor: str
    counterparty: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    type: str
    amount_cents: int
    remaining_cents: int
    balance_cents: Optional[int] = None
    paid_cents: Optional[int] = None
    interest_rate: Optional[Decimal] = None
    due_date: Optional[datetime] = None
    status: str
    description: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DebtPaymentCreate(BaseModel):
    debt_id: Optional[str] = None
    amount_cents: Optional[int] = Field(None, gt=0)
    amount: Optional[int] = None
    date: Optional[str] = None
    note: Optional[str] = None
    description: Optional[str] = None


class DebtPaymentRead(BaseModel):
    id: str
    debt_id: str
    amount_cents: int
    date: datetime
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DebtSummary(BaseModel):
    total_debt_cents: int = 0
    total_receivable_cents: int = 0
    open_debt_cents: int = 0
    open_receivable_cents: int = 0
    total_open_cents: int = 0
    count: int = 0
    open_count: int = 0
    paid_count: int = 0


# ----- Helpers -----

def _debt_read(d: DebtDebt) -> DebtRead:
    paid = d.amount_cents - d.remaining_cents
    return DebtRead(
        id=d.id,
        account_id=d.account_id,
        creditor=d.creditor,
        counterparty=d.creditor,
        name=d.creditor,
        title=d.description or d.creditor,
        type=d.type,
        amount_cents=d.amount_cents,
        remaining_cents=d.remaining_cents,
        balance_cents=d.remaining_cents,
        paid_cents=paid,
        interest_rate=d.interest_rate,
        due_date=d.due_date,
        status=d.status,
        description=d.description,
        note=d.description,
        created_at=d.created_at,
        archived_at=d.archived_at,
    )


def _resolve_create(data: DebtCreate):
    creditor = data.creditor or data.counterparty or data.name or data.title
    if not creditor:
        creditor = "Unbekannt"
    creditor = str(creditor).strip()
    if not creditor:
        creditor = "Unbekannt"

    amount = data.amount_cents
    if amount is None and data.amount is not None:
        amount = data.amount
    if amount is None or amount <= 0:
        raise HTTPException(status_code=422, detail="amount_cents muss > 0 sein")

    interest = data.interest_rate
    if interest is None:
        interest = data.interest_rate_percent

    due_raw = data.due_date if data.due_date is not None else data.due
    due = _parse_dt(due_raw)
    if due_raw is not None and due is None:
        raise HTTPException(status_code=422, detail="Ungültiges due_date")

    dtype = _norm_type(data.type)
    status = _norm_status(data.status)
    description = data.description if data.description is not None else data.note

    return creditor, int(amount), interest, due, dtype, status, description


# ----- Router -----

router = APIRouter(prefix="/api/debt", tags=["debt"])


@router.post("", response_model=DebtRead, status_code=201)
@router.post("/create", response_model=DebtRead, status_code=201)
def create_debt(data: DebtCreate, db: Session = Depends(get_db)):
    # Validate account if provided
    if data.account_id:
        account = db.query(Account).filter(Account.id == data.account_id).first()
        if not account or account.archived_at is not None:
            raise HTTPException(status_code=404, detail="Konto nicht gefunden")

    # Idempotency
    if data.idempotency_key:
        existing = db.query(DebtDebt).filter(DebtDebt.idempotency_key == data.idempotency_key).first()
        if existing:
            return _debt_read(existing)

    creditor, amount, interest, due, dtype, status, description = _resolve_create(data)

    debt = DebtDebt(
        id=str(uuid4()),
        account_id=data.account_id,
        creditor=creditor,
        type=dtype,
        amount_cents=amount,
        remaining_cents=amount,
        interest_rate=interest,
        due_date=due,
        status=status,
        description=description,
        idempotency_key=data.idempotency_key,
    )
    db.add(debt)
    db.commit()
    db.refresh(debt)
    return _debt_read(debt)


@router.get("", response_model=list[DebtRead])
@router.get("/list", response_model=list[DebtRead])
def list_debts(
    account_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
):
    query = db.query(DebtDebt)
    if account_id:
        query = query.filter(DebtDebt.account_id == account_id)
    if status:
        query = query.filter(DebtDebt.status == _norm_status(status))
    if type:
        query = query.filter(DebtDebt.type == _norm_type(type))
    if not include_archived:
        query = query.filter(DebtDebt.archived_at.is_(None))
    debts = query.order_by(DebtDebt.created_at.desc()).all()
    return [_debt_read(d) for d in debts]


@router.get("/summary", response_model=DebtSummary)
@router.get("/total", response_model=DebtSummary)
@router.get("/balance", response_model=DebtSummary)
@router.get("/overview", response_model=DebtSummary)
def debt_summary(
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(DebtDebt).filter(DebtDebt.archived_at.is_(None))
    if account_id:
        query = query.filter(DebtDebt.account_id == account_id)
    debts = query.all()

    total_debt = sum(d.amount_cents for d in debts if d.type == "OWED")
    total_recv = sum(d.amount_cents for d in debts if d.type == "RECEIVABLE")
    open_debt = sum(d.remaining_cents for d in debts if d.type == "OWED" and d.status != "PAID")
    open_recv = sum(d.remaining_cents for d in debts if d.type == "RECEIVABLE" and d.status != "PAID")
    open_count = sum(1 for d in debts if d.status != "PAID" and d.archived_at is None)
    paid_count = sum(1 for d in debts if d.status == "PAID")

    return DebtSummary(
        total_debt_cents=total_debt,
        total_receivable_cents=total_recv,
        open_debt_cents=open_debt,
        open_receivable_cents=open_recv,
        total_open_cents=open_debt + open_recv,
        count=len(debts),
        open_count=open_count,
        paid_count=paid_count,
    )


@router.get("/status", response_model=DebtSummary)
@router.get("/stats", response_model=DebtSummary)
def debt_status(
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return debt_summary(account_id=account_id, db=db)


@router.get("/{debt_id}", response_model=DebtRead)
def get_debt(debt_id: str, db: Session = Depends(get_db)):
    debt = db.query(DebtDebt).filter(DebtDebt.id == debt_id).first()
    if not debt:
        raise HTTPException(status_code=404, detail="Schuld nicht gefunden")
    return _debt_read(debt)


@router.patch("/{debt_id}", response_model=DebtRead)
def update_debt(debt_id: str, data: DebtUpdate, db: Session = Depends(get_db)):
    debt = db.query(DebtDebt).filter(DebtDebt.id == debt_id).first()
    if not debt:
        raise HTTPException(status_code=404, detail="Schuld nicht gefunden")

    if data.creditor is not None or data.counterparty is not None or data.name is not None:
        new_cred = data.creditor or data.counterparty or data.name
        if new_cred:
            debt.creditor = str(new_cred).strip()
    if data.type is not None:
        debt.type = _norm_type(data.type)
    if data.amount_cents is not None:
        debt.amount_cents = int(data.amount_cents)
        if debt.remaining_cents > debt.amount_cents:
            debt.remaining_cents = debt.amount_cents
    if data.remaining_cents is not None:
        if data.remaining_cents > debt.amount_cents:
            raise HTTPException(status_code=400, detail="Restbetrag darf Gesamtbetrag nicht überschreiten")
        debt.remaining_cents = int(data.remaining_cents)
    if data.interest_rate is not None:
        debt.interest_rate = data.interest_rate
    if data.due_date is not None:
        parsed = _parse_dt(data.due_date)
        if data.due_date and parsed is None:
            raise HTTPException(status_code=422, detail="Ungültiges due_date")
        debt.due_date = parsed
    if data.status is not None:
        debt.status = _norm_status(data.status)
    if data.description is not None:
        debt.description = data.description
    if data.note is not None:
        debt.description = data.note
    if data.archived is True:
        debt.archived_at = _utcnow()
        if debt.status not in ("PAID", "CANCELLED"):
            debt.status = "CANCELLED"

    # Auto-status
    if debt.remaining_cents <= 0:
        debt.remaining_cents = 0
        if debt.status not in ("CANCELLED",):
            debt.status = "PAID"
    elif debt.status == "PAID" and debt.remaining_cents > 0:
        debt.status = "OPEN"

    db.commit()
    db.refresh(debt)
    return _debt_read(debt)


@router.delete("/{debt_id}")
def delete_debt(debt_id: str, db: Session = Depends(get_db)):
    debt = db.query(DebtDebt).filter(DebtDebt.id == debt_id).first()
    if not debt:
        raise HTTPException(status_code=404, detail="Schuld nicht gefunden")
    debt.archived_at = _utcnow()
    if debt.status not in ("PAID",):
        debt.status = "CANCELLED"
    db.commit()
    return {"ok": True, "id": debt.id}


@router.post("/{debt_id}/payments", response_model=DebtPaymentRead, status_code=201)
@router.post("/{debt_id}/pay", response_model=DebtPaymentRead, status_code=201)
@router.post("/{debt_id}/payment", response_model=DebtPaymentRead, status_code=201)
def create_payment(debt_id: str, data: DebtPaymentCreate, db: Session = Depends(get_db)):
    debt = db.query(DebtDebt).filter(DebtDebt.id == debt_id).first()
    if not debt or debt.archived_at is not None:
        raise HTTPException(status_code=404, detail="Schuld nicht gefunden")

    amount = data.amount_cents
    if amount is None and data.amount is not None:
        amount = data.amount
    if amount is None or amount <= 0:
        raise HTTPException(status_code=422, detail="amount_cents muss > 0 sein")
    amount = int(amount)

    if amount > debt.remaining_cents:
        raise HTTPException(status_code=400, detail="Zahlung übersteigt Restschuld")

    pay_date = _parse_dt(data.date)
    if data.date is not None and pay_date is None:
        raise HTTPException(status_code=422, detail="Ungültiges Datum")
    if pay_date is None:
        pay_date = _utcnow()

    note = data.note if data.note is not None else data.description

    payment = DebtDebtPayment(
        id=str(uuid4()),
        debt_id=debt.id,
        amount_cents=amount,
        date=pay_date,
        note=note,
    )
    debt.remaining_cents -= amount
    if debt.remaining_cents <= 0:
        debt.remaining_cents = 0
        debt.status = "PAID"

    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


@router.get("/{debt_id}/payments", response_model=list[DebtPaymentRead])
def list_payments(debt_id: str, db: Session = Depends(get_db)):
    debt = db.query(DebtDebt).filter(DebtDebt.id == debt_id).first()
    if not debt:
        raise HTTPException(status_code=404, detail="Schuld nicht gefunden")
    payments = db.query(DebtDebtPayment).filter(DebtDebtPayment.debt_id == debt_id).order_by(DebtDebtPayment.date.desc()).all()
    return payments


@router.post("/payments", response_model=DebtPaymentRead, status_code=201)
@router.post("/payment", response_model=DebtPaymentRead, status_code=201)
@router.post("/pay", response_model=DebtPaymentRead, status_code=201)
def create_payment_flat(data: DebtPaymentCreate, db: Session = Depends(get_db)):
    if not data.debt_id:
        raise HTTPException(status_code=422, detail="debt_id ist erforderlich")
    # Reuse by calling logic manually
    debt = db.query(DebtDebt).filter(DebtDebt.id == data.debt_id).first()
    if not debt or debt.archived_at is not None:
        raise HTTPException(status_code=404, detail="Schuld nicht gefunden")

    amount = data.amount_cents
    if amount is None and data.amount is not None:
        amount = data.amount
    if amount is None or amount <= 0:
        raise HTTPException(status_code=422, detail="amount_cents muss > 0 sein")
    amount = int(amount)

    if amount > debt.remaining_cents:
        raise HTTPException(status_code=400, detail="Zahlung übersteigt Restschuld")

    pay_date = _parse_dt(data.date)
    if data.date is not None and pay_date is None:
        raise HTTPException(status_code=422, detail="Ungültiges Datum")
    if pay_date is None:
        pay_date = _utcnow()

    note = data.note if data.note is not None else data.description

    payment = DebtDebtPayment(
        id=str(uuid4()),
        debt_id=debt.id,
        amount_cents=amount,
        date=pay_date,
        note=note,
    )
    debt.remaining_cents -= amount
    if debt.remaining_cents <= 0:
        debt.remaining_cents = 0
        debt.status = "PAID"

    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


# ----- Plugin Class -----

class DebtPlugin(FinancePlugin):
    name = "debt"
    version = "0.1.0"

    def register(self, app):
        engine = app.state.db_engine
        from app.db.database import Base
        Base.metadata.create_all(bind=engine, tables=[
            DebtDebt.__table__,
            DebtDebtPayment.__table__,
        ])
        app.include_router(router)


PLUGIN = DebtPlugin()
