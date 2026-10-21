"""Category model."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Category(Base):
    __tablename__ = "categories"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # INCOME or EXPENSE
    parent_id = Column(String, ForeignKey("categories.id"), nullable=True)
    color = Column(String, nullable=True)
    icon = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    archived_at = Column(DateTime, nullable=True)

    parent = relationship("Category", remote_side=[id], backref="children")
    transactions = relationship("Transaction", back_populates="category")
