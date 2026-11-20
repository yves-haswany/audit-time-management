
"""TymeNaro database connections, schemas and migrations.

Database architecture:
    db/audit.db                 Legacy database; preserved during migration
    db/master.db                Central tenant directory and authentication
    db/tenants/tenant_1.db      Fiduciaire du Moyen Orient
    db/tenants/tenant_2.db      Company 2

IMPORTANT:
- connect() continues to use the legacy database.
- connect_master() connects to master.db.
- connect_tenant(id) connects to an existing tenant database.
- init_tenant_db() initializes a tenant database but DOES NOT
  import Excel files or migrate records from audit.db.
"""

import os
import sqlite3

from config import (
    DB_PATH,
    MASTER_DB_PATH,
    tenant_db_path,
)


# ============================================================
# TENANT OPERATIONAL DATABASE SCHEMA
# ============================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS Tenant(
  TenantID     INTEGER PRIMARY KEY AUTOINCREMENT,
  CompanyName  TEXT NOT NULL UNIQUE,
  Industry     TEXT NOT NULL,
  IsActive     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Service(
  ServiceID    INTEGER PRIMARY KEY AUTOINCREMENT,
  TenantID     INTEGER REFERENCES Tenant(TenantID),
  ServiceName  TEXT NOT NULL,
  Letter       TEXT DEFAULT '',
  UNIQUE(TenantID, ServiceName)
);

CREATE TABLE IF NOT EXISTS SectionCatalog (
    SectionID INTEGER PRIMARY KEY AUTOINCREMENT,
    TenantID INTEGER NOT NULL REFERENCES Tenant(TenantID),
    Industry TEXT NOT NULL,
    Service TEXT NOT NULL,
    SectionName TEXT,
    SubSectionName TEXT,
    SubSubSectionName TEXT,
    Remarks TEXT,
    DefaultHours REAL DEFAULT 1,
    IsDeleted INTEGER NOT NULL DEFAULT 0,
    UNIQUE(
        TenantID,
        Industry,
        Service,
        SectionName,
        SubSectionName,
        SubSubSectionName
    )
);

CREATE TABLE IF NOT EXISTS Industry (
    IndustryID INTEGER PRIMARY KEY AUTOINCREMENT,
    TenantID INTEGER NOT NULL REFERENCES Tenant(TenantID),
    ClientType TEXT NOT NULL,
    Industry TEXT NOT NULL,
    UNIQUE(TenantID, ClientType, Industry)
);

CREATE TABLE IF NOT EXISTS Client(
  ClientID     INTEGER PRIMARY KEY AUTOINCREMENT,
  TenantID     INTEGER REFERENCES Tenant(TenantID),
  CustomerName TEXT NOT NULL,
  IDHonorary   TEXT,
  Contact      TEXT,
  Email        TEXT,
  Phone        TEXT,
  Phone2       TEXT,
  Address      TEXT,
  Building     TEXT,
  Street       TEXT,
  City         TEXT,
  Region       TEXT,
  Country      TEXT,
  Nationality  TEXT,
  ClientType   TEXT,
  TeamLeader   TEXT,
  IndustryID   INTEGER REFERENCES Industry(IndustryID)
);

