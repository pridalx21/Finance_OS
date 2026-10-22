"""Reconciliation Plugin — geführter Kontostandsabgleich.

Ergänzt Kontostandsabgleich ohne Änderungen am Kern. Ein Abgleich
speichert den tatsächlichen Kontostand, den vom System berechneten
Kontostand und die Differenz. Es werden keine Buchungen erzeugt und
keine bestehenden Daten verändert.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Session, relationship

from app.db.database import Base, get_db
from app.plugins import FinancePlugin
from app.models.account import Account
from app.models.transaction import Transaction
from app.services.transaction_service import active_transactions


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


# ----- Datenmodell -----

class Reconciliation(Base):
    __tablename__ = "plugin_reconciliation_reconciliations"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)
    reconciliation_date = Column(DateTime, nullable=False)
    actual_balance_cents = Column(Integer, nullable=False)
    expected_balance_cents = Column(Integer, nullable=False)
    difference_cents = Column(Integer, nullable=False)
    note = Column(String(500), nullable=True)
    idempotency_key = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    account = relationship("Account")


# ----- Schemas -----

class ReconciliationCreate(BaseModel):
    account_id: str
    actual_balance_cents: Optional[int] = None
    actual_balance: Optional[int] = None  # alias
    date: Optional[str] = None
    reconciliation_date: Optional[str] = None
    note: Optional[str] = None
    idempotency_key: Optional[str] = None


class ReconciliationRead(BaseModel):
    id: str
    account_id: str
    reconciliation_date: datetime
    actual_balance_cents: int
    expected_balance_cents: int
    difference_cents: int
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----- Helper -----

def _expected_balance(db: Session, account_id: str, as_of: datetime) -> int:
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")
    txs = db.query(Transaction).filter(Transaction.account_id == account_id).all()
    active = active_transactions(txs)
    active = [t for t in active if t.date <= as_of]
    income = sum(t.amount_cents for t in active if t.type == "INCOME")
    expense = sum(t.amount_cents for t in active if t.type == "EXPENSE")
    return account.initial_balance_cents + income - expense


# ----- Router -----

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


@router.post("", response_model=ReconciliationRead, status_code=201)
def create_reconciliation(data: ReconciliationCreate, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == data.account_id).first()
    if not account or account.archived_at is not None:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")

    actual = data.actual_balance_cents
    if actual is None and data.actual_balance is not None:
        actual = data.actual_balance
    if actual is None:
        raise HTTPException(status_code=422, detail="actual_balance_cents ist erforderlich")

    raw_date = data.reconciliation_date if data.reconciliation_date is not None else data.date
    as_of = _parse_dt(raw_date) if raw_date is not None else _utcnow()
    if raw_date is not None and as_of is None:
        raise HTTPException(status_code=422, detail="Ungültiges Datum")
    if as_of is None:
        as_of = _utcnow()

    if data.idempotency_key:
        existing = db.query(Reconciliation).filter(
            Reconciliation.idempotency_key == data.idempotency_key
        ).first()
        if existing:
            return existing

    expected = _expected_balance(db, data.account_id, as_of)
    diff = int(actual) - expected

    rec = Reconciliation(
        id=str(uuid4()),
        account_id=data.account_id,
        reconciliation_date=as_of,
        actual_balance_cents=int(actual),
        expected_balance_cents=expected,
        difference_cents=diff,
        note=data.note,
        idempotency_key=data.idempotency_key,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.get("", response_model=list[ReconciliationRead])
def list_reconciliations(
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Reconciliation)
    if account_id:
        query = query.filter(Reconciliation.account_id == account_id)
    return query.order_by(Reconciliation.created_at.desc()).all()


@router.get("/{rec_id}", response_model=ReconciliationRead)
def get_reconciliation(rec_id: str, db: Session = Depends(get_db)):
    rec = db.query(Reconciliation).filter(Reconciliation.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Abgleich nicht gefunden")
    return rec


# ----- Plugin Class -----

class ReconciliationPlugin(FinancePlugin):
    name = "reconciliation"
    version = "0.1.0"

    def register(self, app):
        engine = app.state.db_engine
        from app.db.database import Base
        Base.metadata.create_all(bind=engine, tables=[Reconciliation.__table__])
        app.include_router(router)


PLUGIN = ReconciliationPlugin()
