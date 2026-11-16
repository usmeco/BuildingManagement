"""Deterministic parser for payment messages.

Phase 1 rule (from the BRD): only ONE message pattern counts as a payment:

    "1000 paid, 205"      ->  amount=1000, flat=205

Anything else (questions, chatter, other wordings) is ignored on purpose, to
avoid false positives. Add new patterns here later, each with tests.
"""
import re
from dataclasses import dataclass
from typing import Optional

PAYMENT_RE = re.compile(r"^\s*(\d{3,6})\s+paid\s*,\s*(\d{3})\s*$", re.IGNORECASE)


def valid_flat_numbers() -> list[str]:
    """001-005, 101-105, ... 501-505 (30 flats)."""
    return [f"{floor}{unit:02d}" for floor in range(0, 6) for unit in range(1, 6)]


VALID_FLATS = set(valid_flat_numbers())


def is_valid_flat(flat_number: str) -> bool:
    return flat_number in VALID_FLATS


def floor_of(flat_number: str) -> int:
    return int(flat_number[0])


@dataclass
class ParseResult:
    matched: bool  # message looked like a payment message
    amount: Optional[int] = None
    flat_number: Optional[str] = None
    error: Optional[str] = None  # set when matched but unusable (e.g. unknown flat)

    @property
    def ok(self) -> bool:
        return self.matched and self.error is None


def parse_payment_text(text: str) -> ParseResult:
    m = PAYMENT_RE.match(text or "")
    if not m:
        return ParseResult(matched=False)
    amount, flat = int(m.group(1)), m.group(2)
    if not is_valid_flat(flat):
        return ParseResult(True, amount, flat, error=f"Unknown flat number {flat}")
    if amount <= 0:
        return ParseResult(True, amount, flat, error="Amount must be positive")
    return ParseResult(True, amount, flat)
