"""Create the 30 flats (001-005, 101-105 ... 501-505). Safe to re-run.

    python -m scripts.seed_flats
    python -m scripts.seed_flats residents.csv     # optional: flat_number,member_name,email,phone,alt_phone
"""
import csv
import sys

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Flat
from app.services.parser import floor_of, valid_flat_numbers


def seed(db, csv_path: str | None = None) -> int:
    created = 0
    for number in valid_flat_numbers():
        if not db.scalar(select(Flat).where(Flat.flat_number == number)):
            db.add(Flat(flat_number=number, floor=floor_of(number)))
            created += 1
    db.flush()
    if csv_path:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                flat = db.scalar(select(Flat).where(Flat.flat_number == row["flat_number"].strip().zfill(3)))
                if flat:
                    flat.member_name = row.get("member_name") or flat.member_name
                    flat.email = row.get("email") or flat.email
                    flat.phone = row.get("phone") or flat.phone
                    flat.alt_phone = row.get("alt_phone") or flat.alt_phone
    db.commit()
    return created


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        n = seed(session, sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Created {n} flats")
