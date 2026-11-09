"""Audit Time Management — FastAPI entrypoint.

Run with:  uvicorn app:app --reload
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.database import init_db
from services.importer import load_data
from routes import auth, me, missions, tasks, admin

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


@app.get("/", response_class=FileResponse)
def index():
    return BASE_DIR / "templates" / "index.html"


@app.on_event("startup")
def _startup():
    init_db()
    report: list = []
    load_data(report)
    for lvl, who, msg in report:
        print(f"[import] {lvl:5} {who:40} {msg}")

    from core.database import connect
    c = connect()
    n_emp     = c.execute("SELECT COUNT(*) FROM Employee").fetchone()[0]
    n_tasks   = c.execute("SELECT COUNT(*) FROM MissionTask").fetchone()[0]
    n_mis     = c.execute("SELECT COUNT(*) FROM Mission").fetchone()[0]
    n_active  = c.execute(
        "SELECT COUNT(DISTINCT EmployeeID) FROM MissionTask"
    ).fetchone()[0]
    c.close()
    print(
        f"[import] OK {n_emp} employees ({n_active} with work), "
        f"{n_tasks} mission rows, {n_mis} missions"
    )