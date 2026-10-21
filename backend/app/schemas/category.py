"""Category schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(INCOME|EXPENSE)$")
    parent_id: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = None
    icon: Optional[str] = None
    archived_at: Optional[datetime] = None


class CategoryRead(BaseModel):
    id: str
    name: str
    type: str
    parent_id: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    created_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