CREATE TABLE IF NOT EXISTS Employee(
  EmployeeID   INTEGER PRIMARY KEY AUTOINCREMENT,
  TenantID     INTEGER NOT NULL DEFAULT 0,
  EmployeeName TEXT NOT NULL,
  LoginCode    TEXT NOT NULL,
  Username     TEXT NOT NULL,
  PasswordHash TEXT NOT NULL,
  IsActive     INTEGER DEFAULT 1,
  IsTeamLead   INTEGER DEFAULT 0,
  Classification TEXT,
  TeamLeader   TEXT,
  UNIQUE(TenantID, EmployeeName)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_emp_uname
ON Employee(LOWER(Username));

CREATE TABLE IF NOT EXISTS Mission(
  MissionID    INTEGER PRIMARY KEY AUTOINCREMENT,
  TenantID     INTEGER REFERENCES Tenant(TenantID),
  IDHonorary   INTEGER NOT NULL,
  CustomerName TEXT NOT NULL,
  ServiceID    INTEGER REFERENCES Service(ServiceID),
  FiscalYear   TEXT,
  WindowStart  TEXT NOT NULL,
  WindowEnd    TEXT NOT NULL,
  UNIQUE(
      TenantID,
      IDHonorary,
      CustomerName,
      WindowStart,
      WindowEnd
  )
);

CREATE TABLE IF NOT EXISTS MissionTask(
  TaskID          INTEGER PRIMARY KEY AUTOINCREMENT,
  MissionID       INTEGER REFERENCES Mission(MissionID),
  TaskName        TEXT NOT NULL,
  TaskDescription TEXT,
  TeamMemberName  TEXT NOT NULL,
  EmployeeID      INTEGER REFERENCES Employee(EmployeeID),
  AllocatedHours  REAL NOT NULL DEFAULT 0,
  Date1           TEXT,
  Date2           TEXT,
  JobDesc         TEXT,
  Adopted         INTEGER DEFAULT 0,
  Launched        INTEGER DEFAULT 0,
  Suspended       INTEGER DEFAULT 0,
  Accomplished    INTEGER DEFAULT 0,
  ExcelRow        INTEGER,
  UNIQUE(MissionID, TaskName, TeamMemberName)
);

CREATE TABLE IF NOT EXISTS WorkSession(
  SessionID  INTEGER PRIMARY KEY AUTOINCREMENT,
  EmployeeID INTEGER REFERENCES Employee(EmployeeID),
  MissionID  INTEGER REFERENCES Mission(MissionID),
  TaskID     INTEGER REFERENCES MissionTask(TaskID),
  LoginTime  TEXT NOT NULL,
  LogoutTime TEXT,
  TimeLogID  INTEGER,
  JobDesc    TEXT
);

CREATE TABLE IF NOT EXISTS Token(
  Token      TEXT PRIMARY KEY,
  EmployeeID INTEGER,
  CreatedAt  TEXT
);

CREATE VIEW IF NOT EXISTS MemberMissionBudget AS
WITH sess AS (
  SELECT EmployeeID, MissionID,
         SUM(
             (julianday(LogoutTime)-julianday(LoginTime))*24
         ) AS ConsumedHours
  FROM WorkSession
  WHERE LogoutTime IS NOT NULL
  GROUP BY EmployeeID, MissionID
),
tasks AS (
  SELECT EmployeeID, MissionID,
         SUM(AllocatedHours) AS AllocatedHours,
         SUM(Accomplished) AS TasksDone,
         COUNT(*) AS TasksTotal
  FROM MissionTask
  GROUP BY EmployeeID, MissionID
)
SELECT
       m.MissionID,
       m.CustomerName,
       m.IDHonorary,
       m.TenantID,
       m.ServiceID,
       m.WindowStart,
       m.WindowEnd,
       t.EmployeeID,
       t.AllocatedHours,
       COALESCE(s.ConsumedHours, 0) AS ConsumedHours,
       ROUND(
           100.0 * COALESCE(s.ConsumedHours, 0)
           / NULLIF(t.AllocatedHours, 0),
           1
       ) AS PctConsumed,
       t.TasksDone,
       t.TasksTotal
FROM Mission m
JOIN tasks t ON t.MissionID = m.MissionID
LEFT JOIN sess s
       ON s.MissionID = m.MissionID
      AND s.EmployeeID = t.EmployeeID;

CREATE VIEW IF NOT EXISTS TaskSignTimes AS
SELECT
       t.TaskID,
       DATE(MAX(ws.LoginTime)) AS Signindate,
       TIME(MAX(ws.LoginTime)) AS Signintime,
       DATE(MAX(ws.LogoutTime)) AS Signoutdate,
       TIME(MAX(ws.LogoutTime)) AS Signouttime,
       SUM(
           (julianday(ws.LogoutTime)-julianday(ws.LoginTime))*24
       ) AS HoursLogged
FROM MissionTask t
LEFT JOIN WorkSession ws ON ws.TaskID = t.TaskID
GROUP BY t.TaskID;
"""


# ============================================================
# MASTER DATABASE SCHEMA
# ============================================================

MASTER_SCHEMA = """
CREATE TABLE IF NOT EXISTS TenantDirectory (
    TenantID INTEGER PRIMARY KEY,
    CompanyName TEXT NOT NULL UNIQUE,
    CompanyCode TEXT NOT NULL COLLATE NOCASE UNIQUE,
    Industry TEXT NOT NULL,
    IsActive INTEGER NOT NULL DEFAULT 1,
    DatabaseFile TEXT NOT NULL UNIQUE,
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS SuperAdmin (
    SuperAdminID INTEGER PRIMARY KEY AUTOINCREMENT,
    FullName TEXT NOT NULL,
    Username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    PasswordHash TEXT NOT NULL,
    IsActive INTEGER NOT NULL DEFAULT 1,
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS AuthSession (
    Token TEXT PRIMARY KEY,
    UserType TEXT NOT NULL
        CHECK (UserType IN ('superadmin', 'employee')),
    SuperAdminID INTEGER,
    TenantID INTEGER,
    EmployeeID INTEGER,
    CreatedAt TEXT NOT NULL,
    ExpiresAt TEXT NOT NULL,

    CHECK (
        (
            UserType = 'superadmin'
            AND SuperAdminID IS NOT NULL
            AND TenantID IS NULL
            AND EmployeeID IS NULL
        )
        OR
        (
            UserType = 'employee'
            AND SuperAdminID IS NULL
            AND TenantID IS NOT NULL
            AND EmployeeID IS NOT NULL
        )
    ),

    FOREIGN KEY (SuperAdminID)
        REFERENCES SuperAdmin(SuperAdminID),

    FOREIGN KEY (TenantID)
        REFERENCES TenantDirectory(TenantID)
);

CREATE INDEX IF NOT EXISTS ix_authsession_tenant
ON AuthSession(TenantID);

CREATE INDEX IF NOT EXISTS ix_authsession_superadmin
ON AuthSession(SuperAdminID);

CREATE TABLE IF NOT EXISTS ImportLog (
    ImportID INTEGER PRIMARY KEY AUTOINCREMENT,
    ImportKey TEXT NOT NULL UNIQUE,
    TenantID INTEGER NOT NULL,
    SourceDescription TEXT,
    ImportedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    Status TEXT NOT NULL DEFAULT 'completed',
    Details TEXT,

    FOREIGN KEY (TenantID)
        REFERENCES TenantDirectory(TenantID)
);

CREATE TABLE IF NOT EXISTS MigrationLog (
    MigrationID INTEGER PRIMARY KEY AUTOINCREMENT,
    MigrationKey TEXT NOT NULL UNIQUE,
    Status TEXT NOT NULL,
    ExecutedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    Details TEXT
);
"""


# ============================================================
# LEGACY DATABASE CONNECTION
# ============================================================

def connect() -> sqlite3.Connection:
    """
    Connect to the original shared database.

    Kept unchanged for compatibility with existing application
    routes while the tenant migration is being implemented.
    """
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


# ============================================================
# GENERIC DATABASE CONNECTION
# ============================================================

def _connect_database(path) -> sqlite3.Connection:
    """
    Connect to an existing SQLite database.

    Does not silently create a missing database.
    """
    path = str(path)

    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Database does not exist: {path}"
        )

    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")

    return c


# ============================================================
# MASTER DATABASE CONNECTION
# ============================================================

def connect_master() -> sqlite3.Connection:
    """
    Connect to the central master database.

    init_master_db() must be called before this function.
    """
    return _connect_database(MASTER_DB_PATH)


# ============================================================
# TENANT DATABASE CONNECTION
# ============================================================

def connect_tenant(tenant_id: int) -> sqlite3.Connection:
    """
    Connect to an existing tenant database.

    The tenant ID must be positive.
    This function does not create a missing database.
    """
    tenant_id = int(tenant_id)

    if tenant_id <= 0:
        raise ValueError("Invalid tenant ID.")

    return _connect_database(tenant_db_path(tenant_id))


# ============================================================
# EXISTING SCHEMA HELPERS
# ============================================================

def _column_exists(c, table, column) -> bool:
    rows = c.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return any(row["name"] == column for row in rows)


def _table_exists(c, table) -> bool:
    row = c.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table,),
    ).fetchone()

    return row is not None


# ============================================================
# EXISTING DATABASE MIGRATIONS
# ============================================================

def _migrate(c) -> None:
    """
    Migrate existing operational tables while preserving IDs
    and relationships.
    """

    # ---- Service.Letter ----

    if (
        _table_exists(c, "Service")
        and not _column_exists(c, "Service", "Letter")
    ):
        c.execute(
            "ALTER TABLE Service ADD COLUMN Letter TEXT DEFAULT ''"
        )

    # ---- Client extended columns ----

    new_client_cols = [
        ("Phone2", "TEXT"),
        ("Building", "TEXT"),
        ("Street", "TEXT"),
        ("City", "TEXT"),
        ("Region", "TEXT"),
        ("Country", "TEXT"),
        ("Nationality", "TEXT"),
        ("ClientType", "TEXT"),
        ("TeamLeader", "TEXT"),
        ("IndustryID", "INTEGER"),
    ]

    if _table_exists(c, "Client"):
        for name, typ in new_client_cols:
            if not _column_exists(c, "Client", name):
                c.execute(
                    f"ALTER TABLE Client ADD COLUMN {name} {typ}"
                )

    # ---- SectionCatalog.IsDeleted ----

    if (
        _table_exists(c, "SectionCatalog")
        and not _column_exists(c, "SectionCatalog", "IsDeleted")
    ):
        c.execute("""
            ALTER TABLE SectionCatalog
            ADD COLUMN IsDeleted INTEGER NOT NULL DEFAULT 0
        """)

    # ---- Determine which tables require rebuilding ----

    employee_needs_migration = False

    if _table_exists(c, "Employee"):
        employee_fks = c.execute(
            "PRAGMA foreign_key_list(Employee)"
        ).fetchall()

        employee_needs_migration = any(
            row["table"] == "Tenant"
            for row in employee_fks
        )

    industry_needs_migration = (
        _table_exists(c, "Industry")
        and not _column_exists(c, "Industry", "TenantID")
    )

    section_needs_migration = (
        _table_exists(c, "SectionCatalog")
        and not _column_exists(c, "SectionCatalog", "TenantID")
    )

    if not (
        employee_needs_migration
        or industry_needs_migration
        or section_needs_migration
    ):
        return

    # Existing catalogs must belong to Company 1.

    if industry_needs_migration or section_needs_migration:
        tenant = c.execute("""
            SELECT TenantID
            FROM Tenant
            WHERE TenantID = 1
        """).fetchone()

        if tenant is None:
            raise RuntimeError(
                "TenantID=1 does not exist. "
                "Catalog migration cancelled."
            )

    # Foreign keys must be disabled outside a transaction.

    c.commit()
    c.execute("PRAGMA foreign_keys = OFF")

    try:
        c.execute("BEGIN IMMEDIATE")

        # ----------------------------------------------------
        # 1. REBUILD EMPLOYEE
        # ----------------------------------------------------

        if employee_needs_migration:
            c.execute("DROP TABLE IF EXISTS Employee_new")

            c.execute("""
                CREATE TABLE Employee_new (
                    EmployeeID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TenantID INTEGER NOT NULL DEFAULT 0,
                    EmployeeName TEXT NOT NULL,
                    LoginCode TEXT NOT NULL,
                    Username TEXT NOT NULL,
                    PasswordHash TEXT NOT NULL,
                    IsActive INTEGER DEFAULT 1,
                    IsTeamLead INTEGER DEFAULT 0,
                    Classification TEXT,
                    TeamLeader TEXT,
                    UNIQUE(TenantID, EmployeeName)
                )
            """)

            c.execute("""
                INSERT INTO Employee_new (
                    EmployeeID,
                    TenantID,
                    EmployeeName,
                    LoginCode,
                    Username,
                    PasswordHash,
                    IsActive,
                    IsTeamLead,
                    Classification,
                    TeamLeader
                )
                SELECT
                    EmployeeID,
                    TenantID,
                    EmployeeName,
                    LoginCode,
                    Username,
                    PasswordHash,
                    IsActive,
                    IsTeamLead,
                    Classification,
                    TeamLeader
                FROM Employee
            """)

            c.execute("DROP TABLE Employee")

            c.execute(
                "ALTER TABLE Employee_new RENAME TO Employee"
            )

            c.execute("""
                CREATE UNIQUE INDEX ux_emp_uname
                ON Employee(LOWER(Username))
            """)

        # ----------------------------------------------------
        # 2. REBUILD INDUSTRY
        # ----------------------------------------------------

        if industry_needs_migration:
            c.execute("DROP TABLE IF EXISTS Industry_new")

            c.execute("""
                CREATE TABLE Industry_new (
                    IndustryID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TenantID INTEGER NOT NULL REFERENCES Tenant(TenantID),
                    ClientType TEXT NOT NULL,
                    Industry TEXT NOT NULL,
                    UNIQUE(TenantID, ClientType, Industry)
                )
            """)

            c.execute("""
                INSERT INTO Industry_new (
                    IndustryID,
                    TenantID,
                    ClientType,
                    Industry
                )
                SELECT
                    IndustryID,
                    1,
                    ClientType,
                    Industry
                FROM Industry
            """)

            c.execute("DROP TABLE Industry")

            c.execute(
                "ALTER TABLE Industry_new RENAME TO Industry"
            )

        # ----------------------------------------------------
        # 3. REBUILD SECTION CATALOG
        # ----------------------------------------------------

        if section_needs_migration:
            c.execute("DROP TABLE IF EXISTS SectionCatalog_new")

            c.execute("""
                CREATE TABLE SectionCatalog_new (
                    SectionID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TenantID INTEGER NOT NULL REFERENCES Tenant(TenantID),
                    Industry TEXT NOT NULL,
                    Service TEXT NOT NULL,
                    SectionName TEXT,
                    SubSectionName TEXT,
                    SubSubSectionName TEXT,
                    Remarks TEXT,
                    DefaultHours REAL DEFAULT 1,
                    IsDeleted INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(
                        TenantID,
                        Industry,
                        Service,
                        SectionName,
                        SubSectionName,
                        SubSubSectionName
                    )
                )
            """)

            c.execute("""
                INSERT INTO SectionCatalog_new (
                    SectionID,
                    TenantID,
                    Industry,
                    Service,
                    SectionName,
                    SubSectionName,
                    SubSubSectionName,
                    Remarks,
                    DefaultHours,
                    IsDeleted
                )
                SELECT
                    SectionID,
                    1,
                    Industry,
                    Service,
                    SectionName,
                    SubSectionName,
                    SubSubSectionName,
                    Remarks,
                    DefaultHours,
                    COALESCE(IsDeleted, 0)
                FROM SectionCatalog
            """)

            c.execute("DROP TABLE SectionCatalog")

            c.execute(
                "ALTER TABLE SectionCatalog_new RENAME TO SectionCatalog"
            )

        # ----------------------------------------------------
        # 4. VALIDATE FOREIGN KEYS
        # ----------------------------------------------------

        violations = c.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if violations:
            details = [
                tuple(row) for row in violations
            ]

            raise RuntimeError(
                "Foreign-key violations detected. "
                f"Migration cancelled: {details}"
            )

        c.commit()

        print("Employee migration completed.")
        print("Industry migration completed.")
        print("SectionCatalog migration completed.")
        print("Foreign-key validation passed.")

    except Exception:
        c.rollback()
        raise

    finally:
        c.execute("PRAGMA foreign_keys = ON")


# ============================================================
# LEGACY DATABASE INITIALIZATION
# ============================================================

def init_db() -> None:
    """
    Initialize the original shared database.

    Kept for backward compatibility during the transition.
    """
    c = connect()

    try:
        c.executescript(SCHEMA)

        _migrate(c)

        c.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            ux_client_name
            ON Client(TenantID, CustomerName)
        """)

        c.commit()

    finally:
        c.close()


# ============================================================
# MASTER DATABASE INITIALIZATION
# ============================================================

def init_master_db() -> None:
    """
    Initialize the central master database.

    Creates:
    - TenantDirectory
    - SuperAdmin
    - AuthSession
    - ImportLog
    - MigrationLog

    Does not import or copy company records.
    """
    path = str(MASTER_DB_PATH)

    os.makedirs(os.path.dirname(path), exist_ok=True)

    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")

    try:
        c.executescript(MASTER_SCHEMA)

        violations = c.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if violations:
            raise RuntimeError(
                "Master database foreign-key violations: "
                f"{[tuple(row) for row in violations]}"
            )

        c.commit()

        result = c.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if result != "ok":
            raise RuntimeError(
                f"Master database integrity check failed: {result}"
            )

        print("Master database initialized successfully.")

    except Exception:
        c.rollback()
        raise

    finally:
        c.close()


# ============================================================
# MASTER TENANT REGISTRATION
# ============================================================

def register_master_tenant(
    tenant_id: int,
    company_name: str,
    company_code: str,
    industry: str,
    is_active: int = 1,
) -> None:
    """
    Register a company in the master tenant directory.

    Existing company details cannot be silently replaced.

    This function does not create its tenant database.
    """
    tenant_id = int(tenant_id)

    company_name = company_name.strip()
    company_code = company_code.strip().upper()
    industry = industry.strip()

    if tenant_id <= 0:
        raise ValueError("Invalid tenant ID.")

    if not company_name:
        raise ValueError("Company name is required.")

    if not company_code:
        raise ValueError("Company code is required.")

    if not industry:
        raise ValueError("Industry is required.")

    if is_active not in (0, 1):
        raise ValueError("is_active must be 0 or 1.")

    database_file = tenant_db_path(tenant_id).name

    c = connect_master()

    try:
        existing = c.execute("""
            SELECT *
            FROM TenantDirectory
            WHERE TenantID = ?
        """, (tenant_id,)).fetchone()

        if existing:
            if (
                existing["CompanyName"] != company_name
                or existing["CompanyCode"].upper() != company_code
                or existing["Industry"] != industry
                or existing["DatabaseFile"] != database_file
            ):
                raise ValueError(
                    f"Tenant {tenant_id} is already registered "
                    "with different company details."
                )

            c.execute("""
                UPDATE TenantDirectory
                SET IsActive = ?
                WHERE TenantID = ?
            """, (is_active, tenant_id))

        else:
            c.execute("""
                INSERT INTO TenantDirectory (
                    TenantID,
                    CompanyName,
                    CompanyCode,
                    Industry,
                    IsActive,
                    DatabaseFile
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                tenant_id,
                company_name,
                company_code,
                industry,
                is_active,
                database_file,
            ))

        c.commit()

    except Exception:
        c.rollback()
        raise

    finally:
        c.close()


# ============================================================
# TENANT DATABASE INITIALIZATION
# ============================================================

def init_tenant_db(
    tenant_id: int,
    company_name: str | None = None,
    industry: str | None = None,
) -> None:
    """
    Initialize one tenant's operational database.

    Requirements:
    - Tenant must already exist in master.db.
    - Tenant must be active.
    - Database identity must match the master directory.

    This function:
    - Creates the operational schema if missing.
    - Runs the existing schema migrations.
    - Creates the tenant identity row if missing.
    - Validates foreign keys and database integrity.

    It does NOT:
    - Import Excel files.
    - Copy data from audit.db.
    - Create employees or administrators.
    - Modify another tenant's database.
    """
    tenant_id = int(tenant_id)

    if tenant_id <= 0:
        raise ValueError("Invalid tenant ID.")

    master = connect_master()

    try:
        tenant = master.execute("""
            SELECT
                TenantID,
                CompanyName,
                CompanyCode,
                Industry,
                IsActive,
                DatabaseFile
            FROM TenantDirectory
            WHERE TenantID = ?
        """, (tenant_id,)).fetchone()

        if tenant is None:
            raise ValueError(
                f"Tenant {tenant_id} is not registered "
                "in the master database."
            )

        if company_name is not None:
            if company_name.strip() != tenant["CompanyName"]:
                raise ValueError(
                    "Company name does not match the master "
                    "tenant directory."
                )

        if industry is not None:
            if industry.strip() != tenant["Industry"]:
                raise ValueError(
                    "Industry does not match the master "
                    "tenant directory."
                )

        expected_filename = tenant_db_path(tenant_id).name

        if tenant["DatabaseFile"] != expected_filename:
            raise RuntimeError(
                "Tenant database filename does not match "
                "the configured tenant database path."
            )

        if not tenant["IsActive"]:
            raise ValueError(
                f"Tenant {tenant_id} is inactive."
            )

        tenant_name = tenant["CompanyName"]
        tenant_industry = tenant["Industry"]
        tenant_active = int(tenant["IsActive"])

    finally:
        master.close()

    path = tenant_db_path(tenant_id)

    os.makedirs(os.path.dirname(str(path)), exist_ok=True)

    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")

    try:
        # Create operational tables and views.
        c.executescript(SCHEMA)

        # Apply existing migrations.
        _migrate(c)

        # Preserve existing uniqueness rule.
        c.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            ux_client_name
            ON Client(TenantID, CustomerName)
        """)

        # Check tenant identity.
        existing = c.execute("""
            SELECT TenantID, CompanyName, Industry
            FROM Tenant
            WHERE TenantID = ?
        """, (tenant_id,)).fetchone()

        if existing is None:

            other_tenants = c.execute(
                "SELECT TenantID FROM Tenant"
            ).fetchall()

            if other_tenants:
                raise RuntimeError(
                    "The tenant database already contains "
                    "a different tenant identity."
                )

            c.execute("""
                INSERT INTO Tenant (
                    TenantID,
                    CompanyName,
                    Industry,
                    IsActive
                )
                VALUES (?, ?, ?, ?)
            """, (
                tenant_id,
                tenant_name,
                tenant_industry,
                tenant_active,
            ))

        else:
            if (
                existing["CompanyName"] != tenant_name
                or existing["Industry"] != tenant_industry
            ):
                raise RuntimeError(
                    "Tenant database identity does not match "
                    "the master tenant directory."
                )

        # A tenant database must contain only its own identity.
        other_tenants = c.execute("""
            SELECT TenantID
            FROM Tenant
            WHERE TenantID != ?
        """, (tenant_id,)).fetchall()

        if other_tenants:
            raise RuntimeError(
                "Unexpected additional tenant identities "
                "found in tenant database: "
                f"{[row['TenantID'] for row in other_tenants]}"
            )

        # Validate foreign keys.
        violations = c.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if violations:
            raise RuntimeError(
                "Tenant database foreign-key violations: "
                f"{[tuple(row) for row in violations]}"
            )

        c.commit()

        # Validate database integrity.
        result = c.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if result != "ok":
            raise RuntimeError(
                f"Tenant database integrity check failed: {result}"
            )

        print(
            "Tenant database initialized successfully: "
            f"{tenant_name} (TenantID={tenant_id})"
        )

    except Exception:
        c.rollback()
        raise

    finally:
        c.close()
