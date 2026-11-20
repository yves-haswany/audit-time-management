"""Database connection and schema."""
import sqlite3
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS Tenant(
  TenantID     INTEGER PRIMARY KEY AUTOINCREMENT,
  CompanyName  TEXT NOT NULL UNIQUE,
  Industry     TEXT NOT NULL,
  IsActive     INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS Service(
  ServiceID    INTEGER PRIMARY KEY AUTOINCREMENT,
  TenantID     INTEGER REFERENCES Tenant(TenantID),
  ServiceName  TEXT NOT NULL,
  Letter       TEXT DEFAULT '',
  UNIQUE(TenantID, ServiceName));

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
  IndustryID   INTEGER REFERENCES Industry(IndustryID));

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
  UNIQUE(TenantID, EmployeeName));

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
  UNIQUE(TenantID, IDHonorary, CustomerName, WindowStart, WindowEnd));

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
  Adopted      INTEGER DEFAULT 0,
  Launched     INTEGER DEFAULT 0,
  Suspended    INTEGER DEFAULT 0,
  Accomplished INTEGER DEFAULT 0,
  ExcelRow     INTEGER,
  UNIQUE(MissionID, TaskName, TeamMemberName));

CREATE TABLE IF NOT EXISTS WorkSession(
  SessionID  INTEGER PRIMARY KEY AUTOINCREMENT,
  EmployeeID INTEGER REFERENCES Employee(EmployeeID),
  MissionID  INTEGER REFERENCES Mission(MissionID),
  TaskID     INTEGER REFERENCES MissionTask(TaskID),
  LoginTime  TEXT NOT NULL,
  LogoutTime TEXT,
  TimeLogID  INTEGER,
  JobDesc    TEXT);

CREATE TABLE IF NOT EXISTS Token(
  Token      TEXT PRIMARY KEY,
  EmployeeID INTEGER,
  CreatedAt  TEXT);

CREATE VIEW IF NOT EXISTS MemberMissionBudget AS
WITH sess AS (
  SELECT EmployeeID, MissionID,
         SUM((julianday(LogoutTime)-julianday(LoginTime))*24) AS ConsumedHours
  FROM WorkSession
  WHERE LogoutTime IS NOT NULL
  GROUP BY EmployeeID, MissionID),
tasks AS (
  SELECT EmployeeID, MissionID,
         SUM(AllocatedHours) AS AllocatedHours,
         SUM(Accomplished)   AS TasksDone,
         COUNT(*)            AS TasksTotal
  FROM MissionTask
  GROUP BY EmployeeID, MissionID)
SELECT m.MissionID, m.CustomerName, m.IDHonorary, m.TenantID, m.ServiceID,
       m.WindowStart, m.WindowEnd,
       t.EmployeeID, t.AllocatedHours,
       COALESCE(s.ConsumedHours, 0) AS ConsumedHours,
       ROUND(100.0 * COALESCE(s.ConsumedHours, 0) / NULLIF(t.AllocatedHours, 0), 1)
           AS PctConsumed,
       t.TasksDone, t.TasksTotal
FROM Mission m
JOIN tasks t ON t.MissionID = m.MissionID
LEFT JOIN sess s ON s.MissionID = m.MissionID AND s.EmployeeID = t.EmployeeID;

CREATE VIEW IF NOT EXISTS TaskSignTimes AS
SELECT t.TaskID,
       DATE(MAX(ws.LoginTime))  AS Signindate,
       TIME(MAX(ws.LoginTime))  AS Signintime,
       DATE(MAX(ws.LogoutTime)) AS Signoutdate,
       TIME(MAX(ws.LogoutTime)) AS Signouttime,
       SUM((julianday(ws.LogoutTime)-julianday(ws.LoginTime))*24) AS HoursLogged
FROM MissionTask t
LEFT JOIN WorkSession ws ON ws.TaskID = t.TaskID
GROUP BY t.TaskID;
"""

def connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def _column_exists(c, table, column) -> bool:
    rows = c.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)

def _table_exists(c, table) -> bool:
    row = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None



def _migrate(c) -> None:
    """Migrate existing tables while preserving IDs and relationships."""

    # ---- Service.Letter ----
    if _table_exists(c, "Service") and not _column_exists(
        c, "Service", "Letter"
    ):
        c.execute("ALTER TABLE Service ADD COLUMN Letter TEXT DEFAULT ''")

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

    # ---- Check which tables need rebuilding ----

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
                "TenantID=1 does not exist. Catalog migration cancelled."
            )

    # Foreign keys must be disabled outside a transaction.
    c.commit()
    c.execute("PRAGMA foreign_keys = OFF")

    try:
        c.execute("BEGIN IMMEDIATE")

        # =====================================================
        # 1. REBUILD EMPLOYEE
        # Remove only Employee -> Tenant foreign key.
        # Preserve all employee IDs and credentials.
        # =====================================================

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

            # Restore the case-insensitive username index.
            c.execute("""
                CREATE UNIQUE INDEX ux_emp_uname
                ON Employee(LOWER(Username))
            """)

        # =====================================================
        # 2. REBUILD INDUSTRY
        # Preserve IndustryID and Client.IndustryID references.
        # Assign existing records to Tenant 1.
        # =====================================================

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

        # =====================================================
        # 3. REBUILD SECTION CATALOG
        # Preserve SectionID and all existing catalog values.
        # Assign existing records to Tenant 1.
        # =====================================================

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

        # =====================================================
        # 4. VALIDATE ALL FOREIGN KEYS
        # =====================================================

        violations = c.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if violations:
            details = [tuple(row) for row in violations]

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


def init_db() -> None:
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

