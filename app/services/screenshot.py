"""Extract payment details from a UPI screenshot using the Claude API (vision).

The result is only a *candidate*. It always becomes a pending draft that a human
approves; a screenshot is evidence, not proof that money reached the account.
"""
import base64
import json
import re
from datetime import datetime
from typing import Optional

from ..config import settings

PROMPT = """You are reading a screenshot of a UPI payment confirmation from an Indian payment app.
Return ONLY a JSON object, no markdown, with these keys (use null if not visible):
{"amount": number, "utr": string, "paid_at": "YYYY-MM-DD HH:MM" (24h), "payer_name": string,
 "payee_name": string, "status": "success" | "failed" | "pending" | "unknown", "is_upi_screenshot": boolean}
Do not guess values that are not visible."""


class ScreenshotError(Exception):
    pass


def parse_model_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScreenshotError(f"Model did not return valid JSON: {exc}")


def normalise(data: dict) -> dict:
    """Validate/clean what the model returned. Raises ScreenshotError if unusable."""
    if not data.get("is_upi_screenshot", True):
        raise ScreenshotError("Image does not look like a UPI payment screenshot")
    if data.get("status") not in (None, "success", "unknown"):
        raise ScreenshotError(f"Payment status in screenshot is '{data.get('status')}', not success")
    try:
        amount = float(data["amount"])
    except (KeyError, TypeError, ValueError):
        raise ScreenshotError("Could not read the amount")
    if amount <= 0:
        raise ScreenshotError("Amount must be positive")
    paid_at: Optional[datetime] = None
    if data.get("paid_at"):
        try:
            paid_at = datetime.strptime(data["paid_at"], "%Y-%m-%d %H:%M")
        except ValueError:
            paid_at = None
    utr = re.sub(r"\s+", "", str(data["utr"])) if data.get("utr") else None
    return {"amount": amount, "utr": utr, "paid_at": paid_at,
            "payer_name": data.get("payer_name"), "payee_name": data.get("payee_name")}


def extract_upi_details(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    if not settings.anthropic_api_key:
        raise ScreenshotError("ANTHROPIC_API_KEY is not configured")
    import anthropic  # imported lazily so the app runs without the key during Phase 1

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=500,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.b64encode(image_bytes).decode()}},
            {"type": "text", "text": PROMPT},
        ]}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return normalise(parse_model_json(text))
