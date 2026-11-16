"""Meta WhatsApp Cloud API webhook (bot number, one-to-one chats)."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..services import whatsapp

router = APIRouter()


@router.get("/webhook/whatsapp")
def verify(hub_mode: str = Query(alias="hub.mode", default=""),
           hub_token: str = Query(alias="hub.verify_token", default=""),
           hub_challenge: str = Query(alias="hub.challenge", default="")):
    if hub_mode == "subscribe" and settings.whatsapp_verify_token and hub_token == settings.whatsapp_verify_token:
        return Response(hub_challenge, media_type="text/plain")
    raise HTTPException(403, "Verification failed")


@router.post("/webhook/whatsapp")
async def receive(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not whatsapp.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(403, "Bad signature")
    payload = json.loads(raw or b"{}")
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                try:
                    whatsapp.handle_message(db, msg)
                except Exception:  # never let one bad message make Meta retry forever
                    db.rollback()
                    whatsapp.log.exception("Failed handling message")
    return {"status": "ok"}
