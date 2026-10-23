"""Debts Plugin — Schulden und Forderungen.

Erfasst Verbindlichkeiten (OWED) und Forderungen (RECEIVABLE) mit ihren
Rückzahlungen. Das Plugin ändert den Kern nicht, benutzt aber die
Buchungslogik des Kerns (:mod:`app.services.transaction_service`).

Fachliche Regeln
-----------------

* Der ursprüngliche Betrag ist immer positiv, jede Zahlung ist positiv.
* Der Restbetrag wird **immer** aus dem ursprünglichen Betrag und den
  gültigen Zahlungen berechnet (``amount - Summe der nicht stornierten
  Zahlungen + Korrektur``). Er wird nie durch eine Einzeldifferenz
  weitergebucht, deshalb kann er nicht auseinanderlaufen.
* Eine Zahlung übersteigt den Restbetrag nie (Überzahlung wird abgelehnt).
* Eine vollständig bezahlte Schuld hat Restbetrag 0 und Status ``PAID``.
* Eine offene Schuld wird nicht allein durch das Verstreichen eines
  Fälligkeitsdatums als bezahlt betrachtet; ``is_overdue`` ist ein
  abgeleiteter Anzeigewert und ändert den gespeicherten Status nicht.
* Eine Rückzahlung kann optional als Buchung auf einem Konto verknüpft
  werden. Die Richtung folgt aus der Art der Schuld: eine eigene Schuld
  wird zur Ausgabe, eine erhaltene Rückzahlung einer Forderung zur Einnahme.
  Ohne Verknüpfung bleibt das Feld ``transaction_id`` leer - die Zahlung ist
  dann ausdrücklich "ohne Kontobewegung" erfasst.
* Zahlungen, Buchung und Anpassung des Restbetrags werden in **einer**
  Datenbanktransaktion gespeichert.
* Jede Zahlung trägt einen Idempotenzschlüssel. Ein wiederholter Request
  mit demselben Schlüssel erzeugt keine zweite Zahlung; mit abweichendem
  Inhalt führt er zu einem Konflikt (HTTP 409).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Numeric, Index, func
from sqlalchemy.orm import Session, relationship

from app.db.database import Base, get_db
from app.plugins import FinancePlugin
from app.models.account import Account
from app.schemas.transaction import TransactionCreate
from app.services.transaction_service import TransactionService, emit_transaction_created


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fingerprint(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


# ----- Fachliche Konstanten ----------------------------------------------

DEBT_TYPE_OWED = "OWED"
DEBT_TYPE_RECEIVABLE = "RECEIVABLE"
DEBT_TYPES = (DEBT_TYPE_OWED, DEBT_TYPE_RECEIVABLE)

STATUS_OPEN = "OPEN"
STATUS_PAID = "PAID"
STATUS_CANCELLED = "CANCELLED"
STATUS_OVERDUE = "OVERDUE"
DEBT_STATUSES = (STATUS_OPEN, STATUS_PAID, STATUS_CANCELLED, STATUS_OVERDUE)

_TYPE_ALIASES = {
    "OWED": DEBT_TYPE_OWED,
    "DEBT": DEBT_TYPE_OWED,
    "LIABILITY": DEBT_TYPE_OWED,
    "PAYABLE": DEBT_TYPE_OWED,
    "SCHULD": DEBT_TYPE_OWED,
    "VERBINDLICHKEIT": DEBT_TYPE_OWED,
    "RECEIVABLE": DEBT_TYPE_RECEIVABLE,
    "CREDIT": DEBT_TYPE_RECEIVABLE,
    "OWED_TO_ME": DEBT_TYPE_RECEIVABLE,
    "FORDERUNG": DEBT_TYPE_RECEIVABLE,
    "ASSET": DEBT_TYPE_RECEIVABLE,
}

_STATUS_ALIASES = {
    "OPEN": STATUS_OPEN,
    "OFFEN": STATUS_OPEN,
    "PAID": STATUS_PAID,
    "BEZAHLT": STATUS_PAID,
    "CANCELLED": STATUS_CANCELLED,
    "CANCELED": STATUS_CANCELLED,
    "STORNIERT": STATUS_CANCELLED,
    "OVERDUE": STATUS_OVERDUE,
    "UEBERFAELLIG": STATUS_OVERDUE,
}


def _norm_type(value: Optional[str]) -> str:
    """Map a type alias to the canonical type. Unknown types are rejected."""
    if not value:
        return DEBT_TYPE_OWED
    key = str(value).strip().upper()
    if key in _TYPE_ALIASES:
        return _TYPE_ALIASES[key]
    raise HTTPException(
        status_code=422,
        detail=f"Ungültiger Typ '{value}'. Erlaubt sind: OWED (Schuld), RECEIVABLE (Forderung)",
    )


def _norm_status(value: Optional[str]) -> str:
    """Map a status alias to the canonical status. Unknown statuses are rejected."""
    if not value:
        return STATUS_OPEN
    key = str(value).strip().upper()
    if key in _STATUS_ALIASES:
        return _STATUS_ALIASES[key]
    raise HTTPException(
        status_code=422,
        detail=f"Ungültiger Status '{value}'. Erlaubt sind: {', '.join(DEBT_STATUSES)}",
    )


def _derive_status(current: str, remaining_cents: int, archived: bool) -> str:
    """Status from the remaining amount.

    * archived -> CANCELLED
    * nothing left to pay -> PAID
    * a debt that was fully paid and now has an open amount -> OPEN again
    * every other status (OPEN, OVERDUE, CANCELLED) is kept
    """
    if archived:
        return STATUS_CANCELLED
    if remaining_cents <= 0:
        return STATUS_PAID
    if current == STATUS_PAID:
        return STATUS_OPEN
    return current


# ----- Datenmodell --------------------------------------------------------

class DebtsDebt(Base):
    __tablename__ = "plugin_debts_debts"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    creditor = Column(String(200), nullable=False)
    type = Column(String(20), nullable=False, default=DEBT_TYPE_OWED)  # OWED / RECEIVABLE
    amount_cents = Column(Integer, nullable=False)
    remaining_cents = Column(Integer, nullable=False)
    interest_rate = Column(Numeric(precision=6, scale=2), nullable=True)  # Prozent
    due_date = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default=STATUS_OPEN)
    description = Column(String(500), nullable=True)
    idempotency_key = Column(String, unique=True, nullable=True)
    idempotency_fingerprint = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    archived_at = Column(DateTime, nullable=True)
    #: Documented manual correction of the remaining amount (in Rappen).
    #: remaining = amount - paid payments + correction
    correction_cents = Column(Integer, nullable=False, default=0)

    account = relationship("Account")
    payments = relationship("DebtsDebtPayment", back_populates="debt", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_plugin_debts_debts_account_id", "account_id"),
    )


class DebtsDebtPayment(Base):
    __tablename__ = "plugin_debts_payments"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    debt_id = Column(String, ForeignKey("plugin_debts_debts.id"), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    date = Column(DateTime, nullable=False, default=_utcnow)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    #: Client supplied key that makes a repeated request a no-op.
    idempotency_key = Column(String, nullable=True)
    idempotency_fingerprint = Column(String(64), nullable=True)
    #: Booking on an account created for this payment (NULL = without account movement)
    transaction_id = Column(String, ForeignKey("transactions.id"), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancel_reason = Column(String(200), nullable=True)

    debt = relationship("DebtsDebt", back_populates="payments")

    __table_args__ = (
        Index("ix_plugin_debts_payments_debt_id", "debt_id"),
        Index(
            "ux_plugin_debts_payments_idempotency_key",
            "idempotency_key",
            unique=True,
        ),
    )


# ----- Schemas ------------------------------------------------------------

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
    payment_count: int = 0
    correction_cents: int = 0
    is_overdue: bool = False
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
    #: Book the payment on an account (expense for OWED, income for RECEIVABLE)
    create_transaction: bool = False
    #: Account for the booking. Defaults to the account of the debt.
    account_id: Optional[str] = None
    idempotency_key: Optional[str] = None


class DebtPaymentRead(BaseModel):
    id: str
    debt_id: str
    amount_cents: int
    date: datetime
    note: Optional[str] = None
    created_at: datetime
    idempotency_key: Optional[str] = None
    transaction_id: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None
    is_cancelled: bool = False

    model_config = ConfigDict(from_attributes=True)


class DebtSummary(BaseModel):
    total_debt_cents: int = 0
    total_receivable_cents: int = 0
    open_debt_cents: int = 0
    open_receivable_cents: int = 0
    #: Sum of both open positions. Not a net value - use net_open_cents for that.
    total_open_cents: int = 0
    #: Open receivables minus open debts (the net position).
    net_open_cents: int = 0
    count: int = 0
    open_count: int = 0
    paid_count: int = 0
    cancelled_count: int = 0
    #: Number of archived debts (they are not part of the amounts above).
    archived_count: int = 0


# ----- Service ------------------------------------------------------------

class DebtService:
    """Business rules for debts and their payments."""

    def __init__(self, db: Session):
        self.db = db

    # ----- helpers --------------------------------------------------------

    def _get_debt(self, debt_id: str) -> DebtsDebt:
        return self.get(debt_id)

    def _paid_cents(self, debt_id: str) -> int:
        """Sum of the valid (not cancelled) payments of a debt."""
        total = (
            self.db.query(func.coalesce(func.sum(DebtsDebtPayment.amount_cents), 0))
            .filter(
                DebtsDebtPayment.debt_id == debt_id,
                DebtsDebtPayment.cancelled_at.is_(None),
            )
            .scalar()
        )
        return int(total or 0)

    def payment_count(self, debt_id: str) -> int:
        return (
            self.db.query(DebtsDebtPayment)
            .filter(
                DebtsDebtPayment.debt_id == debt_id,
                DebtsDebtPayment.cancelled_at.is_(None),
            )
            .count()
        )

    def get(self, debt_id: str) -> DebtsDebt:
        """Return a debt or raise HTTP 404."""
        debt = self.db.query(DebtsDebt).filter(DebtsDebt.id == debt_id).first()
        if not debt:
            raise HTTPException(status_code=404, detail="Schuld nicht gefunden")
        return debt

    def _recompute(self, debt: DebtsDebt) -> None:
        """Recalculate the remaining amount and the status of a debt."""
        paid = self._paid_cents(debt.id)
        remaining = debt.amount_cents - paid + int(debt.correction_cents or 0)
        debt.remaining_cents = max(0, remaining)
        debt.status = _derive_status(
            debt.status, debt.remaining_cents, debt.archived_at is not None
        )

    def _validate_account(self, account_id: str) -> Account:
        account = self.db.query(Account).filter(Account.id == account_id).first()
        if account is None or account.archived_at is not None:
            raise HTTPException(status_code=404, detail="Konto nicht gefunden")
        return account

    # ----- debts ----------------------------------------------------------

    def create(self, data: DebtCreate) -> DebtsDebt:
        if data.account_id:
            self._validate_account(data.account_id)

        creditor, amount, interest, due, dtype, status, description = self._resolve_create(data)

        if data.idempotency_key:
            existing = (
                self.db.query(DebtsDebt)
                .filter(DebtsDebt.idempotency_key == data.idempotency_key)
                .first()
            )
            if existing:
                self._check_idempotency(existing, data, creditor, amount, dtype, status)
                return existing

        debt = DebtsDebt(
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
            idempotency_fingerprint=(
                self._fingerprint(data, creditor, amount, dtype, status, interest, due, description)
                if data.idempotency_key
                else None
            ),
        )
        self.db.add(debt)
        self.db.commit()
        self.db.refresh(debt)
        return debt

    def _resolve_create(self, data: DebtCreate):
        creditor = data.creditor or data.counterparty or data.name or data.title
        creditor = str(creditor).strip() if creditor else ""
        if not creditor:
            raise HTTPException(
                status_code=422,
                detail="Gläubiger bzw. Gegenpartei ist erforderlich",
            )

        amount = data.amount_cents if data.amount_cents is not None else data.amount
        if amount is None or int(amount) <= 0:
            raise HTTPException(status_code=422, detail="amount_cents muss > 0 sein")
        amount = int(amount)

        interest = data.interest_rate if data.interest_rate is not None else data.interest_rate_percent

        due_raw = data.due_date if data.due_date is not None else data.due
        due = _parse_dt(due_raw)
        if due_raw is not None and due is None:
            raise HTTPException(status_code=422, detail="Ungültiges due_date")

        dtype = _norm_type(data.type)
        status = _norm_status(data.status)
        description = data.description if data.description is not None else data.note

        return creditor, amount, interest, due, dtype, status, description

    def _fingerprint(
        self,
        data: DebtCreate,
        creditor: str,
        amount: int,
        dtype: str,
        status: str,
        interest,
        due,
        description,
    ) -> str:
        return _fingerprint(
            {
                "account_id": data.account_id,
                "creditor": creditor,
                "type": dtype,
                "amount_cents": amount,
                "interest_rate": str(interest) if interest is not None else None,
                "due_date": due.isoformat() if due else None,
                "status": status,
                "description": description,
            }
        )

    def _check_idempotency(
        self,
        existing: DebtsDebt,
        data: DebtCreate,
        creditor: str,
        amount: int,
        dtype: str,
        status: str,
    ) -> None:
        """Raise HTTP 409 if the key is reused with a different payload."""
        if existing.idempotency_fingerprint:
            expected = self._fingerprint(
                data,
                creditor,
                amount,
                dtype,
                status,
                existing.interest_rate,
                existing.due_date,
                existing.description,
            )
            if existing.idempotency_fingerprint != expected:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet",
                )
            return

        # Row without fingerprint (written before the column existed)
        if (
            existing.creditor != creditor
            or existing.type != dtype
            or existing.amount_cents != amount
            or (existing.account_id or None) != (data.account_id or None)
        ):
            raise HTTPException(
                status_code=409,
                detail="Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet",
            )

    def update(self, debt_id: str, data: DebtUpdate) -> DebtsDebt:
        debt = self._get_debt(debt_id)

        if data.creditor is not None or data.counterparty is not None or data.name is not None:
            new_cred = data.creditor or data.counterparty or data.name
            new_cred = str(new_cred).strip() if new_cred else ""
            if not new_cred:
                raise HTTPException(
                    status_code=422,
                    detail="Gläubiger bzw. Gegenpartei darf nicht leer sein",
                )
            debt.creditor = new_cred

        if data.type is not None:
            debt.type = _norm_type(data.type)

        if data.amount_cents is not None:
            new_amount = int(data.amount_cents)
            paid = self._paid_cents(debt.id)
            if new_amount < paid:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Der Gesamtbetrag darf nicht kleiner sein als die bereits "
                        f"geleisteten Zahlungen ({paid} Rappen)"
                    ),
                )
            debt.amount_cents = new_amount

        if data.remaining_cents is not None:
            target = int(data.remaining_cents)
            if target > debt.amount_cents:
                raise HTTPException(
                    status_code=400,
                    detail="Restbetrag darf Gesamtbetrag nicht überschreiten",
                )
            paid = self._paid_cents(debt.id)
            # Documented manual correction: the remaining amount is kept in
            # `correction_cents` so that the rule
            # "remaining = amount - payments + correction" stays true.
            debt.correction_cents = target - (debt.amount_cents - paid)

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
        if data.archived is not None:
            if data.archived:
                debt.archived_at = _utcnow()
            else:
                debt.archived_at = None
                if debt.status == STATUS_CANCELLED:
                    debt.status = STATUS_OPEN

        self._recompute(debt)

        self.db.commit()
        self.db.refresh(debt)
        return debt

    def archive(self, debt_id: str) -> DebtsDebt:
        debt = self._get_debt(debt_id)
        debt.archived_at = _utcnow()
        self._recompute(debt)
        self.db.commit()
        self.db.refresh(debt)
        return debt

    # ----- payments -------------------------------------------------------

    def create_payment(self, debt_id: str, data: DebtPaymentCreate) -> DebtsDebtPayment:
        debt = self._get_debt(debt_id)
        if debt.archived_at is not None:
            raise HTTPException(status_code=409, detail="Schuld ist archiviert")
        if debt.status == STATUS_CANCELLED:
            raise HTTPException(status_code=409, detail="Schuld ist storniert")

        amount, pay_date, note = self._resolve_payment(data)
        if amount > debt.remaining_cents:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Zahlung übersteigt die Restschuld "
                    f"({debt.remaining_cents} Rappen)"
                ),
            )

        if data.idempotency_key:
            existing = (
                self.db.query(DebtsDebtPayment)
                .filter(DebtsDebtPayment.idempotency_key == data.idempotency_key)
                .first()
            )
            if existing:
                self._check_payment_idempotency(existing, data, debt, amount, pay_date, note)
                return existing

        account = self._resolve_booking_account(debt, data)

        payment = DebtsDebtPayment(
            id=str(uuid4()),
            debt_id=debt.id,
            amount_cents=amount,
            date=pay_date,
            note=note,
            idempotency_key=data.idempotency_key,
            idempotency_fingerprint=(
                self._payment_fingerprint(
                    debt, data, amount, pay_date, note, self._booking_account_id(debt, data)
                )
                if data.idempotency_key
                else None
            ),
        )
        self.db.add(payment)
        self.db.flush()

        transaction = None
        if data.create_transaction:
            transaction = self._book_payment(debt, payment, account)
            # The booking is linked to the payment (nullable -> "ohne Kontobewegung")
            payment.transaction_id = transaction.id

        self._recompute(debt)

        # Payment, booking and the new remaining amount are stored together.
        self.db.commit()
        self.db.refresh(payment)
        if transaction is not None:
            emit_transaction_created(transaction, reversal=False)
        return payment

    def _resolve_payment(self, data: DebtPaymentCreate):
        amount = data.amount_cents if data.amount_cents is not None else data.amount
        if amount is None or int(amount) <= 0:
            raise HTTPException(status_code=422, detail="amount_cents muss > 0 sein")
        amount = int(amount)

        pay_date = _parse_dt(data.date)
        if data.date is not None and pay_date is None:
            raise HTTPException(status_code=422, detail="Ungültiges Datum")
        if pay_date is None:
            pay_date = _utcnow()

        note = data.note if data.note is not None else data.description
        return amount, pay_date, note

    def _booking_account_id(
        self, debt: DebtsDebt, data: DebtPaymentCreate
    ) -> Optional[str]:
        """Account that a booking would use (None when nothing is booked)."""
        if not data.create_transaction:
            return None
        return data.account_id or debt.account_id

    def _resolve_booking_account(
        self, debt: DebtsDebt, data: DebtPaymentCreate
    ) -> Optional[Account]:
        """Account for the booking (None if the payment is booked nowhere)."""
        account_id = self._booking_account_id(debt, data)
        if not account_id:
            if data.create_transaction:
                raise HTTPException(
                    status_code=422,
                    detail="Für die Buchung wird ein Konto benötigt "
                    "(account_id der Schuld oder eigener account_id)",
                )
            return None
        return self._validate_account(account_id)

    def _book_payment(
        self,
        debt: DebtsDebt,
        payment: DebtsDebtPayment,
        account: Account,
    ):
        """Create the booking for a payment (without committing)."""
        tx_type = "EXPENSE" if debt.type == DEBT_TYPE_OWED else "INCOME"
        description = payment.note or f"Rückzahlung {debt.creditor}"
        service = TransactionService(self.db)
        return service.create(
            TransactionCreate(
                account_id=account.id,
                type=tx_type,
                amount_cents=payment.amount_cents,
                description=description,
                date=payment.date,
                idempotency_key=f"debt-payment:{payment.id}",
            ),
            commit=False,
        )

    def _payment_fingerprint(
        self,
        debt: DebtsDebt,
        data: DebtPaymentCreate,
        amount: int,
        pay_date: datetime,
        note,
        account_id: Optional[str],
    ) -> str:
        return _fingerprint(
            {
                "debt_id": debt.id,
                "amount_cents": amount,
                # Only a date sent by the client is part of the payload.
                "date": pay_date.isoformat() if data.date is not None else None,
                "note": note,
                "create_transaction": bool(data.create_transaction),
                "account_id": account_id,
            }
        )

    def _check_payment_idempotency(
        self,
        existing: DebtsDebtPayment,
        data: DebtPaymentCreate,
        debt: DebtsDebt,
        amount: int,
        pay_date: datetime,
        note,
    ) -> None:
        if existing.idempotency_fingerprint:
            expected = self._payment_fingerprint(
                debt,
                data,
                amount,
                pay_date,
                note,
                self._booking_account_id(debt, data),
            )
            if existing.idempotency_fingerprint != expected:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet",
                )
            return

        # Row without fingerprint (written before the column existed)
        if (
            existing.debt_id != debt.id
            or existing.amount_cents != amount
            or (existing.note or None) != (note or None)
        ):
            raise HTTPException(
                status_code=409,
                detail="Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet",
            )

    def cancel_payment(self, payment_id: str, reason: Optional[str] = None) -> DebtsDebtPayment:
        """Void a payment.

        The payment row stays in the database and is marked as cancelled, so
        the history is preserved. The remaining amount is recalculated and a
        linked booking is voided with a storno.
        """
        payment = (
            self.db.query(DebtsDebtPayment)
            .filter(DebtsDebtPayment.id == payment_id)
            .first()
        )
        if not payment:
            raise HTTPException(status_code=404, detail="Zahlung nicht gefunden")

        if payment.cancelled_at is not None:
            # Already voided - repeating the request changes nothing.
            return payment

        payment.cancelled_at = _utcnow()
        payment.cancel_reason = reason
        # Make the cancellation visible to the recalculation below.
        self.db.flush()

        reversal = None
        if payment.transaction_id:
            reversal = TransactionService(self.db).reverse(payment.transaction_id, commit=False)

        debt = self._get_debt(payment.debt_id)
        self._recompute(debt)

        self.db.commit()
        self.db.refresh(payment)
        if reversal is not None:
            emit_transaction_created(reversal, reversal=True)
        return payment

    # ----- read -----------------------------------------------------------

    def list_payments(self, debt_id: str, include_cancelled: bool = True) -> list[DebtsDebtPayment]:
        self._get_debt(debt_id)
        query = self.db.query(DebtsDebtPayment).filter(DebtsDebtPayment.debt_id == debt_id)
        if not include_cancelled:
            query = query.filter(DebtsDebtPayment.cancelled_at.is_(None))
        return query.order_by(DebtsDebtPayment.date.desc()).all()


# ----- Read helpers -------------------------------------------------------

def _is_overdue(debt: DebtsDebt) -> bool:
    """Due date passed and the debt is still open.

    A passed due date never turns a debt into a paid one - it is only shown.
    """
    if debt.due_date is None:
        return False
    if debt.remaining_cents <= 0:
        return False
    if debt.archived_at is not None or debt.status == STATUS_CANCELLED:
        return False
    return debt.due_date < _utcnow()


def _debt_read(debt: DebtsDebt, service: DebtService) -> DebtRead:
    paid = debt.amount_cents + int(debt.correction_cents or 0) - debt.remaining_cents
    return DebtRead(
        id=debt.id,
        account_id=debt.account_id,
        creditor=debt.creditor,
        counterparty=debt.creditor,
        name=debt.creditor,
        title=debt.description or debt.creditor,
        type=debt.type,
        amount_cents=debt.amount_cents,
        remaining_cents=debt.remaining_cents,
        balance_cents=debt.remaining_cents,
        paid_cents=paid,
        payment_count=service.payment_count(debt.id),
        correction_cents=int(debt.correction_cents or 0),
        is_overdue=_is_overdue(debt),
        interest_rate=debt.interest_rate,
        due_date=debt.due_date,
        status=debt.status,
        description=debt.description,
        note=debt.description,
        created_at=debt.created_at,
        archived_at=debt.archived_at,
    )


def _payment_read(payment: DebtsDebtPayment) -> DebtPaymentRead:
    return DebtPaymentRead(
        id=payment.id,
        debt_id=payment.debt_id,
        amount_cents=payment.amount_cents,
        date=payment.date,
        note=payment.note,
        created_at=payment.created_at,
        idempotency_key=payment.idempotency_key,
        transaction_id=payment.transaction_id,
        cancelled_at=payment.cancelled_at,
        cancel_reason=payment.cancel_reason,
        is_cancelled=payment.cancelled_at is not None,
    )


# ----- Router -------------------------------------------------------------

router = APIRouter(prefix="/api/debts", tags=["debts"])


@router.post("", response_model=DebtRead, status_code=201)
@router.post("/create", response_model=DebtRead, status_code=201)
def create_debt(data: DebtCreate, db: Session = Depends(get_db)):
    service = DebtService(db)
    debt = service.create(data)
    return _debt_read(debt, service)


@router.get("", response_model=list[DebtRead])
@router.get("/list", response_model=list[DebtRead])
def list_debts(
    account_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
):
    service = DebtService(db)
    query = db.query(DebtsDebt)
    if account_id:
        query = query.filter(DebtsDebt.account_id == account_id)
    if status:
        query = query.filter(DebtsDebt.status == _norm_status(status))
    if type:
        query = query.filter(DebtsDebt.type == _norm_type(type))
    if not include_archived:
        query = query.filter(DebtsDebt.archived_at.is_(None))
    debts = query.order_by(DebtsDebt.created_at.desc()).all()
    return [_debt_read(d, service) for d in debts]


@router.get("/summary", response_model=DebtSummary)
@router.get("/total", response_model=DebtSummary)
@router.get("/balance", response_model=DebtSummary)
@router.get("/overview", response_model=DebtSummary)
def debt_summary(
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Liabilities and receivables are reported separately.

    Only debts that are neither paid nor cancelled count as "open".
    """
    query = db.query(DebtsDebt).filter(DebtsDebt.archived_at.is_(None))
    if account_id:
        query = query.filter(DebtsDebt.account_id == account_id)
    debts = query.all()

    archived_query = db.query(DebtsDebt).filter(DebtsDebt.archived_at.isnot(None))
    if account_id:
        archived_query = archived_query.filter(DebtsDebt.account_id == account_id)
    archived_count = archived_query.count()

    def is_open(d: DebtsDebt) -> bool:
        return d.status not in (STATUS_PAID, STATUS_CANCELLED)

    total_debt = sum(d.amount_cents for d in debts if d.type == DEBT_TYPE_OWED)
    total_recv = sum(d.amount_cents for d in debts if d.type == DEBT_TYPE_RECEIVABLE)
    open_debt = sum(d.remaining_cents for d in debts if d.type == DEBT_TYPE_OWED and is_open(d))
    open_recv = sum(
        d.remaining_cents for d in debts if d.type == DEBT_TYPE_RECEIVABLE and is_open(d)
    )

    return DebtSummary(
        total_debt_cents=total_debt,
        total_receivable_cents=total_recv,
        open_debt_cents=open_debt,
        open_receivable_cents=open_recv,
        total_open_cents=open_debt + open_recv,
        net_open_cents=open_recv - open_debt,
        count=len(debts),
        open_count=sum(1 for d in debts if is_open(d)),
        paid_count=sum(1 for d in debts if d.status == STATUS_PAID),
        cancelled_count=sum(1 for d in debts if d.status == STATUS_CANCELLED),
        archived_count=archived_count,
    )


