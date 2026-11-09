"""Central configuration — the only file you edit when HR updates the Excel
source or adds a new employee."""
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_DIR   = BASE_DIR / "db"
DB_DIR.mkdir(exist_ok=True)

EMP_XLS = DATA_DIR / "Yves_TemplateEmployee.xls"
MIS_XLS = DATA_DIR / "Yves_TemplateMission.xls(2).xlsx"
DB_PATH = DB_DIR / "audit.db"

# Auth
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "12"))

# Name-mismatch aliases between the mission file and the employee file.
# v5 data has none, but keep this mechanism for future renames:
#   ALIASES["old spelling"] = "canonical EmployeeName"
ALIASES: dict[str, str] = {}

# People who own mission rows but are absent from the employee file.
# The importer will create them with these credentials (bcrypt-hashed).
MISSING_EMPLOYEES = [
    {"name": "Toufic Antoine Daoud", "login": "TAD", "username": "TAD"},
]