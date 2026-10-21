"""Account schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    currency: str = Field(default="CHF", max_length=3)
    initial_balance_cents: int = Field(default=0, ge=0)


class AccountRead(BaseModel):
    id: str
    name: str
    currency: str
    initial_balance_cents: int
    created_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AccountBalance(BaseModel):
    account_id: str
    account_name: str
    currency: str
    initial_balance_cents: int
    total_income_cents: int
    total_expense_cents: int
    balance_cents: int
