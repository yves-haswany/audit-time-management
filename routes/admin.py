"""Admin endpoints — Excel exporter, mission list, and admin CRUD for
teams / employees / clients / services / industries."""
from __future__ import annotations

import os
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from core.dependencies import current_user
from core.database import connect
from scripts.export_mission import export_mission_to_bytes
from scripts.export_timelog import get_filtered_logs_as_list, export_user_logs_to_bytes

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ============================================================
# HELPERS
# ============================================================

def _require_admin(user=Depends(current_user)):
    """Reject anyone whose Classification is not 'Administrator' or 'Managing Partner'."""
    role = str(user.get("Classification", "")).strip().lower()
    if role not in ["administrator", "managing partner"]:
        raise HTTPException(403, "Administrator or Managing Partner only")
    return user


# ============================================================
# EXISTING ROUTES
# ============================================================

@router.get("/missions")
def all_missions(user=Depends(current_user)):
    c = connect()
    rows = c.execute(
        """
        SELECT
            m.MissionID,
            m.IDHonorary,
            m.CustomerName,
            s.ServiceName AS Service,
            m.FiscalYear,
            m.WindowStart,
            m.WindowEnd,
            COUNT(t.TaskID)                 AS TasksTotal,
            ROUND(SUM(t.AllocatedHours), 1) AS AllocatedHours
        FROM Mission m
        LEFT JOIN MissionTask t ON t.MissionID = m.MissionID
        LEFT JOIN Service s ON s.ServiceID = m.ServiceID
        GROUP BY m.MissionID
        ORDER BY m.WindowStart
        """
    ).fetchall()
    c.close()

    today = date.today().isoformat()
    out = []
    for r in rows:
        d = dict(r)
        if today < d["WindowStart"]:
            d["WindowStatus"] = "not_started"
        elif today > d["WindowEnd"]:
            d["WindowStatus"] = "overdue"
        else:
            d["WindowStatus"] = "open"
        out.append(d)
    return out


