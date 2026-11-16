from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import now_ist
from .database import Base

Money = Numeric(12, 2, asdecimal=False)


class Flat(Base):
    __tablename__ = "flats"

    id: Mapped[int] = mapped_column(primary_key=True)
    flat_number: Mapped[str] = mapped_column(String(3), unique=True, index=True)  # 001..005, 101..105 ... 501..505
    floor: Mapped[int] = mapped_column(Integer)  # 0 = ground floor
    member_name: Mapped[Optional[str]] = mapped_column(String(120))
    email: Mapped[Optional[str]] = mapped_column(String(160))
    phone: Mapped[Optional[str]] = mapped_column(String(20))  # primary, country code, no +
    alt_phone: Mapped[Optional[str]] = mapped_column(String(20))
    reminders_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)  # consent before any reminder
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MonthlyConfig(Base):
    """One row per month: the standard amount per flat (change it for 2x/3x months)."""

    __tablename__ = "monthly_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), unique=True, index=True)  # YYYY-MM
    amount_per_flat: Mapped[float] = mapped_column(Money)
    opening_reserve: Mapped[Optional[float]] = mapped_column(Money, nullable=True)  # None = roll from previous month
    note: Mapped[Optional[str]] = mapped_column(String(255))
    closed: Mapped[bool] = mapped_column(Boolean, default=False)


class DueOverride(Base):
    """Different amount for one flat in one month."""

    __tablename__ = "due_overrides"
    __table_args__ = (UniqueConstraint("flat_id", "month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    flat_id: Mapped[int] = mapped_column(ForeignKey("flats.id"))
    month: Mapped[str] = mapped_column(String(7))
    amount: Mapped[float] = mapped_column(Money)
    reason: Mapped[Optional[str]] = mapped_column(String(255))


class Payment(Base):
    """Transaction-level ledger: the source of truth. Monthly sheets are generated from this."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    flat_id: Mapped[Optional[int]] = mapped_column(ForeignKey("flats.id"), nullable=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    amount: Mapped[float] = mapped_column(Money)
    source: Mapped[str] = mapped_column(String(20))  # text | screenshot | manual
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # pending | approved | rejected
    utr: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    payer_name: Mapped[Optional[str]] = mapped_column(String(120))
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    evidence_path: Mapped[Optional[str]] = mapped_column(String(255))
    sender_phone: Mapped[Optional[str]] = mapped_column(String(20))
    flags: Mapped[Optional[str]] = mapped_column(String(255))  # e.g. possible_duplicate,flat_unknown
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_ist)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(60))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    review_note: Mapped[Optional[str]] = mapped_column(String(255))

    flat: Mapped[Optional[Flat]] = relationship()


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    expense_date: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(60))  # see EXPENSE_CATEGORIES
    description: Mapped[Optional[str]] = mapped_column(String(255))
    vendor: Mapped[Optional[str]] = mapped_column(String(120))
    amount: Mapped[float] = mapped_column(Money)
    receipt_path: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | approved | rejected
    created_by: Mapped[Optional[str]] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_ist)
    approved_by: Mapped[Optional[str]] = mapped_column(String(60))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now_ist)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    details: Mapped[Optional[str]] = mapped_column(Text)


EXPENSE_CATEGORIES = [
    "Building guard salary",
    "Main gate guard salary",
    "Lane sweeper salary",
    "Water tank cleaning",
    "Lift maintenance",
    "Miscellaneous",
]
