"""Ledger rules: drafts -> approval -> monthly status and reserve maths."""
import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import now_ist, settings
from ..models import AuditLog, DueOverride, Expense, Flat, MonthlyConfig, Payment

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class LedgerError(Exception):
    pass


class DuplicateTransactionError(LedgerError):
    pass


def check_month(month: str) -> str:
    if not MONTH_RE.match(month):
        raise LedgerError("Month must look like YYYY-MM")
    return month


def prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def log(db: Session, actor: str, action: str, entity: str, entity_id: Optional[int], details=None) -> None:
    db.add(AuditLog(actor=actor, action=action, entity=entity, entity_id=entity_id,
                    details=json.dumps(details, default=str) if details is not None else None))


# ---------- month configuration ----------
def ensure_month(db: Session, month: str) -> MonthlyConfig:
    check_month(month)
    cfg = db.scalar(select(MonthlyConfig).where(MonthlyConfig.month == month))
    if not cfg:
        cfg = MonthlyConfig(month=month, amount_per_flat=settings.default_monthly_amount)
        db.add(cfg)
        db.flush()
    return cfg


def get_flat(db: Session, flat_number: str) -> Optional[Flat]:
    return db.scalar(select(Flat).where(Flat.flat_number == flat_number))


def due_for_flat(db: Session, flat: Flat, month: str) -> float:
    override = db.scalar(select(DueOverride).where(DueOverride.flat_id == flat.id, DueOverride.month == month))
    return override.amount if override else ensure_month(db, month).amount_per_flat


# ---------- payments ----------
def create_draft_payment(db: Session, *, flat_number: Optional[str], amount: float, month: str, source: str,
                         actor: str = "system", raw_text: Optional[str] = None, utr: Optional[str] = None,
                         paid_at: Optional[datetime] = None, payer_name: Optional[str] = None,
                         evidence_path: Optional[str] = None, sender_phone: Optional[str] = None) -> Payment:
    check_month(month)
    flat = get_flat(db, flat_number) if flat_number else None
    flags = []
    if flat_number and not flat:
        raise LedgerError(f"Flat {flat_number} does not exist")
    if not flat:
        flags.append("flat_unknown")
    if utr and db.scalar(select(Payment).where(Payment.utr == utr, Payment.status != "rejected")):
        flags.append("duplicate_utr")
    elif flat and db.scalar(select(Payment).where(Payment.flat_id == flat.id, Payment.month == month,
                                                   Payment.amount == amount, Payment.status != "rejected")):
        flags.append("possible_duplicate")

    p = Payment(flat_id=flat.id if flat else None, month=month, amount=amount, source=source, utr=utr,
                paid_at=paid_at or now_ist(), payer_name=payer_name, raw_text=raw_text,
                evidence_path=evidence_path, sender_phone=sender_phone,
                flags=",".join(flags) or None)
    db.add(p)
    db.flush()
    log(db, actor, "create_draft", "payment", p.id, {"amount": amount, "flat": flat_number, "month": month,
                                                       "source": source, "flags": flags})
    return p


def _get_pending(db: Session, payment_id: int) -> Payment:
    p = db.get(Payment, payment_id)
    if not p:
        raise LedgerError("Payment not found")
    if p.status != "pending":
        raise LedgerError(f"Payment is already {p.status}")
    return p


def approve_payment(db: Session, payment_id: int, actor: str, override_duplicate: bool = False) -> Payment:
    p = _get_pending(db, payment_id)
    if p.flat_id is None:
        raise LedgerError("Assign a flat before approving")
    if ensure_month(db, p.month).closed:
        raise LedgerError("Month is closed; record a logged adjustment in an open month instead")
    if p.utr and not override_duplicate:
        clash = db.scalar(select(Payment).where(Payment.utr == p.utr, Payment.status == "approved",
                                                Payment.id != p.id))
        if clash:
            raise DuplicateTransactionError(f"UTR {p.utr} is already credited (payment #{clash.id})")
    p.status, p.reviewed_by, p.reviewed_at = "approved", actor, now_ist()
    log(db, actor, "approve", "payment", p.id, {"override_duplicate": override_duplicate})
    return p


def reject_payment(db: Session, payment_id: int, actor: str, reason: Optional[str] = None) -> Payment:
    p = _get_pending(db, payment_id)
    p.status, p.reviewed_by, p.reviewed_at, p.review_note = "rejected", actor, now_ist(), reason
    log(db, actor, "reject", "payment", p.id, {"reason": reason})
    return p


