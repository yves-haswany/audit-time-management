
"""TymeNaro central configuration."""

import os
from pathlib import Path

# ============================================================
# PROJECT PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
DB_DIR = BASE_DIR / "db"
TENANT_DB_DIR = DB_DIR / "tenants"

EXPORT_DIR = BASE_DIR / "exports"

DB_DIR.mkdir(exist_ok=True)
TENANT_DB_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)

# ============================================================
# DATABASE PATHS
# ============================================================

# Original shared database.
# Preserve this database during migration.
LEGACY_DB_PATH = DB_DIR / "audit.db"

# Central database for Super Admin and tenant directory.
MASTER_DB_PATH = DB_DIR / "master.db"

# Existing connection compatibility during migration.
DB_PATH = LEGACY_DB_PATH

# ============================================================
# EXCEL SOURCES
# EXCLUSIVELY FOR FIDUCIAIRE DU MOYEN ORIENT
# ============================================================

INITIAL_TENANT_ID = 1
INITIAL_COMPANY_NAME = "Fiduciaire du Moyen Orient"

TEAMS_XLS = DATA_DIR / "Yves_TemplateTeams.xls"
EMP_XLS = DATA_DIR / "Yves_TemplateEmployee(2).xls"
MIS_XLS = DATA_DIR / "Yves_TemplateMission.xls(2).xlsx"

INDUSTRY_XLS = DATA_DIR / "Industry.xls"
SERVICES_XLS = DATA_DIR / "Services.xls"
SECTIONS_XLS = DATA_DIR / "Sections.xls"
CUSTOMERS_XLS = DATA_DIR / "Customers.xls"

# This flag controls the one-time legacy Excel import.
# It must never be used to seed newly created tenants.
ENABLE_INITIAL_TENANT_IMPORT = True

# ============================================================
# TENANT EXPORT PATHS
# ============================================================

def tenant_db_path(tenant_id: int) -> Path:
    tenant_id = int(tenant_id)

    if tenant_id <= 0:
        raise ValueError("Invalid tenant ID.")

    return TENANT_DB_DIR / f"tenant_{tenant_id}.db"


def tenant_export_dir(tenant_id: int) -> Path:
    tenant_id = int(tenant_id)

    if tenant_id <= 0:
        raise ValueError("Invalid tenant ID.")

    path = EXPORT_DIR / f"tenant_{tenant_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ============================================================
# AUTHENTICATION
# ============================================================

TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "12"))

# ============================================================
# EMPLOYEE NAME ALIASES
# ============================================================

ALIASES: dict[str, str] = {}

# ============================================================
# MISSING EMPLOYEES
# EXCLUSIVELY FOR THE INITIAL TENANT IMPORT
# ============================================================

MISSING_EMPLOYEES = [
    {
        "name": "Toufic Antoine Daoud",
        "login": "TAD",
        "username": "TAD",
    },
]

