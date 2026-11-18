"""Audit Time Management — FastAPI entrypoint.

Run with:  uvicorn app:app --reload
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.database import init_db
from services.importer import (
    load_data,
    seed_industries_from_excel,
    seed_clients_from_missions,
    seed_industries_unclassified_fallback,
    link_clients_to_industries,
    seed_services_from_excel, 
    seed_sections_from_excel, 
    seed_customers_from_excel,
)
from routes import auth, me, missions, tasks, admin, super_admin

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
app.include_router(super_admin.router)

@app.get("/", response_class=FileResponse)
def index():
    return BASE_DIR / "templates" / "index.html"

@app.get("/super-admin", response_class=FileResponse)
def super_admin_ui():
    return BASE_DIR / "templates" / "super_admin.html"

@app.on_event("startup")
def _startup():
    init_db()

    from core.database import connect
    c = connect()
    c.execute("INSERT OR IGNORE INTO Tenant (TenantID, CompanyName, Industry) VALUES (1, 'Audit Company', 'Auditing')")
    c.execute("INSERT OR IGNORE INTO Service (TenantID, ServiceName) VALUES (1, 'Audit')")
    c.commit()
    c.close()

    # 1. Seed industries from Excel
    seed_industries_from_excel()

    # 2. Import employees, teams, missions
    report: list = []
    load_data(report)

    # 3. Backfill clients from missions
    seed_clients_from_missions()

    # 4. Attach every client to 'Other / Unclassified'
    seed_industries_unclassified_fallback()
    link_clients_to_industries()

    # 5. Seed the full services list from Excel  <-- NEW
    seed_services_from_excel()

    # 6. Seed the section catalog from Excel  <-- NEW
    seed_sections_from_excel()

    # 7. Seed the customer list from Excel  <-- NEW
    seed_customers_from_excel()