def edit_payment(db: Session, payment_id: int, actor: str, **fields) -> Payment:
    p = _get_pending(db, payment_id)
    changes = {}
    for key in ("amount", "month", "utr", "paid_at", "payer_name"):
        if fields.get(key) is not None:
            if key == "month":
                check_month(fields[key])
            changes[key] = (getattr(p, key), fields[key])
            setattr(p, key, fields[key])
    if fields.get("flat_number"):
        flat = get_flat(db, fields["flat_number"])
        if not flat:
            raise LedgerError(f"Flat {fields['flat_number']} does not exist")
        changes["flat"] = (p.flat_id, flat.id)
        p.flat_id = flat.id
        p.flags = ",".join(f for f in (p.flags or "").split(",") if f and f != "flat_unknown") or None
    log(db, actor, "edit", "payment", p.id, changes)
    return p


# ---------- expenses ----------
def create_expense(db: Session, *, month: str, expense_date, category: str, amount: float,
                   description: Optional[str] = None, vendor: Optional[str] = None,
                   receipt_path: Optional[str] = None, actor: str = "admin") -> Expense:
    check_month(month)
    if amount <= 0:
        raise LedgerError("Expense amount must be positive")
    e = Expense(month=month, expense_date=expense_date, category=category, amount=amount,
                description=description, vendor=vendor, receipt_path=receipt_path, created_by=actor)
    db.add(e)
    db.flush()
    log(db, actor, "create", "expense", e.id, {"amount": amount, "category": category})
    return e


def decide_expense(db: Session, expense_id: int, actor: str, approve: bool) -> Expense:
    e = db.get(Expense, expense_id)
    if not e:
        raise LedgerError("Expense not found")
    if e.status != "pending":
        raise LedgerError(f"Expense is already {e.status}")
    if ensure_month(db, e.month).closed:
        raise LedgerError("Month is closed")
    e.status = "approved" if approve else "rejected"
    e.approved_by = actor
    log(db, actor, e.status, "expense", e.id)
    return e


# ---------- monthly views ----------
def month_status(db: Session, month: str) -> list[dict]:
    """One row per active flat: due, paid (approved only), balance, status."""
    ensure_month(db, month)
    paid_rows = db.execute(
        select(Payment.flat_id, func.sum(Payment.amount), func.max(Payment.paid_at))
        .where(Payment.month == month, Payment.status == "approved").group_by(Payment.flat_id)
    ).all()
    paid = {fid: (total, last) for fid, total, last in paid_rows}
    rows = []
    for flat in db.scalars(select(Flat).where(Flat.active.is_(True)).order_by(Flat.flat_number)):
        due = due_for_flat(db, flat, month)
        total, last = paid.get(flat.id, (0, None))
        balance = due - total
        status = "paid" if balance <= 0 and total > 0 else ("partial" if total > 0 else "pending")
        rows.append({"flat": flat, "due": due, "paid": total, "balance": balance,
                     "status": status, "last_paid_at": last})
    return rows


def opening_reserve(db: Session, month: str, _depth: int = 0) -> float:
    cfg = ensure_month(db, month)
    if cfg.opening_reserve is not None:
        return cfg.opening_reserve
    prev = prev_month(month)
    has_prev = db.scalar(select(MonthlyConfig).where(MonthlyConfig.month == prev))
    if not has_prev or _depth > 36:
        return 0.0
    return month_totals(db, prev, _depth + 1)["closing_reserve"]


def month_totals(db: Session, month: str, _depth: int = 0) -> dict:
    rows = month_status(db, month)
    due_total = sum(r["due"] for r in rows)
    collected = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                          .where(Payment.month == month, Payment.status == "approved")) or 0
    outstanding = sum(max(r["balance"], 0) for r in rows)
    by_cat = defaultdict(float)
    for e in db.scalars(select(Expense).where(Expense.month == month, Expense.status == "approved")):
        by_cat[e.category] += e.amount
    expenses = sum(by_cat.values())
    opening = opening_reserve(db, month, _depth)
    return {
        "month": month,
        "opening_reserve": opening,
        "total_due": due_total,
        "approved_collections": collected,
        "outstanding_dues": outstanding,
        "expenses_by_category": dict(by_cat),
        "total_expenses": expenses,
        "net_surplus_deficit": collected - expenses,
        # Closing Reserve = Opening Reserve + Approved Collections (+ other income) - Approved Expenses
        "closing_reserve": opening + collected - expenses,
        "paid_flats": sum(r["status"] == "paid" for r in rows),
        "partial_flats": sum(r["status"] == "partial" for r in rows),
        "pending_flats": sum(r["status"] == "pending" for r in rows),
    }
