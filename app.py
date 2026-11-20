
"""TymeNaro FastAPI application entrypoint."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.database import init_master_db
from routes import auth, me, missions, tasks, admin, super_admin


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="TymeNaro")

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

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
def startup():
    # Initialize only the central database.
    # Never initialize the legacy database or import Excel files here.
    init_master_db()
