"""Import employees and missions from the Excel source files."""
import re
import os
import pandas as pd

from config import EMP_XLS, MIS_XLS, TEAMS_XLS, ALIASES, MISSING_EMPLOYEES
from core.database import connect
from core.security import hash_password


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def load_data(report: list) -> None:
    c = connect()

    # ---------- Employees ----------
    if c.execute("SELECT COUNT(*) FROM Employee").fetchone()[0] == 0:
        try:
            df = pd.read_excel(EMP_XLS)
        except Exception as e:
            raise RuntimeError(f"Could not read the Excel file: {e}")

        print(f"\n[DEBUG] Reading file: {EMP_XLS}")
        print(f"[DEBUG] Columns found: {df.columns.tolist()}\n")

        class_col = next((col for col in df.columns if str(col).strip().lower() == "classification"), None)

        for _, r in df.iterrows():
            name  = str(r["EmployeeName"]).strip()
            login = str(r["Login"]).strip()
            uname = str(r["Username"]).strip()
            
            classification = ""
            if class_col and pd.notna(r[class_col]):
                classification = str(r[class_col]).strip()

            c.execute(
                """INSERT OR IGNORE INTO Employee
                   (EmployeeName, LoginCode, Username, PasswordHash, Classification, TenantID)
                   VALUES (?,?,?,?,?,1)""",
                (name, login, uname, hash_password(login), classification),
            )
            
        for e in MISSING_EMPLOYEES:
            c.execute(
                """INSERT OR IGNORE INTO Employee
                   (EmployeeName, LoginCode, Username, PasswordHash, TenantID)
                   VALUES (?,?,?,?,1)""",
                (e["name"], e["login"], e["username"], hash_password(e["login"])),
            )
            report.append(("INFO", e["name"],
                           f"created employee (username {e['username']}) — confirm with HR"))

    # ---------- Team Leader Assignments ----------
    if os.path.exists(TEAMS_XLS):
        teams_df = pd.read_excel(TEAMS_XLS)
        print(f"\n[DEBUG] Reading teams from: {TEAMS_XLS}")
        for _, r in teams_df.iterrows():
            leader = str(r["Team Leader"]).strip()
            member = str(r["Team Member"]).strip()
            
            c.execute(
                "UPDATE Employee SET TeamLeader = ? WHERE LOWER(EmployeeName) = LOWER(?)",
                (leader, member)
            )
    else:
        print(f"\n[WARNING] Teams file not found at {TEAMS_XLS}. Team Leader assignments skipped.")

    emp = {_norm(r["EmployeeName"]): r["EmployeeID"]
           for r in c.execute("SELECT EmployeeID, EmployeeName FROM Employee")}

    # ---------- Missions + Tasks ----------
    if c.execute("SELECT COUNT(*) FROM MissionTask").fetchone()[0] == 0:
        df = pd.read_excel(MIS_XLS, sheet_name="Yves_TemplateMission")
        
        fiscal_col = next((col for col in df.columns if str(col).strip().lower() == "fiscal year"), None)
        
        for excel_row, r in df.iterrows():
            ws_str = str(r["Date1"])[:10]
            we_str = str(r["Date2"])[:10]
            
            fiscal_yr = ""
            if fiscal_col and pd.notna(r[fiscal_col]):
                fiscal_yr = str(r[fiscal_col]).strip()

            # Look up the ServiceID based on the Service text
            service_text = str(r["Service"]).strip()
            service_row = c.execute("SELECT ServiceID FROM Service WHERE TenantID=1 AND ServiceName = ?", (service_text,)).fetchone()
            
            if service_row:
                service_id = service_row["ServiceID"]
            else:
                # Create the service dynamically if it doesn't exist
                c.execute("INSERT INTO Service (TenantID, ServiceName) VALUES (1, ?)", (service_text,))
                service_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Insert into Mission using ServiceID
            c.execute(
                """INSERT OR IGNORE INTO Mission
                   (TenantID, IDHonorary, CustomerName, ServiceID, FiscalYear, WindowStart, WindowEnd)
                   VALUES (1, ?, ?, ?, ?, ?, ?)""",
                (int(r["IDHonorary"]),
                 str(r["Customer Name"]).strip(),
                 service_id,
                 fiscal_yr,
                 ws_str, we_str),
            )
            mid = c.execute(
                """SELECT MissionID FROM Mission
                   WHERE TenantID=1 AND IDHonorary=? AND CustomerName=?
                     AND WindowStart=? AND WindowEnd=?""",
                (int(r["IDHonorary"]),
                 str(r["Customer Name"]).strip(),
                 ws_str, we_str),
            ).fetchone()["MissionID"]

            raw = str(r["Team Member"]).strip()
            key = ALIASES.get(_norm(raw), _norm(raw))
            eid = emp.get(key)
            if eid is None:
                raise RuntimeError(
                    f"Row {excel_row + 2}: unknown team member '{raw}'. "
                    f"Fix the name or add it to ALIASES / MISSING_EMPLOYEES "
                    f"in config.py before starting."
                )

            # Handle the new TaskName and TaskDescription columns
            # If they don't exist in the Excel file, fall back to the old audit columns
            task_name = ""
            if "TaskName" in df.columns:
                task_name = str(r["TaskName"]).strip()
            elif "SubSubSectionName" in df.columns:
                task_name = str(r["SubSubSectionName"]).strip()
            
            task_desc = ""
            if "TaskDescription" in df.columns:
                task_desc = str(r["TaskDescription"]).strip()
            elif "SectionName" in df.columns:
                section = str(r.get("SectionName", "")).strip()
                sub = str(r.get("SubSectionName", "")).strip()
                task_desc = f"{section} / {sub}" if section else sub
            
            c.execute(
                """INSERT OR IGNORE INTO MissionTask
                   (MissionID, TaskName, TaskDescription, TeamMemberName, EmployeeID, AllocatedHours, Date1, Date2, JobDesc, ExcelRow)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (mid,
                 task_name, task_desc,
                 raw, eid,
                 float(r["NbHours"]) if pd.notna(r["NbHours"]) else 0.0,
                 ws_str, we_str,
                 r.get("JobDesc"),
                 int(excel_row)),
            )

    c.commit()
    c.close()