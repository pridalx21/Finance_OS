"""Transaction schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class TransactionCreate(BaseModel):
    account_id: str
    type: str = Field(..., pattern="^(INCOME|EXPENSE)$")
    amount_cents: int = Field(..., gt=0)
    category_id: Optional[str] = None
    description: Optional[str] = None
    date: Optional[datetime] = None
    idempotency_key: Optional[str] = None


class TransactionRead(BaseModel):
    id: str
    account_id: str
    type: str
    amount_cents: int
    category_id: Optional[str] = None
    description: Optional[str] = None
    date: datetime
    created_at: datetime
    idempotency_key: Optional[str] = None
    reversed_by: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TransactionList(BaseModel):
    items: list[TransactionRead]
    total: int
    page: int
    page_size: int
