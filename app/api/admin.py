"""Admin REST API. Every route requires the X-Admin-Key header."""
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..config import current_month, settings
from ..database import get_db
from ..models import EXPENSE_CATEGORIES, AuditLog, DueOverride, Expense, Flat, Payment
from ..services import ledger, reminders
from ..services.excel_report import save_workbook
from ..services.parser import parse_payment_text


def require_admin(x_admin_key: str = Header(default="")):
    if not secrets.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(401, "Invalid admin key")


router = APIRouter(dependencies=[Depends(require_admin)])


def _payment_dict(p: Payment) -> dict:
    return {"id": p.id, "flat": p.flat.flat_number if p.flat else None, "month": p.month, "amount": p.amount,
            "source": p.source, "status": p.status, "utr": p.utr, "paid_at": p.paid_at, "flags": p.flags,
            "raw_text": p.raw_text, "evidence_path": p.evidence_path, "created_at": p.created_at}


def _wrap(fn):
    try:
        return fn()
    except ledger.DuplicateTransactionError as exc:
        raise HTTPException(409, str(exc))
    except ledger.LedgerError as exc:
        raise HTTPException(400, str(exc))


# ----- flats -----
@router.get("/flats")
def list_flats(db: Session = Depends(get_db)):
    return db.scalars(select(Flat).order_by(Flat.flat_number)).all()


