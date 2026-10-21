"""Account model."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.orm import relationship

from app.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    currency = Column(String, nullable=False, default="CHF")
    initial_balance_cents = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    archived_at = Column(DateTime, nullable=True)

    transactions = relationship("Transaction", back_populates="account", cascade="all, delete-orphan")
