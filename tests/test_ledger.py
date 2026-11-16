import datetime

import pytest

from app.models import DueOverride, Flat
from app.services import ledger


def pay(db, flat="205", amount=1000, month="2026-11", **kw):
    return ledger.create_draft_payment(db, flat_number=flat, amount=amount, month=month, source="manual", **kw)


def status_of(db, flat, month="2026-11"):
    return next(r for r in ledger.month_status(db, month) if r["flat"].flat_number == flat)


def test_draft_does_not_count_until_approved(db):
    p = pay(db)
    assert status_of(db, "205")["paid"] == 0
    ledger.approve_payment(db, p.id, "treasurer")
    assert status_of(db, "205")["status"] == "paid"


def test_partial_and_instalments(db):
    ledger.approve_payment(db, pay(db, amount=400).id, "t")
    assert status_of(db, "205")["status"] == "partial" and status_of(db, "205")["balance"] == 600
    ledger.approve_payment(db, pay(db, amount=600).id, "t")
    assert status_of(db, "205")["status"] == "paid"


def test_double_month_via_config_and_override(db):
    ledger.ensure_month(db, "2026-12").amount_per_flat = 2000
    db.add(DueOverride(flat_id=ledger.get_flat(db, "101").id, month="2026-12", amount=3000))
    db.flush()
    assert status_of(db, "205", "2026-12")["due"] == 2000
    assert status_of(db, "101", "2026-12")["due"] == 3000


def test_duplicate_utr_blocked_without_override(db):
    a = pay(db, utr="UTR123")
    ledger.approve_payment(db, a.id, "t")
    b = pay(db, flat="305", utr="UTR123")
    assert "duplicate_utr" in b.flags
    with pytest.raises(ledger.DuplicateTransactionError):
        ledger.approve_payment(db, b.id, "t")
    ledger.approve_payment(db, b.id, "t", override_duplicate=True)


def test_possible_duplicate_flag_without_utr(db):
    pay(db)
    assert "possible_duplicate" in pay(db).flags


def test_unknown_flat_rejected_and_missing_flat_needs_assignment(db):
    with pytest.raises(ledger.LedgerError):
        pay(db, flat="999")
    p = ledger.create_draft_payment(db, flat_number=None, amount=1000, month="2026-11", source="screenshot")
    assert "flat_unknown" in p.flags
    with pytest.raises(ledger.LedgerError):
        ledger.approve_payment(db, p.id, "t")
    ledger.edit_payment(db, p.id, "t", flat_number="102")
    ledger.approve_payment(db, p.id, "t")


def test_cannot_decide_twice_and_audit_written(db):
    p = pay(db)
    ledger.reject_payment(db, p.id, "t", "wrong flat")
    with pytest.raises(ledger.LedgerError):
        ledger.approve_payment(db, p.id, "t")
    from app.models import AuditLog
    assert db.query(AuditLog).filter(AuditLog.entity == "payment").count() >= 2


def test_closed_month_blocks_approval(db):
    p = pay(db)
    ledger.ensure_month(db, "2026-11").closed = True
    with pytest.raises(ledger.LedgerError):
        ledger.approve_payment(db, p.id, "t")


def test_reserve_formula_and_rollover(db):
    cfg = ledger.ensure_month(db, "2026-11")
    cfg.opening_reserve = 5000
    for flat in ("001", "002", "003"):
        ledger.approve_payment(db, pay(db, flat=flat).id, "t")
    e = ledger.create_expense(db, month="2026-11", expense_date=datetime.date(2026, 11, 5),
                              category="Lift maintenance", amount=1500)
    pending = ledger.create_expense(db, month="2026-11", expense_date=datetime.date(2026, 11, 6),
                                    category="Miscellaneous", amount=999)
    ledger.decide_expense(db, e.id, "t", True)
    t = ledger.month_totals(db, "2026-11")
    assert t["total_due"] == 30000 and t["approved_collections"] == 3000
    assert t["outstanding_dues"] == 27000          # expected is not received
    assert t["total_expenses"] == 1500             # pending expense excluded
    assert t["closing_reserve"] == 5000 + 3000 - 1500
    assert ledger.opening_reserve(db, "2026-12") == 6500   # rolls from previous month
    assert pending.status == "pending"
