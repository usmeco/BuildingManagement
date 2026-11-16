from fastapi import FastAPI

from .api import admin, whatsapp
from .database import Base, engine

Base.metadata.create_all(engine)

app = FastAPI(title="BuildingMate AI", version="0.1.0",
              description="AI-assisted building maintenance accounting. Admin routes need X-Admin-Key.")
app.include_router(admin.router, prefix="/api", tags=["admin"])
app.include_router(whatsapp.router, tags=["whatsapp"])


@app.get("/health")
def health():
    return {"status": "ok"}
