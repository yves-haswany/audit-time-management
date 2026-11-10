"""Database connection and schema."""
import sqlite3
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS Employee(
  EmployeeID   INTEGER PRIMARY KEY AUTOINCREMENT,
  EmployeeName TEXT UNIQUE NOT NULL,
  LoginCode    TEXT NOT NULL,
  Username     TEXT NOT NULL,
  PasswordHash TEXT NOT NULL,
  IsActive     INTEGER DEFAULT 1,
  IsTeamLead   INTEGER DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS ux_emp_uname ON Employee(LOWER(Username));

CREATE TABLE IF NOT EXISTS Mission(
  MissionID    INTEGER PRIMARY KEY AUTOINCREMENT,
  IDHonorary   INTEGER NOT NULL,
  CustomerName TEXT NOT NULL,
  Service      TEXT NOT NULL,
  FiscalYear   TEXT,  -- NEW
  WindowStart  TEXT NOT NULL,
  WindowEnd    TEXT NOT NULL,
  UNIQUE(IDHonorary, CustomerName, WindowStart, WindowEnd));

CREATE TABLE IF NOT EXISTS MissionTask(
  TaskID          INTEGER PRIMARY KEY AUTOINCREMENT,
  MissionID       INTEGER REFERENCES Mission(MissionID),
  SectionName     TEXT,
  SubSectionName  TEXT,
  SubSubSectionName TEXT,
  TeamMemberName  TEXT NOT NULL,
  EmployeeID      INTEGER REFERENCES Employee(EmployeeID),
  AllocatedHours  REAL NOT NULL DEFAULT 0,
  Date1           TEXT,  -- NEW
  Date2           TEXT,  -- NEW
  JobDesc         TEXT,
  Adopted      INTEGER DEFAULT 0,
  Launched     INTEGER DEFAULT 0,
  Suspended    INTEGER DEFAULT 0,
  Accomplished INTEGER DEFAULT 0,
  ExcelRow     INTEGER,
  UNIQUE(MissionID, SubSubSectionName, TeamMemberName));

CREATE TABLE IF NOT EXISTS WorkSession(
  SessionID  INTEGER PRIMARY KEY AUTOINCREMENT,
  EmployeeID INTEGER REFERENCES Employee(EmployeeID),
  MissionID  INTEGER REFERENCES Mission(MissionID),
  TaskID     INTEGER REFERENCES MissionTask(TaskID),
  LoginTime  TEXT NOT NULL,
  LogoutTime TEXT,
  TimeLogID INTEGER, 
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
SELECT m.MissionID, m.CustomerName, m.IDHonorary,
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


def init_db() -> None:
    c = connect()
    c.executescript(SCHEMA)
    c.commit()
    c.close()