@router.get("/export/{mission_id}")
def export_mission(mission_id: int, user=Depends(current_user)):
    """Download the mission as an .xlsx with current progress filled in."""
    c = connect()
    m = c.execute(
        "SELECT MissionID, CustomerName, IDHonorary FROM Mission WHERE MissionID = ?",
        (mission_id,),
    ).fetchone()
    c.close()
    if not m:
        raise HTTPException(404, "Mission not found")

    try:
        data = export_mission_to_bytes(mission_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

    safe_customer = "".join(
        ch if ch.isalnum() else "_" for ch in m["CustomerName"]
    ).strip("_")
    filename = f"{safe_customer}_{m['IDHonorary']}_mission.xlsx"

    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/time-logs")
def view_time_logs(user=Depends(current_user)):
    """Returns a filtered list of time logs based on the user's role."""
    classification = str(user.get("Classification", "")).strip().lower()

    if classification in ["administrator", "managing partner"]:
        logs = get_filtered_logs_as_list(all_logs=True)
    elif classification == "team leader":
        c = connect()
        team = c.execute(
            "SELECT EmployeeName FROM Employee WHERE TeamLeader = ?",
            (user["EmployeeName"],),
        ).fetchall()
        c.close()
        team_names = [t["EmployeeName"] for t in team]
        team_names.append(user["EmployeeName"])
        logs = get_filtered_logs_as_list(employees=team_names)
    else:
        logs = get_filtered_logs_as_list(employees=[user["EmployeeName"]])

    formatted_logs = []
    for l in logs:
        section = l.get("SectionName") or ""
        subsection = l.get("SubSectionName") or ""
        taskname = l.get("SubSubSectionName") or ""

        if section or subsection:
            display_task = f"{section} / {subsection} - {taskname}"
        else:
            display_task = taskname or "-"

        hours_val = l.get("Hours Logged")
        hours_display = str(hours_val) if hours_val is not None else "-"

        signout_val = l.get("Sign Out Time")
        signout_display = str(signout_val) if signout_val is not None else "-"

        formatted_logs.append({
            "Date": l.get("Date"),
            "Employee": l.get("Employee"),
            "TaskName": display_task,
            "SignIn": l.get("Sign In Time") or "-",
            "SignOut": signout_display,
            "Hours": hours_display,
            "Description": l.get("Job Description") or "-",
            "Status": "Signed Out" if signout_val else "Signed In",
        })

    return formatted_logs


@router.get("/download-timelogs")
def download_timelogs(user=Depends(current_user)):
    """Downloads the Excel file based on the user's role."""
    classification = str(user.get("Classification", "")).strip().lower()

    if classification in ["administrator", "managing partner"]:
        file_path = os.path.join("exports", "TimeLogs.xlsx")
        if not os.path.exists(file_path):
            raise HTTPException(404, "No logs exist yet.")
        return FileResponse(
            path=file_path,
            filename="All_Company_TimeLogs.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    elif classification == "team leader":
        c = connect()
        team = c.execute(
            "SELECT EmployeeName FROM Employee WHERE TeamLeader = ?",
            (user["EmployeeName"],),
        ).fetchall()
        c.close()

        team_names = [t["EmployeeName"] for t in team]
        team_names.append(user["EmployeeName"])

        try:
            data = export_user_logs_to_bytes(team_names)
            return Response(
                content=data,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="My_Team_TimeLogs.xlsx"'},
            )
        except Exception as e:
            raise HTTPException(404, str(e))

    else:
        raise HTTPException(
            403,
            "Access denied. Only Team Leaders, Administrators, and Managing Partners can download time logs.",
        )


# ============================================================
# ADMIN CRUD — TEAMS
# ============================================================

class TeamIn(BaseModel):
    TeamName: str
    LeaderEmployeeID: Optional[int] = None
    MemberIDs: List[int] = []


@router.get("/teams")
def list_teams(user=Depends(_require_admin)):
    """Return one entry per distinct TeamLeader, with member list attached."""
    c = connect()
    leaders = c.execute(
        """
        SELECT DISTINCT e.TeamLeader AS LeaderName
        FROM Employee e
        WHERE e.TeamLeader IS NOT NULL AND e.TeamLeader != ''
        ORDER BY e.TeamLeader
        """
    ).fetchall()

    out = []
    for row in leaders:
        leader_name = row["LeaderName"]
        leader = c.execute(
            "SELECT EmployeeID, EmployeeName FROM Employee WHERE EmployeeName = ?",
            (leader_name,),
        ).fetchone()
        members = c.execute(
            """
            SELECT EmployeeID, EmployeeName
            FROM Employee
            WHERE TeamLeader = ?
            ORDER BY EmployeeName
            """,
            (leader_name,),
        ).fetchall()
        out.append({
            "TeamName": f"{leader_name}'s Team",
            "LeaderID": leader["EmployeeID"] if leader else None,
            "LeaderName": leader_name,
            "MemberCount": len(members),
            "member_ids": [m["EmployeeID"] for m in members],
            "members": [dict(m) for m in members],
        })
    c.close()
    return out


@router.post("/teams")
def create_team(payload: TeamIn, user=Depends(_require_admin)):
    """Assign members to a leader. Existing TeamLeader column is rewritten."""
    if not payload.LeaderEmployeeID:
        raise HTTPException(400, "LeaderEmployeeID is required")

    c = connect()
    leader = c.execute(
        "SELECT EmployeeID, EmployeeName, Classification FROM Employee WHERE EmployeeID = ?",
        (payload.LeaderEmployeeID,),
    ).fetchone()
    if not leader:
        c.close()
        raise HTTPException(404, "Leader employee not found")

    leader_name = leader["EmployeeName"]

    # Promote leader classification if needed
    if str(leader["Classification"]).strip().lower() != "team leader":
        c.execute(
            "UPDATE Employee SET Classification = 'Team Leader' WHERE EmployeeID = ?",
            (payload.LeaderEmployeeID,),
        )

    # Clear previous members of this leader (so re-saving is idempotent)
    c.execute("UPDATE Employee SET TeamLeader = NULL WHERE TeamLeader = ?", (leader_name,))

    # Assign new members
    for emp_id in payload.MemberIDs:
        if emp_id == payload.LeaderEmployeeID:
            continue
        c.execute(
            "UPDATE Employee SET TeamLeader = ? WHERE EmployeeID = ?",
            (leader_name, emp_id),
        )

    c.commit()
    c.close()
    return {"ok": True, "TeamName": f"{leader_name}'s Team"}


@router.patch("/teams/{leader_employee_id}")
def update_team(leader_employee_id: int, payload: TeamIn, user=Depends(_require_admin)):
    return create_team(payload, user)


@router.delete("/teams/{leader_employee_id}")
def delete_team(leader_employee_id: int, user=Depends(_require_admin)):
    c = connect()
    leader = c.execute(
        "SELECT EmployeeName FROM Employee WHERE EmployeeID = ?",
        (leader_employee_id,),
    ).fetchone()
    if not leader:
        c.close()
        raise HTTPException(404, "Leader not found")
    c.execute("UPDATE Employee SET TeamLeader = NULL WHERE TeamLeader = ?", (leader["EmployeeName"],))
    c.commit()
    c.close()
    return {"ok": True}


# ============================================================
# ADMIN CRUD — EMPLOYEES
# ============================================================

class EmployeeIn(BaseModel):
    EmployeeName: str
    Username: str
    Password: Optional[str] = None
    Classification: str = "Member"
    TeamID: Optional[int] = None
    Role: str = "member"
    TeamLeader: Optional[str] = None


@router.get("/employees")
def list_employees(user=Depends(_require_admin)):
    c = connect()
    rows = c.execute(
        """
        SELECT EmployeeID, EmployeeName, Username, Classification, TeamLeader
        FROM Employee
        ORDER BY EmployeeName
        """
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


@router.post("/employees")
def create_employee(payload: EmployeeIn, user=Depends(_require_admin)):
    if not payload.Password:
        raise HTTPException(400, "Password required for new employee")

    c = connect()
    try:
        cur = c.execute(
            """
            INSERT INTO Employee (EmployeeName, Username, Password, Classification, TeamLeader)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.EmployeeName,
                payload.Username,
                payload.Password,
                payload.Classification,
                payload.TeamLeader,
            ),
        )
        emp_id = cur.lastrowid
        c.commit()
    except Exception as e:
        c.close()
        raise HTTPException(400, str(e))
    c.close()
    return {"EmployeeID": emp_id}


@router.patch("/employees/{emp_id}")
def update_employee(emp_id: int, payload: EmployeeIn, user=Depends(_require_admin)):
    c = connect()
    try:
        if payload.Password:
            c.execute(
                """
                UPDATE Employee SET EmployeeName=?, Username=?, Password=?,
                    Classification=?, TeamLeader=? WHERE EmployeeID=?
                """,
                (
                    payload.EmployeeName,
                    payload.Username,
                    payload.Password,
                    payload.Classification,
                    payload.TeamLeader,
                    emp_id,
                ),
            )
        else:
            c.execute(
                """
                UPDATE Employee SET EmployeeName=?, Username=?,
                    Classification=?, TeamLeader=? WHERE EmployeeID=?
                """,
                (
                    payload.EmployeeName,
                    payload.Username,
                    payload.Classification,
                    payload.TeamLeader,
                    emp_id,
                ),
            )
        c.commit()
    except Exception as e:
        c.close()
        raise HTTPException(400, str(e))
    c.close()
    return {"ok": True}


@router.delete("/employees/{emp_id}")
def delete_employee(emp_id: int, user=Depends(_require_admin)):
    c = connect()
    emp = c.execute(
        "SELECT EmployeeName FROM Employee WHERE EmployeeID = ?", (emp_id,)
    ).fetchone()
    if not emp:
        c.close()
        raise HTTPException(404, "Employee not found")
    c.execute("UPDATE Employee SET TeamLeader = NULL WHERE TeamLeader = ?", (emp["EmployeeName"],))
    c.execute("DELETE FROM Employee WHERE EmployeeID = ?", (emp_id,))
    c.commit()
    c.close()
    return {"ok": True}


# ============================================================
# ADMIN CRUD — CLIENTS
# ============================================================

class ClientIn(BaseModel):
    CustomerName: str
    IDHonorary: Optional[str] = None
    Contact: Optional[str] = None
    Email: Optional[str] = None
    Phone: Optional[str] = None
    Phone2: Optional[str] = None
    Address: Optional[str] = None
    Building: Optional[str] = None
    Street: Optional[str] = None
    City: Optional[str] = None
    Region: Optional[str] = None
    Country: Optional[str] = None
    Nationality: Optional[str] = None
    ClientType: Optional[str] = None
    TeamLeader: Optional[str] = None
    IndustryID: Optional[int] = None


@router.get("/clients")
def list_clients(user=Depends(_require_admin)):
    c = connect()
    try:
        rows = c.execute("""
            SELECT c.ClientID, c.CustomerName, c.IDHonorary, c.Contact,
                   c.Email, c.Phone, c.Phone2, c.Address, c.Building, c.Street,
                   c.City, c.Region, c.Country, c.Nationality, c.ClientType,
                   c.TeamLeader, c.IndustryID,
                   i.Industry AS IndustryName,
                   i.ClientType AS IndustryGroup
            FROM Client c
            LEFT JOIN Industry i ON i.IndustryID = c.IndustryID
            ORDER BY c.CustomerName
        """).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception:
        rows = c.execute("""
            SELECT c.ClientID, c.CustomerName, c.IDHonorary, c.Contact,
                   c.Email, c.Phone, NULL AS Phone2, c.Address,
                   NULL AS Building, NULL AS Street, NULL AS City,
                   NULL AS Region, NULL AS Country, NULL AS Nationality,
                   NULL AS ClientType, NULL AS TeamLeader, c.IndustryID,
                   i.Industry AS IndustryName, i.ClientType AS IndustryGroup
            FROM Client c
            LEFT JOIN Industry i ON i.IndustryID = c.IndustryID
            ORDER BY c.CustomerName
        """).fetchall()
        c.close()
        return [dict(r) for r in rows]


@router.post("/clients")
def create_client(payload: ClientIn, user=Depends(_require_admin)):
    c = connect()
    try:
        cur = c.execute("""
            INSERT INTO Client
              (CustomerName, IDHonorary, Contact, Email, Phone, Phone2,
               Address, Building, Street, City, Region, Country, Nationality,
               ClientType, TeamLeader, IndustryID)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            payload.CustomerName, payload.IDHonorary, payload.Contact,
            payload.Email, payload.Phone, payload.Phone2,
            payload.Address, payload.Building, payload.Street, payload.City,
            payload.Region, payload.Country, payload.Nationality,
            payload.ClientType, payload.TeamLeader, payload.IndustryID,
        ))
        cid = cur.lastrowid
        c.commit()
    except Exception as e:
        c.close()
        raise HTTPException(400, str(e))
    c.close()
    return {"ClientID": cid}


@router.patch("/clients/{client_id}")
def update_client(client_id: int, payload: ClientIn, user=Depends(_require_admin)):
    c = connect()
    try:
        c.execute("""
            UPDATE Client SET
              CustomerName=?, IDHonorary=?, Contact=?, Email=?, Phone=?,
              Phone2=?, Address=?, Building=?, Street=?, City=?, Region=?,
              Country=?, Nationality=?, ClientType=?, TeamLeader=?, IndustryID=?
            WHERE ClientID=?
        """, (
            payload.CustomerName, payload.IDHonorary, payload.Contact,
            payload.Email, payload.Phone, payload.Phone2,
            payload.Address, payload.Building, payload.Street, payload.City,
            payload.Region, payload.Country, payload.Nationality,
            payload.ClientType, payload.TeamLeader, payload.IndustryID,
            client_id,
        ))
        c.commit()
    except Exception as e:
        c.close()
        raise HTTPException(400, str(e))
    c.close()
    return {"ok": True}


@router.delete("/clients/{client_id}")
def delete_client(client_id: int, user=Depends(_require_admin)):
    c = connect()
    try:
        c.execute("DELETE FROM Client WHERE ClientID = ?", (client_id,))
        c.commit()
    except Exception as e:
        c.close()
        raise HTTPException(400, str(e))
    c.close()
    return {"ok": True}


# ============================================================
# ADMIN CRUD — SERVICES
# ============================================================

class ServiceIn(BaseModel):
    ServiceName: str
    Letter: Optional[str] = ""


@router.get("/services")
def list_services(user=Depends(_require_admin)):
    c = connect()
    rows = c.execute("""
        SELECT ServiceID, ServiceName, COALESCE(Letter, '') AS Letter
        FROM Service
        ORDER BY ServiceName
    """).fetchall()
    c.close()
    return [dict(r) for r in rows]


@router.post("/services")
def create_service(payload: ServiceIn, user=Depends(_require_admin)):
    c = connect()
    try:
        cur = c.execute(
            "INSERT INTO Service (TenantID, ServiceName, Letter) VALUES (1, ?, ?)",
            (payload.ServiceName.strip(), payload.Letter or ""),
        )
        sid = cur.lastrowid
        c.commit()
    except Exception as e:
        c.close()
        raise HTTPException(400, str(e))
    c.close()
    return {"ServiceID": sid}


@router.patch("/services/{service_id}")
def update_service(service_id: int, payload: ServiceIn, user=Depends(_require_admin)):
    c = connect()
    try:
        c.execute(
            "UPDATE Service SET ServiceName = ?, Letter = ? WHERE ServiceID = ?",
            (payload.ServiceName.strip(), payload.Letter or "", service_id),
        )
        c.commit()
    except Exception as e:
        c.close()
        raise HTTPException(400, str(e))
    c.close()
    return {"ok": True}


@router.delete("/services/{service_id}")
def delete_service(service_id: int, user=Depends(_require_admin)):
    c = connect()
    used = c.execute(
        "SELECT COUNT(*) AS n FROM Mission WHERE ServiceID = ?",
        (service_id,),
    ).fetchone()
    if used and used["n"] > 0:
        c.close()
        raise HTTPException(400, "Cannot delete: this service is used by existing missions.")
    c.execute("DELETE FROM Service WHERE ServiceID = ?", (service_id,))
    c.commit()
    c.close()
    return {"ok": True}


# ============================================================
# ADMIN CRUD — INDUSTRIES
# ============================================================

class IndustryIn(BaseModel):
    ClientType: str
    Industry: str


@router.get("/industries")
def list_industries(user=Depends(_require_admin)):
    c = connect()
    rows = c.execute("""
        SELECT IndustryID, ClientType, Industry
        FROM Industry
        ORDER BY ClientType, Industry
    """).fetchall()
    c.close()
    return [dict(r) for r in rows]


@router.post("/industries")
def create_industry(payload: IndustryIn, user=Depends(_require_admin)):
    c = connect()
    try:
        cur = c.execute(
            "INSERT INTO Industry (ClientType, Industry) VALUES (?, ?)",
            (payload.ClientType.strip(), payload.Industry.strip()),
        )
        iid = cur.lastrowid
        c.commit()
    except Exception as e:
        c.close()
        raise HTTPException(400, str(e))
    c.close()
    return {"IndustryID": iid}


@router.patch("/industries/{industry_id}")
def update_industry(industry_id: int, payload: IndustryIn, user=Depends(_require_admin)):
    c = connect()
    try:
        c.execute(
            "UPDATE Industry SET ClientType = ?, Industry = ? WHERE IndustryID = ?",
            (payload.ClientType.strip(), payload.Industry.strip(), industry_id),
        )
        c.commit()
    except Exception as e:
        c.close()
        raise HTTPException(400, str(e))
    c.close()
    return {"ok": True}


@router.delete("/industries/{industry_id}")
def delete_industry(industry_id: int, user=Depends(_require_admin)):
    c = connect()
    used = c.execute(
        "SELECT COUNT(*) AS n FROM Client WHERE IndustryID = ?",
        (industry_id,),
    ).fetchone()
    if used and used["n"] > 0:
        c.close()
        raise HTTPException(400, "Cannot delete: this industry is assigned to existing clients.")
    c.execute("DELETE FROM Industry WHERE IndustryID = ?", (industry_id,))
    c.commit()
    c.close()
    return {"ok": True}