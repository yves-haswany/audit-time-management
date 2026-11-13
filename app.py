"""Audit Time Management — FastAPI entrypoint.

Run with:  uvicorn app:app --reload
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.database import init_db
from services.importer import load_data
from routes import auth, me, missions, tasks, admin, super_admin  # ADDED super_admin

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Audit Time Management")

# Static files (CSS + JS)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# API routers
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(missions.router)
app.include_router(tasks.router)
app.include_router(admin.router)
app.include_router(super_admin.router) # ADDED THIS LINE

@app.get("/", response_class=FileResponse)
def index():
    return BASE_DIR / "templates" / "index.html"

# NEW ROUTE: Serve the Super Admin UI
@app.get("/super-admin", response_class=FileResponse)
def super_admin_ui():
    return BASE_DIR / "templates" / "super_admin.html"

@app.on_event("startup")
def _startup():
    init_db()
    
    # --- ADD THIS BLOCK ---
    from core.database import connect
    c = connect()
    c.execute("INSERT OR IGNORE INTO Tenant (TenantID, CompanyName, Industry) VALUES (1, 'Audit Company', 'Auditing')")
    c.execute("INSERT OR IGNORE INTO Service (TenantID, ServiceName) VALUES (1, 'Audit')")
    c.commit()
    c.close()
    # ----------------------

    report: list = []
    load_data(report)