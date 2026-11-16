# BuildingMate AI

AI-assisted maintenance accounting for a 30-flat building (ground + 5 floors, flats `001-005` ... `501-505`).
It records payments from chat messages and UPI screenshots, keeps an approved ledger, builds the monthly Excel
workbook, tracks expenses and reserve, and prepares reminders. See the BRD for the full requirements.

## Design rules (from the BRD)
- **Phase 1 text rule:** only `1000 paid, 205` counts as a payment. Everything else is ignored (no false positives).
- **AI never posts to the ledger.** Messages and screenshots become `pending` drafts; an admin approves, edits or rejects.
- **Ledger is the source of truth.** Monthly sheets are generated from approved payments and expenses.
- **Expected is not received:** closing reserve = opening + approved collections - approved expenses.
- **Duplicate UTRs are blocked** unless explicitly overridden. Every action is in the audit log.
- **WhatsApp:** bot number, one-to-one chats only (forward payments to the bot). Not group reading.

## Setup (macOS)
```bash
cd /Users/aafreen/Desktop/MyProjects/Repositories/BuildingManagement
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then set ADMIN_API_KEY
python -m scripts.seed_flats    # creates the 30 flats (optionally pass a residents CSV)
uvicorn app.main:app --reload   # open http://127.0.0.1:8000/docs
pytest                          # run the tests
```
All `/api` routes need the header `X-Admin-Key: <your key>`. The built-in `/docs` page cannot set it for you,
so use the curl examples below (or a tool like Postman) until the admin UI exists.

## Try it with curl
```bash
KEY=your-key
curl -H "X-Admin-Key: $KEY" -X POST localhost:8000/api/payments/parse-text \
  -H 'Content-Type: application/json' -d '{"text":"1000 paid, 205","month":"2026-11"}'
curl -H "X-Admin-Key: $KEY" -X POST localhost:8000/api/payments/1/approve
curl -H "X-Admin-Key: $KEY" localhost:8000/api/reports/2026-11/summary
curl -H "X-Admin-Key: $KEY" -o nov.xlsx localhost:8000/api/reports/2026-11/workbook
```
Special month (double amount): `PUT /api/months/2026-12` with `{"amount_per_flat": 2000}`;
one flat different: `POST /api/months/2026-12/overrides`.

## Project layout
```
app/
  config.py, database.py, models.py, schemas.py, main.py
  api/admin.py          flats, months, payments, expenses, reports, reminders, audit
  api/whatsapp.py       Meta Cloud API webhook
  services/parser.py    "1000 paid, 205" rule + flat validation
  services/ledger.py    drafts, approval, duplicates, month status, reserve maths
  services/excel_report.py  monthly workbook (Maintenance Detail, Expenses, Summary)
  services/screenshot.py    UPI screenshot -> JSON via Claude API (vision)
  services/whatsapp.py  signature check, send, inbound message handling
  services/reminders.py preview + send (opt-in only, paid flats skipped)
scripts/seed_flats.py   create flats / import residents CSV
tests/                  31 tests (parser, ledger rules, Excel, API, webhook flow)
```

## Roadmap
1. **Done:** database, parser, approval flow, Excel, expenses, reserve, audit, API.
2. **WhatsApp bot:** create a Meta Business app, add webhook `https://<host>/webhook/whatsapp`
   (use ngrok locally), fill `WHATSAPP_*` in `.env`, add your number to `ADMIN_PHONES`.
3. **Screenshots:** set `ANTHROPIC_API_KEY`; images sent to the bot become drafts with evidence saved in `evidence/`.
4. **Reminders:** get a WhatsApp template approved, then set `REMINDERS_ENABLED=true`.
5. **Admin UI:** a small Streamlit or React page over the `/api` routes.
6. **Deploy:** Render/Railway + PostgreSQL (`DATABASE_URL`), then run one real month alongside the manual process.

## Open decisions (BRD section 20)
Due date and grace period, who approves expenses, retention period for screenshots and contact data,
and whether residents may pay in advance. Residents should be told what is stored and why before go-live.
