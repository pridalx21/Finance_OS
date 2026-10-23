"""Reconciliation Plugin — geführter Kontostandsabgleich.

Ein Abgleich speichert den tatsächlich gemeldeten Kontostand, den vom System
berechneten Kontostand und die Differenz. Es werden keine Buchungen erzeugt
und keine bestehenden Daten verändert.

Zeitliche Logik
---------------

Der erwartete Kontostand wird für den **Stichtag** berechnet:

* Buchungen nach dem Stichtag beeinflussen das Ergebnis nicht.
* Eine Stornierung wirkt erst ab dem Zeitpunkt, zu dem sie selbst gebucht
  wurde. Eine im Januar gebuchte Ausgabe, die im März storniert wurde, zählt
  am 31. Januar also noch - am 31. März nicht mehr.
* Ein gespeicherter Abgleich ist ein Snapshot: spätere Buchungen oder
  Stornierungen verändern ihn nicht. Der Abgleich bleibt abrufbar und die
  Differenz bleibt sichtbar, bis sie geklärt ist.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import Session, relationship

from app.db.database import Base, get_db
from app.plugins import FinancePlugin
from app.models.account import Account
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionCreate
from app.services.account_service import compute_balance
from app.services.transaction_service import TransactionService, emit_transaction_created


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_as_of(value) -> Optional[datetime]:
    """Parse a cut-off date.

    A date without a time component (e.g. ``2026-10-23``) is interpreted as
    the *end* of that day, so all bookings of that day are included.
    """
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    text = str(value).strip()
    if "T" not in text and " " not in text:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


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


# ----- Datenmodell --------------------------------------------------------

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
    idempotency_fingerprint = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    #: JSON list of the booking ids that produced the expected balance.
    #: Makes the snapshot reproducible even after later changes.
    basis_transaction_ids = Column(Text, nullable=True)

    account = relationship("Account")


# ----- Schemas ------------------------------------------------------------

class ReconciliationCreate(BaseModel):
    account_id: str
    actual_balance_cents: Optional[int] = None
    actual_balance: Optional[int] = None  # alias
    date: Optional[str] = None
    reconciliation_date: Optional[str] = None
    note: Optional[str] = None
    idempotency_key: Optional[str] = None
    #: Optionally book the difference as a correction transaction so the
    #: system balance matches the actual balance.
    create_transaction: bool = False


class ReconciliationRead(BaseModel):
    id: str
    account_id: str
    reconciliation_date: datetime
    actual_balance_cents: int
    expected_balance_cents: int
    difference_cents: int
    note: Optional[str] = None
    created_at: datetime
    basis_transaction_ids: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ExpectedBalanceRead(BaseModel):
    """System balance for a cut-off date (preview before saving)."""

    account_id: str
    date: datetime
    expected_balance_cents: int
    transaction_count: int


# ----- Helper -------------------------------------------------------------

def _expected_balance(db: Session, account_id: str, as_of: datetime):
    """Return (balance_cents, contributing transaction ids) for a cut-off date."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")
    result = compute_balance(db, account_id, as_of=as_of)
    if result is None:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")
    return result.balance_cents, result.transaction_ids


