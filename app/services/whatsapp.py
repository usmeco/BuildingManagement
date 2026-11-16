"""WhatsApp Cloud API helpers (one-to-one bot chat; NOT group reading)."""
import hashlib
import hmac
import logging
import os
import re
import uuid

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import current_month, settings
from ..models import Flat
from . import ledger
from .parser import is_valid_flat, parse_payment_text
from .screenshot import ScreenshotError, extract_upi_details

log = logging.getLogger("buildingmate.whatsapp")
GRAPH = "https://graph.facebook.com/v20.0"


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    """Check Meta's X-Hub-Signature-256. If no app secret is configured, skip (dev only)."""
    if not settings.whatsapp_app_secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.whatsapp_token}"}


def send_text(to: str, body: str) -> None:
    if not settings.whatsapp_token:
        log.info("[dry-run] to %s: %s", to, body)
        return
    httpx.post(f"{GRAPH}/{settings.whatsapp_phone_number_id}/messages", headers=_headers(), timeout=20,
               json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}})


def send_template(to: str, template: str, params: list[str], lang: str = "en") -> None:
    """Reminders outside the 24h window must use a Meta-approved template."""
    if not settings.whatsapp_token:
        log.info("[dry-run] template %s to %s: %s", template, to, params)
        return
    httpx.post(f"{GRAPH}/{settings.whatsapp_phone_number_id}/messages", headers=_headers(), timeout=20, json={
        "messaging_product": "whatsapp", "to": to, "type": "template",
        "template": {"name": template, "language": {"code": lang},
                     "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]}})


def download_media(media_id: str) -> tuple[bytes, str]:
    meta = httpx.get(f"{GRAPH}/{media_id}", headers=_headers(), timeout=20).json()
    resp = httpx.get(meta["url"], headers=_headers(), timeout=30)
    return resp.content, meta.get("mime_type", "image/jpeg")


def flat_for_phone(db: Session, phone: str) -> Flat | None:
    return db.scalar(select(Flat).where(or_(Flat.phone == phone, Flat.alt_phone == phone)))


def sender_allowed(db: Session, phone: str) -> bool:
    return phone in settings.admin_phones or flat_for_phone(db, phone) is not None


def handle_message(db: Session, msg: dict) -> None:
    """Process one inbound WhatsApp message and reply. Unrecognised chatter is ignored silently."""
    sender = msg.get("from", "")
    if not sender_allowed(db, sender):
        log.info("Ignoring message from unregistered number")
        return
    month = current_month()

    if msg.get("type") == "text":
        text = msg["text"]["body"]
        result = parse_payment_text(text)
        if not result.matched:
            return
        if not result.ok:
            send_text(sender, f"Could not record that: {result.error}. Format: 1000 paid, 205")
            return
        p = ledger.create_draft_payment(db, flat_number=result.flat_number, amount=result.amount, month=month,
                                        source="text", actor=f"wa:{sender}", raw_text=text, sender_phone=sender)
        db.commit()
        warn = " (possible duplicate, admin will check)" if p.flags else ""
        send_text(sender, f"Recorded draft #{p.id}: Rs {result.amount} from flat {result.flat_number} "
                          f"for {month}. Pending admin approval.{warn}")

    elif msg.get("type") == "image":
        caption = (msg["image"].get("caption") or "").strip()
        flat_number = caption if is_valid_flat(caption) else None
        if not flat_number:
            f = flat_for_phone(db, sender)
            flat_number = f.flat_number if f else None
        try:
            data, mime = download_media(msg["image"]["id"])
            details = extract_upi_details(data, mime)
        except ScreenshotError as exc:
            send_text(sender, f"Could not read the screenshot: {exc}. Please send '1000 paid, 205' instead.")
            return
        os.makedirs(settings.evidence_dir, exist_ok=True)
        ext = "png" if "png" in mime else "jpg"
        path = os.path.join(settings.evidence_dir, f"{uuid.uuid4().hex}.{ext}")
        with open(path, "wb") as fh:
            fh.write(data)
        p = ledger.create_draft_payment(db, flat_number=flat_number, amount=details["amount"], month=month,
                                        source="screenshot", actor=f"wa:{sender}", utr=details["utr"],
                                        paid_at=details["paid_at"], payer_name=details["payer_name"],
                                        evidence_path=path, sender_phone=sender)
        db.commit()
        who = f"flat {flat_number}" if flat_number else "an unknown flat (admin will assign)"
        send_text(sender, f"Recorded draft #{p.id}: Rs {details['amount']:.0f} from {who}. Pending admin approval.")
