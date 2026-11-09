"""Pytest fixtures: temp DB + test client. The importer needs the real Excel
files to seed data, so tests copy them into a temp data dir."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def temp_env(monkeypatch):
    """Copy the real Excel files into a temp dir, point config at it, and
    create a fresh DB file. Yields the temp DB path."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "data").mkdir()
    for fname in ("Yves_TemplateEmployee.xls", "Yves_TemplateMission.xls.xlsx"):
        src = ROOT / "data" / fname
        if src.exists():
            shutil.copy(src, tmp / "data" / fname)
    (tmp / "db").mkdir()

    # Rewrite config paths before app imports
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp / "data")
    monkeypatch.setattr(config, "DB_DIR",   tmp / "db")
    monkeypatch.setattr(config, "EMP_XLS",  tmp / "data" / "Yves_TemplateEmployee.xls")
    monkeypatch.setattr(config, "MIS_XLS",  tmp / "data" / "Yves_TemplateMission.xls.xlsx")
    monkeypatch.setattr(config, "DB_PATH",  tmp / "db" / "audit.db")

    # Reload DB module so it points at the new file
    import importlib
    import core.database
    importlib.reload(core.database)

    core.database.init_db()
    from services.importer import load_data
    load_data([])

    yield tmp / "db" / "audit.db"
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def client(temp_env):
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)