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

CREATE TABLE IF NOT EXISTS SectionCatalog(
  SectionID         INTEGER PRIMARY KEY AUTOINCREMENT,
  Industry          TEXT NOT NULL,
  Service           TEXT NOT NULL,
  SectionName       TEXT,
  SubSectionName    TEXT,
  SubSubSectionName TEXT,
  Remarks           TEXT,
  DefaultHours      REAL DEFAULT 1,
  UNIQUE(Industry, Service, SectionName, SubSectionName, SubSubSectionName));

CREATE TABLE IF NOT EXISTS Industry(
  IndustryID   INTEGER PRIMARY KEY AUTOINCREMENT,
  ClientType   TEXT NOT NULL,
  Industry     TEXT NOT NULL,
  UNIQUE(ClientType, Industry));

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
  TenantID     INTEGER REFERENCES Tenant(TenantID),
  EmployeeName TEXT NOT NULL,
  LoginCode    TEXT NOT NULL,
  Username     TEXT NOT NULL,
  PasswordHash TEXT NOT NULL,
  IsActive     INTEGER DEFAULT 1,
  IsTeamLead   INTEGER DEFAULT 0,
  Classification TEXT,
  TeamLeader   TEXT,
  UNIQUE(TenantID, EmployeeName));
CREATE UNIQUE INDEX IF NOT EXISTS ux_emp_uname ON Employee(LOWER(Username));

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
    """Apply safe migrations to an existing database."""

    # ---- Service.Letter ----
    if _table_exists(c, "Service") and not _column_exists(c, "Service", "Letter"):
        c.execute("ALTER TABLE Service ADD COLUMN Letter TEXT DEFAULT ''")

    # ---- Client: extended columns (from Customers.xls) ----
    new_client_cols = [
        ("Phone2",       "TEXT"),
        ("Building",     "TEXT"),
        ("Street",       "TEXT"),
        ("City",         "TEXT"),
        ("Region",       "TEXT"),
        ("Country",      "TEXT"),
        ("Nationality",  "TEXT"),
        ("ClientType",   "TEXT"),
        ("TeamLeader",   "TEXT"),
        ("IndustryID",   "INTEGER"),
    ]
    if _table_exists(c, "Client"):
        for name, typ in new_client_cols:
            if not _column_exists(c, "Client", name):
                c.execute(f"ALTER TABLE Client ADD COLUMN {name} {typ}")

def init_db() -> None:
    c = connect()
    c.executescript(SCHEMA)
    _migrate(c)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_client_name ON Client(TenantID, CustomerName)")
    c.commit()
    c.close()