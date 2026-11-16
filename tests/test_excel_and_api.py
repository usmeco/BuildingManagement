import datetime

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.services import ledger
from app.services.excel_report import build_workbook


def test_workbook_has_agreed_sheets_and_30_rows(db):
    ledger.approve_payment(db, ledger.create_draft_payment(db, flat_number="205", amount=1000, month="2026-11",
                                                           source="text").id, "t")
    ledger.create_expense(db, month="2026-11", expense_date=datetime.date(2026, 11, 3),
                          category="Water tank cleaning", amount=800)
    wb = build_workbook(db, "2026-11")
    assert wb.sheetnames == ["2026-11 Maintenance Detail", "2026-11 Expenses", "2026-11 Summary"]
    detail = wb["2026-11 Maintenance Detail"]
    rows = [r for r in detail.iter_rows(min_row=4, values_only=True) if r[0]]
    assert len(rows) == 30
    row_205 = next(r for r in rows if r[0] == "205")
    assert row_205[5] == 1000 and row_205[6] == 1000 and row_205[8] == "PAID"


def test_api_end_to_end(tmp_path, monkeypatch):
    from app.main import app
    from app.database import SessionLocal
    from scripts.seed_flats import seed

    with SessionLocal() as s:
        seed(s)
    c = TestClient(app)
    h = {"X-Admin-Key": "test-key"}

    assert c.get("/api/flats").status_code == 401
    assert len(c.get("/api/flats", headers=h).json()) == 30

    r = c.post("/api/payments/parse-text", headers=h, json={"text": "1000 paid, 205", "month": "2026-11"})
    pid = r.json()["payment"]["id"]
    assert c.post("/api/payments/parse-text", headers=h, json={"text": "did 205 pay?"}).json()["matched"] is False
    assert c.post(f"/api/payments/{pid}/approve", headers=h).json()["status"] == "approved"
    assert c.get("/api/reports/2026-11/summary", headers=h).json()["approved_collections"] == 1000
    wb = c.get("/api/reports/2026-11/workbook", headers=h)
    assert wb.status_code == 200 and wb.content[:2] == b"PK"


def test_whatsapp_text_flow(db, monkeypatch):
    from app.config import settings
    from app.services import whatsapp
    sent = []
    monkeypatch.setattr(whatsapp, "send_text", lambda to, body: sent.append((to, body)))
    monkeypatch.setattr(settings, "admin_phones", ["919999999999"])
    whatsapp.handle_message(db, {"from": "919999999999", "type": "text", "text": {"body": "1000 paid, 205"}})
    whatsapp.handle_message(db, {"from": "919999999999", "type": "text", "text": {"body": "hello everyone"}})
    whatsapp.handle_message(db, {"from": "911111111111", "type": "text", "text": {"body": "1000 paid, 205"}})
    assert len(sent) == 1 and "flat 205" in sent[0][1]


def test_screenshot_normalise():
    import pytest
    from app.services.screenshot import ScreenshotError, normalise, parse_model_json
    ok = normalise(parse_model_json('```json\n{"amount": 1000, "utr": "4 1234 5678", "paid_at": "2026-11-03 18:20", '
                                    '"status": "success", "is_upi_screenshot": true}\n```'))
    assert ok["amount"] == 1000 and ok["utr"] == "412345678"
    with pytest.raises(ScreenshotError):
        normalise({"amount": 1000, "status": "failed"})


def test_reminders_exclude_paid_and_non_opted_in(db):
    from app.services import reminders
    for n in ("101", "102"):
        f = ledger.get_flat(db, n)
        f.reminders_opt_in, f.phone, f.member_name = True, "9198" + n, "Test"
    ledger.approve_payment(db, ledger.create_draft_payment(db, flat_number="101", amount=1000, month="2026-11",
                                                           source="text").id, "t")
    plan = reminders.build_reminders(db, "2026-11")
    assert [r["flat_number"] for r in plan["to_send"]] == ["102"]
    assert len(plan["skipped"]) == 28   # 30 flats - 101 (paid) - 102 (reminded) = 28 without opt-in