@router.put("/flats/{flat_number}")
def update_flat(flat_number: str, body: schemas.FlatUpdate, db: Session = Depends(get_db)):
    flat = ledger.get_flat(db, flat_number)
    if not flat:
        raise HTTPException(404, "Flat not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(flat, k, v)
    ledger.log(db, "admin", "update", "flat", flat.id, body.model_dump(exclude_unset=True))
    db.commit()
    return flat


# ----- month config -----
@router.put("/months/{month}")
def set_month(month: str, body: schemas.MonthConfigIn, db: Session = Depends(get_db)):
    cfg = _wrap(lambda: ledger.ensure_month(db, month))
    cfg.amount_per_flat, cfg.opening_reserve, cfg.note = body.amount_per_flat, body.opening_reserve, body.note
    ledger.log(db, "admin", "set_month", "month", cfg.id, body.model_dump())
    db.commit()
    return cfg


@router.post("/months/{month}/overrides")
def set_override(month: str, body: schemas.OverrideIn, db: Session = Depends(get_db)):
    flat = ledger.get_flat(db, body.flat_number)
    if not flat:
        raise HTTPException(404, "Flat not found")
    ov = db.scalar(select(DueOverride).where(DueOverride.flat_id == flat.id, DueOverride.month == month))
    if ov:
        ov.amount, ov.reason = body.amount, body.reason
    else:
        db.add(DueOverride(flat_id=flat.id, month=month, amount=body.amount, reason=body.reason))
    ledger.log(db, "admin", "set_override", "flat", flat.id, {"month": month, "amount": body.amount})
    db.commit()
    return {"ok": True}


@router.post("/months/{month}/close")
def close_month(month: str, db: Session = Depends(get_db)):
    cfg = _wrap(lambda: ledger.ensure_month(db, month))
    cfg.closed = True
    ledger.log(db, "admin", "close_month", "month", cfg.id)
    db.commit()
    return {"month": month, "closed": True}


# ----- payments -----
@router.post("/payments/parse-text")
def parse_text(body: schemas.TextIn, db: Session = Depends(get_db)):
    """Try a chat message like '1000 paid, 205'. Creates a pending draft if it matches."""
    res = parse_payment_text(body.text)
    if not res.matched:
        return {"matched": False, "detail": "Not a payment message (ignored)"}
    if not res.ok:
        raise HTTPException(422, res.error)
    p = _wrap(lambda: ledger.create_draft_payment(db, flat_number=res.flat_number, amount=res.amount,
                                                  month=body.month or current_month(), source="text",
                                                  actor="admin", raw_text=body.text))
    db.commit()
    return {"matched": True, "payment": _payment_dict(p)}


@router.post("/payments")
def manual_payment(body: schemas.ManualPaymentIn, db: Session = Depends(get_db)):
    p = _wrap(lambda: ledger.create_draft_payment(db, flat_number=body.flat_number, amount=body.amount,
                                                  month=body.month, source="manual", actor="admin", utr=body.utr,
                                                  paid_at=body.paid_at, payer_name=body.payer_name))
    db.commit()
    return _payment_dict(p)


@router.get("/payments")
def list_payments(status: str | None = None, month: str | None = None, db: Session = Depends(get_db)):
    q = select(Payment).order_by(Payment.id.desc())
    if status:
        q = q.where(Payment.status == status)
    if month:
        q = q.where(Payment.month == month)
    return [_payment_dict(p) for p in db.scalars(q)]


@router.patch("/payments/{payment_id}")
def edit_payment(payment_id: int, body: schemas.PaymentEdit, db: Session = Depends(get_db)):
    p = _wrap(lambda: ledger.edit_payment(db, payment_id, "admin", **body.model_dump()))
    db.commit()
    return _payment_dict(p)


@router.post("/payments/{payment_id}/approve")
def approve(payment_id: int, body: schemas.ReviewIn = schemas.ReviewIn(), db: Session = Depends(get_db)):
    p = _wrap(lambda: ledger.approve_payment(db, payment_id, body.reviewer, body.override_duplicate))
    db.commit()
    return _payment_dict(p)


@router.post("/payments/{payment_id}/reject")
def reject(payment_id: int, body: schemas.ReviewIn = schemas.ReviewIn(), db: Session = Depends(get_db)):
    p = _wrap(lambda: ledger.reject_payment(db, payment_id, body.reviewer, body.reason))
    db.commit()
    return _payment_dict(p)


# ----- expenses -----
@router.get("/expense-categories")
def categories():
    return EXPENSE_CATEGORIES


@router.post("/expenses")
def add_expense(body: schemas.ExpenseIn, db: Session = Depends(get_db)):
    e = _wrap(lambda: ledger.create_expense(db, **body.model_dump()))
    db.commit()
    return e


@router.get("/expenses")
def list_expenses(month: str | None = None, db: Session = Depends(get_db)):
    q = select(Expense).order_by(Expense.expense_date.desc())
    if month:
        q = q.where(Expense.month == month)
    return db.scalars(q).all()


@router.post("/expenses/{expense_id}/approve")
def approve_expense(expense_id: int, db: Session = Depends(get_db)):
    e = _wrap(lambda: ledger.decide_expense(db, expense_id, "admin", True))
    db.commit()
    return e


@router.post("/expenses/{expense_id}/reject")
def reject_expense(expense_id: int, db: Session = Depends(get_db)):
    e = _wrap(lambda: ledger.decide_expense(db, expense_id, "admin", False))
    db.commit()
    return e


# ----- reports / reminders / audit -----
@router.get("/reports/{month}/summary")
def summary(month: str, db: Session = Depends(get_db)):
    return _wrap(lambda: ledger.month_totals(db, month))


@router.get("/reports/{month}/workbook")
def workbook(month: str, db: Session = Depends(get_db)):
    _wrap(lambda: ledger.check_month(month))
    path = save_workbook(db, month)
    db.commit()
    return FileResponse(path, filename=path.split("/")[-1],
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/reminders/{month}/preview")
def reminder_preview(month: str, db: Session = Depends(get_db)):
    return _wrap(lambda: reminders.build_reminders(db, month))


@router.post("/reminders/{month}/send")
def reminder_send(month: str, db: Session = Depends(get_db)):
    try:
        return {"sent": reminders.send_reminders(db, month)}
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))


@router.get("/audit")
def audit(limit: int = 100, db: Session = Depends(get_db)):
    return db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
