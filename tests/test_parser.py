import pytest

from app.services.parser import is_valid_flat, parse_payment_text, valid_flat_numbers


def test_thirty_valid_flats():
    flats = valid_flat_numbers()
    assert len(flats) == 30
    assert flats[0] == "001" and flats[4] == "005" and flats[-1] == "505"


@pytest.mark.parametrize("text,amount,flat", [
    ("1000 paid, 205", 1000, "205"),
    ("  1000 PAID,205 ", 1000, "205"),
    ("2000 paid, 001", 2000, "001"),
    ("3000 Paid , 505", 3000, "505"),
])
def test_valid_messages(text, amount, flat):
    r = parse_payment_text(text)
    assert r.ok and r.amount == amount and r.flat_number == flat


@pytest.mark.parametrize("text", [
    "did 205 pay 1000?",
    "November maintenance done for 205",
    "Paid 1000 from 205 flat",       # other wording is NOT supported in phase 1
    "1000 paid",
    "1000 paid, 205 and 305",
    "anyone paid 1000 paid, 205?",
    "",
])
def test_false_positives_are_ignored(text):
    assert not parse_payment_text(text).matched


@pytest.mark.parametrize("text", ["1000 paid, 206", "1000 paid, 601", "1000 paid, 200", "1000 paid, 000"])
def test_unknown_flat_is_flagged_not_guessed(text):
    r = parse_payment_text(text)
    assert r.matched and not r.ok and "Unknown flat" in r.error


def test_is_valid_flat():
    assert is_valid_flat("305") and not is_valid_flat("306")