@router.get("/status", response_model=DebtSummary)
@router.get("/stats", response_model=DebtSummary)
def debt_status(
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return debt_summary(account_id=account_id, db=db)


@router.get("/payments/{payment_id}", response_model=DebtPaymentRead)
def get_payment(payment_id: str, db: Session = Depends(get_db)):
    payment = (
        db.query(DebtsDebtPayment).filter(DebtsDebtPayment.id == payment_id).first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Zahlung nicht gefunden")
    return _payment_read(payment)


@router.post("/payments/{payment_id}/cancel", response_model=DebtPaymentRead)
@router.delete("/payments/{payment_id}", response_model=DebtPaymentRead)
def cancel_payment(
    payment_id: str,
    reason: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    service = DebtService(db)
    payment = service.cancel_payment(payment_id, reason=reason)
    return _payment_read(payment)


@router.get("/{debt_id}", response_model=DebtRead)
def get_debt(debt_id: str, db: Session = Depends(get_db)):
    service = DebtService(db)
    debt = service.get(debt_id)
    return _debt_read(debt, service)


@router.patch("/{debt_id}", response_model=DebtRead)
def update_debt(debt_id: str, data: DebtUpdate, db: Session = Depends(get_db)):
    service = DebtService(db)
    debt = service.update(debt_id, data)
    return _debt_read(debt, service)


@router.delete("/{debt_id}")
def delete_debt(debt_id: str, db: Session = Depends(get_db)):
    """Archive a debt. Financial data is never deleted."""
    service = DebtService(db)
    debt = service.archive(debt_id)
    return {"ok": True, "id": debt.id, "status": debt.status}


@router.post("/{debt_id}/payments", response_model=DebtPaymentRead, status_code=201)
@router.post("/{debt_id}/pay", response_model=DebtPaymentRead, status_code=201)
@router.post("/{debt_id}/payment", response_model=DebtPaymentRead, status_code=201)
def create_payment(debt_id: str, data: DebtPaymentCreate, db: Session = Depends(get_db)):
    service = DebtService(db)
    payment = service.create_payment(debt_id, data)
    return _payment_read(payment)


@router.get("/{debt_id}/payments", response_model=list[DebtPaymentRead])
def list_payments(
    debt_id: str,
    include_cancelled: bool = Query(True),
    db: Session = Depends(get_db),
):
    service = DebtService(db)
    payments = service.list_payments(debt_id, include_cancelled=include_cancelled)
    return [_payment_read(p) for p in payments]


@router.post("/payments", response_model=DebtPaymentRead, status_code=201)
@router.post("/payment", response_model=DebtPaymentRead, status_code=201)
@router.post("/pay", response_model=DebtPaymentRead, status_code=201)
def create_payment_flat(data: DebtPaymentCreate, db: Session = Depends(get_db)):
    if not data.debt_id:
        raise HTTPException(status_code=422, detail="debt_id ist erforderlich")
    service = DebtService(db)
    payment = service.create_payment(data.debt_id, data)
    return _payment_read(payment)


# ----- Plugin Class -------------------------------------------------------

class DebtsPlugin(FinancePlugin):
    name = "debts"
    version = "0.2.0"

    def register(self, app):
        engine = app.state.db_engine
        from app.db.database import Base
        Base.metadata.create_all(bind=engine, tables=[
            DebtsDebt.__table__,
            DebtsDebtPayment.__table__,
        ])
        app.include_router(router)


PLUGIN = DebtsPlugin()
