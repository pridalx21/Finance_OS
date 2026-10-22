"""Investments Plugin — Aktien, ETFs, Krypto.

Ergänzt Investment-Tracking ohne Änderungen am Kern.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Session, relationship, joinedload

from app.db.database import Base, get_db
from app.plugins import FinancePlugin
from app.models.account import Account


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ----- Datenmodell -----

class Investment(Base):
    """Ein Wertpapier / Asset (z. B. AAPL, VT, BTC)."""
    __tablename__ = "plugin_investments_investments"

    id = Column(String, primary_key=True)
    symbol = Column(String(20), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False)
    type = Column(String(20), nullable=False)  # "stock", "etf", "crypto"
    currency = Column(String(3), nullable=False, default="CHF")
    isin = Column(String(12), nullable=True, unique=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class Position(Base):
    """Ein Bestand in einem Konto."""
    __tablename__ = "plugin_investments_positions"

    id = Column(String, primary_key=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)
    investment_id = Column(String, ForeignKey("plugin_investments_investments.id"), nullable=False)
    quantity = Column(Numeric(precision=18, scale=8), nullable=False, default=0)
    avg_price_cents = Column(Integer, nullable=False, default=0)  # Durchschnittskaufpreis in Cent
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    account = relationship("Account")
    investment = relationship("Investment")

    __table_args__ = (
        UniqueConstraint("account_id", "investment_id", name="uq_position"),
    )


class Trade(Base):
    """Ein Trade (Kauf/Verkauf)."""
    __tablename__ = "plugin_investments_trades"

    id = Column(String, primary_key=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)
    investment_id = Column(String, ForeignKey("plugin_investments_investments.id"), nullable=False)
    type = Column(String(10), nullable=False)  # "BUY", "SELL"
    quantity = Column(Numeric(precision=18, scale=8), nullable=False)
    price_cents = Column(Integer, nullable=False)  # Stückpreis in Cent
    fee_cents = Column(Integer, nullable=False, default=0)
    date = Column(DateTime, nullable=False, default=_utcnow)
    note = Column(String(500), nullable=True)

    account = relationship("Account")
    investment = relationship("Investment")


# ----- Schemas -----

class InvestmentCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(stock|etf|crypto)$")
    currency: str = Field(default="CHF", max_length=3)
    isin: Optional[str] = Field(None, max_length=12)


class InvestmentRead(BaseModel):
    id: str
    symbol: str
    name: str
    type: str
    currency: str
    isin: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TradeCreate(BaseModel):
    account_id: str
    investment_id: str
    type: str = Field(..., pattern="^(BUY|SELL)$")
    quantity: Decimal = Field(..., gt=0)
    price_cents: int = Field(..., gt=0)
    fee_cents: int = Field(default=0, ge=0)
    date: Optional[datetime] = None
    note: Optional[str] = None


class TradeRead(BaseModel):
    id: str
    account_id: str
    investment_id: str
    type: str
    quantity: Decimal
    price_cents: int
    fee_cents: int
    date: datetime
    note: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class PositionRead(BaseModel):
    investment_id: str
    symbol: str
    name: str
    quantity: Decimal
    avg_price_cents: int
    current_price_cents: Optional[int] = None
    market_value_cents: Optional[int] = None
    pnl_cents: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# ----- Router -----

router = APIRouter(prefix="/api/investments", tags=["investments"])


@router.post("", response_model=InvestmentRead, status_code=201)
def create_investment(data: InvestmentCreate, db: Session = Depends(get_db)):
    existing = db.query(Investment).filter(Investment.symbol == data.symbol.upper()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Investment mit diesem Symbol existiert bereits")

    inv = Investment(
        id=str(uuid4()),
        symbol=data.symbol.upper(),
        name=data.name,
        type=data.type,
        currency=data.currency,
        isin=data.isin,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


@router.get("", response_model=list[InvestmentRead])
def list_investments(db: Session = Depends(get_db)):
    return db.query(Investment).order_by(Investment.symbol).all()


@router.post("/trades", response_model=TradeRead, status_code=201)
def create_trade(data: TradeCreate, db: Session = Depends(get_db)):
    # Validate
    account = db.query(Account).filter(Account.id == data.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")

    inv = db.query(Investment).filter(Investment.id == data.investment_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment nicht gefunden")

    # Load or prepare the position before writing anything.
    pos = db.query(Position).filter(
        Position.account_id == data.account_id,
        Position.investment_id == data.investment_id,
    ).first()
    is_new_position = pos is None
    if is_new_position:
        pos = Position(
            id=str(uuid4()),
            account_id=data.account_id,
            investment_id=data.investment_id,
            quantity=Decimal("0"),
            avg_price_cents=0,
        )

    if data.type == "SELL":
        if pos.quantity < data.quantity:
            raise HTTPException(status_code=400, detail="Nicht genügend Bestand")
        pos.quantity -= data.quantity
    else:  # BUY — weighted average price, rounded half up to whole cents
        total_cost = (
            pos.quantity * Decimal(pos.avg_price_cents)
            + data.quantity * Decimal(data.price_cents)
        )
        new_quantity = pos.quantity + data.quantity
        pos.quantity = new_quantity
        pos.avg_price_cents = int(
            (total_cost / new_quantity).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

    pos.updated_at = _utcnow()

    trade = Trade(
        id=str(uuid4()),
        account_id=data.account_id,
        investment_id=data.investment_id,
        type=data.type,
        quantity=data.quantity,
        price_cents=data.price_cents,
        fee_cents=data.fee_cents,
        date=data.date or _utcnow(),
        note=data.note,
    )

    if is_new_position:
        db.add(pos)
    db.add(trade)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(trade)

    return trade


@router.get("/positions", response_model=list[PositionRead])
def list_positions(account_id: str = Query(...), db: Session = Depends(get_db)):
    try:
        positions = db.query(Position).options(
            joinedload(Position.investment)
        ).filter(
            Position.account_id == account_id,
            Position.quantity > 0,
        ).all()
        
        result = []
        for p in positions:
            inv = p.investment
            if inv is None:
                inv = db.query(Investment).filter(Investment.id == p.investment_id).first()
            if inv is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Investment {p.investment_id} nicht gefunden"
                )
            result.append(PositionRead(
                investment_id=p.investment_id,
                symbol=inv.symbol,
                name=inv.name,
                quantity=p.quantity,
                avg_price_cents=p.avg_price_cents,
            ))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/{investment_id}", response_model=InvestmentRead)
def get_investment(investment_id: str, db: Session = Depends(get_db)):
    inv = db.query(Investment).filter(Investment.id == investment_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment nicht gefunden")
    return inv


# ----- Plugin Class -----

class InvestmentsPlugin(FinancePlugin):
    name = "investments"
    version = "0.1.0"

    def register(self, app):
        engine = app.state.db_engine
        from app.db.database import Base
        Base.metadata.create_all(bind=engine, tables=[
            Investment.__table__,
            Position.__table__,
            Trade.__table__,
        ])
        app.include_router(router)


PLUGIN = InvestmentsPlugin()