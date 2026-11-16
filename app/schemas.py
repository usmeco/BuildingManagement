from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class FlatUpdate(BaseModel):
    member_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    alt_phone: Optional[str] = None
    reminders_opt_in: Optional[bool] = None
    active: Optional[bool] = None


class MonthConfigIn(BaseModel):
    amount_per_flat: float = Field(gt=0)
    opening_reserve: Optional[float] = None
    note: Optional[str] = None


class OverrideIn(BaseModel):
    flat_number: str
    amount: float = Field(ge=0)
    reason: Optional[str] = None


class ManualPaymentIn(BaseModel):
    flat_number: str
    amount: float = Field(gt=0)
    month: str
    utr: Optional[str] = None
    paid_at: Optional[datetime] = None
    payer_name: Optional[str] = None


class TextIn(BaseModel):
    text: str
    month: Optional[str] = None


class PaymentEdit(BaseModel):
    flat_number: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    month: Optional[str] = None
    utr: Optional[str] = None
    paid_at: Optional[datetime] = None
    payer_name: Optional[str] = None


class ReviewIn(BaseModel):
    reviewer: str = "admin"
    override_duplicate: bool = False
    reason: Optional[str] = None


class ExpenseIn(BaseModel):
    month: str
    expense_date: date
    category: str
    amount: float = Field(gt=0)
    description: Optional[str] = None
    vendor: Optional[str] = None
