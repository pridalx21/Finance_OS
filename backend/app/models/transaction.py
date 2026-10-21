"""Transaction model."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=_uuid)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)
    type = Column(String, nullable=False)  # INCOME or EXPENSE
    amount_cents = Column(Integer, nullable=False)
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    description = Column(String, nullable=True)
    date = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    idempotency_key = Column(String, unique=True, nullable=True)
    reversed_by = Column(String, nullable=True)

    account = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
