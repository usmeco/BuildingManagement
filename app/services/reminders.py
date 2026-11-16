"""Reminder rules: only opted-in flats with a balance; individual dues are never posted to the group."""
from sqlalchemy.orm import Session

from ..config import settings
from . import ledger, whatsapp
from .excel_report import month_label


def build_reminders(db: Session, month: str) -> dict:
    to_send, skipped = [], []
    for r in ledger.month_status(db, month):
        flat = r["flat"]
        if r["balance"] <= 0:
            continue  # paid flats never get reminders
        if not flat.reminders_opt_in or not flat.phone:
            skipped.append({"flat_number": flat.flat_number,
                            "reason": "no opt-in" if not flat.reminders_opt_in else "no phone"})
            continue
        to_send.append({
            "flat_number": flat.flat_number,
            "member_name": flat.member_name,
            "phone": flat.phone,
            "outstanding": r["balance"],
            "message": f"Hello {flat.member_name or 'resident'}, maintenance for {month_label(month)} "
                       f"(flat {flat.flat_number}) has Rs {r['balance']:.0f} outstanding. Please pay and "
                       f"send '{r['due']:.0f} paid, {flat.flat_number}'. Ignore if already paid.",
        })
    return {"month": month, "to_send": to_send, "skipped": skipped}


def send_reminders(db: Session, month: str) -> int:
    if not settings.reminders_enabled:
        raise RuntimeError("REMINDERS_ENABLED is false")
    plan = build_reminders(db, month)
    for item in plan["to_send"]:
        whatsapp.send_template(item["phone"], settings.reminder_template_name,
                               [item["member_name"] or "resident", month_label(month),
                                item["flat_number"], f"{item['outstanding']:.0f}"])
        ledger.log(db, "system", "reminder_sent", "flat", None, {"flat": item["flat_number"], "month": month})
    db.commit()
    return len(plan["to_send"])