def _fingerprint(account_id: str, actual: int, client_date: Optional[str], note) -> str:
    """Fingerprint of the client payload.

    Only a date that was sent by the client is part of the fingerprint. A
    date that the server assigns ("now") must not be, otherwise a retry of
    the same request would be reported as a conflict.
    """
    raw = json.dumps(
        {
            "account_id": account_id,
            "actual_balance_cents": actual,
            "date": client_date,
            "note": note,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ----- Router -------------------------------------------------------------

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
    actual = int(actual)

    raw_date = data.reconciliation_date if data.reconciliation_date is not None else data.date
    as_of = _parse_as_of(raw_date) if raw_date is not None else _utcnow()
    if raw_date is not None and as_of is None:
        raise HTTPException(status_code=422, detail="Ungültiges Datum")
    if as_of is None:
        as_of = _utcnow()
    # Only a date sent by the client is part of the idempotency fingerprint.
    client_date = as_of.isoformat() if raw_date is not None else None

    if data.idempotency_key:
        existing = db.query(Reconciliation).filter(
            Reconciliation.idempotency_key == data.idempotency_key
        ).first()
        if existing:
            expected_fp = _fingerprint(data.account_id, actual, client_date, data.note)
            if existing.idempotency_fingerprint:
                if existing.idempotency_fingerprint != expected_fp:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet",
                    )
            elif (
                existing.account_id != data.account_id
                or existing.actual_balance_cents != actual
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet",
                )
            return _to_read(existing)

    expected, basis_ids = _expected_balance(db, data.account_id, as_of)
    diff = actual - expected

    correction_tx = None
    if data.create_transaction and diff != 0:
        tx_type = "INCOME" if diff > 0 else "EXPENSE"
        correction_tx = TransactionService(db).create(
            TransactionCreate(
                account_id=data.account_id,
                type=tx_type,
                amount_cents=abs(diff),
                description="Korrektur Kontostandsabgleich",
                date=_utcnow(),
                idempotency_key=f"reconciliation:{data.idempotency_key}" if data.idempotency_key else None,
            ),
            commit=False,
        )

    rec = Reconciliation(
        id=str(uuid4()),
        account_id=data.account_id,
        reconciliation_date=as_of,
        actual_balance_cents=actual,
        expected_balance_cents=expected,
        difference_cents=diff,
        note=data.note,
        idempotency_key=data.idempotency_key,
        idempotency_fingerprint=(
            _fingerprint(data.account_id, actual, client_date, data.note)
            if data.idempotency_key
            else None
        ),
        basis_transaction_ids=json.dumps(basis_ids),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    if correction_tx is not None:
        emit_transaction_created(correction_tx, reversal=False)
    return _to_read(rec)


def _to_read(rec: Reconciliation) -> ReconciliationRead:
    """Build the read model (the basis is stored as JSON text)."""
    basis: list[str] = []
    if rec.basis_transaction_ids:
        try:
            parsed = json.loads(rec.basis_transaction_ids)
            if isinstance(parsed, list):
                basis = [str(x) for x in parsed]
        except (ValueError, TypeError):
            basis = []
    return ReconciliationRead(
        id=rec.id,
        account_id=rec.account_id,
        reconciliation_date=rec.reconciliation_date,
        actual_balance_cents=rec.actual_balance_cents,
        expected_balance_cents=rec.expected_balance_cents,
        difference_cents=rec.difference_cents,
        note=rec.note,
        created_at=rec.created_at,
        basis_transaction_ids=basis,
    )


@router.get("/expected-balance", response_model=ExpectedBalanceRead)
def expected_balance(
    account_id: str = Query(...),
    date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """System balance for a cut-off date - the value a reconciliation compares against."""
    raw_date = date
    as_of = _parse_as_of(raw_date) if raw_date is not None else _utcnow()
    if raw_date is not None and as_of is None:
        raise HTTPException(status_code=422, detail="Ungültiges Datum")
    expected, basis_ids = _expected_balance(db, account_id, as_of)
    return ExpectedBalanceRead(
        account_id=account_id,
        date=as_of,
        expected_balance_cents=expected,
        transaction_count=len(basis_ids),
    )


@router.get("", response_model=list[ReconciliationRead])
def list_reconciliations(
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Reconciliation)
    if account_id:
        query = query.filter(Reconciliation.account_id == account_id)
    recs = query.order_by(Reconciliation.created_at.desc()).all()
    return [_to_read(r) for r in recs]


@router.get("/{rec_id}", response_model=ReconciliationRead)
def get_reconciliation(rec_id: str, db: Session = Depends(get_db)):
    rec = db.query(Reconciliation).filter(Reconciliation.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Abgleich nicht gefunden")
    return _to_read(rec)


# ----- Plugin Class -------------------------------------------------------

class ReconciliationPlugin(FinancePlugin):
    name = "reconciliation"
    version = "0.2.0"

    def register(self, app):
        engine = app.state.db_engine
        from app.db.database import Base
        Base.metadata.create_all(bind=engine, tables=[Reconciliation.__table__])
        app.include_router(router)


PLUGIN = ReconciliationPlugin()
