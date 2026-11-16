"""Builds the monthly workbook: Maintenance Detail, Expenses, Summary (Appendix A of the BRD)."""
import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Expense
from . import ledger

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def _style_header(ws, row: int, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _autosize(ws) -> None:
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(width + 2, 10), 45)


def month_label(month: str) -> str:
    return datetime.strptime(month, "%Y-%m").strftime("%B %Y")


def build_workbook(db: Session, month: str, building_name: str = "Building") -> Workbook:
    label = month_label(month)
    wb = Workbook()

    # Sheet 1: Maintenance Detail (flat-level summary of the ledger)
    ws = wb.active
    ws.title = f"{month} Maintenance Detail"
    ws["A1"] = f"{label} - Maintenance Detail"
    ws["A1"].font = Font(bold=True, size=14)
    headers = ["Flat No.", "Member Name", "Email", "Primary Phone", "Alternate Phone",
               "Monthly Allowance to Pay", "Allowance Paid", "Balance", "Status", "Date of Payment"]
    ws.append([])
    ws.append(headers)
    _style_header(ws, 3, len(headers))
    for r in ledger.month_status(db, month):
        f = r["flat"]
        ws.append([f.flat_number, f.member_name, f.email, f.phone, f.alt_phone, r["due"], r["paid"],
                   r["balance"], r["status"].upper(), r["last_paid_at"].strftime("%d-%b-%Y %H:%M") if r["last_paid_at"] else ""])
    _autosize(ws)
    ws.freeze_panes = "A4"

    # Sheet 2: Expenses (approved and pending are both listed; only approved counts in totals)
    we = wb.create_sheet(f"{month} Expenses")
    we["A1"] = f"{label} - Expenses"
    we["A1"].font = Font(bold=True, size=14)
    eh = ["Date", "Category", "Description", "Vendor", "Amount", "Status", "Receipt"]
    we.append([])
    we.append(eh)
    _style_header(we, 3, len(eh))
    for e in db.scalars(select(Expense).where(Expense.month == month).order_by(Expense.expense_date)):
        we.append([e.expense_date.strftime("%d-%b-%Y"), e.category, e.description, e.vendor, e.amount,
                   e.status.upper(), e.receipt_path or ""])
    _autosize(we)
    we.freeze_panes = "A4"

    # Sheet 3: Summary
    t = ledger.month_totals(db, month)
    wsu = wb.create_sheet(f"{month} Summary")
    wsu["A1"] = f"{building_name} - {label} Summary"
    wsu["A1"].font = Font(bold=True, size=14)
    lines = [
        ("Opening reserve", t["opening_reserve"]),
        ("Total maintenance due", t["total_due"]),
        ("Total approved collection", t["approved_collections"]),
        ("Outstanding dues", t["outstanding_dues"]),
        ("Flats paid / partial / pending", f'{t["paid_flats"]} / {t["partial_flats"]} / {t["pending_flats"]}'),
    ]
    r = 3
    for name, val in lines:
        wsu.cell(r, 1, name).font = Font(bold=True)
        wsu.cell(r, 2, val)
        r += 1
    r += 1
    wsu.cell(r, 1, "Expenses by category").font = Font(bold=True)
    r += 1
    for cat, amt in t["expenses_by_category"].items():
        wsu.cell(r, 1, cat)
        wsu.cell(r, 2, amt)
        r += 1
    wsu.cell(r, 1, "Total approved expenses").font = Font(bold=True)
    wsu.cell(r, 2, t["total_expenses"])
    r += 2
    wsu.cell(r, 1, "Net surplus / deficit").font = Font(bold=True)
    wsu.cell(r, 2, t["net_surplus_deficit"])
    r += 1
    wsu.cell(r, 1, "Closing reserve").font = Font(bold=True)
    wsu.cell(r, 2, t["closing_reserve"])
    _autosize(wsu)
    return wb


def save_workbook(db: Session, month: str, building_name: str = "Building") -> str:
    os.makedirs(settings.reports_dir, exist_ok=True)
    path = os.path.join(settings.reports_dir, f"{building_name}_Maintenance_{month}.xlsx")
    build_workbook(db, month, building_name).save(path)
    return path
