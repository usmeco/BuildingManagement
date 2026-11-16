import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Current time in India (naive, so it stores cleanly in SQLite)."""
    return datetime.now(IST).replace(tzinfo=None)


def current_month() -> str:
    return now_ist().strftime("%Y-%m")


class Settings:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./buildingmate.db")
    admin_api_key = os.getenv("ADMIN_API_KEY", "change-me")
    default_monthly_amount = int(os.getenv("DEFAULT_MONTHLY_AMOUNT", "1000"))
    evidence_dir = os.getenv("EVIDENCE_DIR", "./evidence")
    reports_dir = os.getenv("REPORTS_DIR", "./reports")

    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    whatsapp_token = os.getenv("WHATSAPP_TOKEN", "")
    whatsapp_phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    whatsapp_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    whatsapp_app_secret = os.getenv("WHATSAPP_APP_SECRET", "")
    admin_phones = [p.strip() for p in os.getenv("ADMIN_PHONES", "").split(",") if p.strip()]

    reminders_enabled = os.getenv("REMINDERS_ENABLED", "false").lower() == "true"
    reminder_template_name = os.getenv("REMINDER_TEMPLATE_NAME", "maintenance_reminder")


settings = Settings()
