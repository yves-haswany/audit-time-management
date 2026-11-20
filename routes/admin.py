
"""Admin endpoints — tenant-isolated missions, time logs, and admin CRUD."""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.dependencies import current_user
from core.database import connect_tenant
from core.security import hash_password

from scripts.export_mission import export_mission_to_bytes
from scripts.export_timelog import (
    get_filtered_logs_as_list,
    export_user_logs_to_bytes,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ============================================================
# HELPERS
# ============================================================

def _require_admin(user=Depends(current_user)):
    """Allow company administrators only. Super Admin is separate."""

    role = str(user.get("Classification") or "").strip().lower()
    tenant_id = user.get("TenantID")

    if role not in ("administrator", "managing partner"):
        raise HTTPException(
            status_code=403,
            detail="Administrator or Managing Partner only."
        )

    if tenant_id is None or int(tenant_id) <= 0:
        raise HTTPException(
            status_code=403,
            detail="A valid company account is required."
        )

    return user

def _tenant_id(user) -> int:
    tenant_id = user.get("TenantID")

    if tenant_id is None or int(tenant_id) <= 0:
        raise HTTPException(403, "Invalid company account.")

    return int(tenant_id)

def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None

def _get_employee(c, employee_id: int, tenant_id: int):
    return c.execute(
        """
        SELECT EmployeeID, EmployeeName, Username, LoginCode,
               Classification, TeamLeader, IsActive
        FROM Employee
        WHERE EmployeeID = ?
          AND TenantID = ?
        """,
        (employee_id, tenant_id)
    ).fetchone()

def _validate_team_leader(c, leader_name, tenant_id):
    if not leader_name:
        return

    leader = c.execute(
        """
        SELECT EmployeeID
        FROM Employee
        WHERE EmployeeName = ?
          AND TenantID = ?
          AND LOWER(COALESCE(Classification, '')) = 'team leader'
        """,
        (leader_name, tenant_id)
    ).fetchone()

    if not leader:
        raise HTTPException(
            400,
            "The selected Team Leader does not belong to your company "
            "or is not classified as a Team Leader."
        )

def _validate_industry(c, industry_id, tenant_id):
    if industry_id is None:
        return

    industry = c.execute(
        """
        SELECT IndustryID
        FROM Industry
        WHERE IndustryID = ?
          AND TenantID = ?
        """,
        (industry_id, tenant_id)
    ).fetchone()

    if not industry:
        raise HTTPException(
            400,
            "The selected industry does not belong to your company."
        )

# ============================================================
# MISSIONS
# ============================================================

@router.get("/missions")
def all_missions(user=Depends(current_user)):
    """Return missions belonging only to the current tenant."""

    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
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
                COUNT(t.TaskID) AS TasksTotal,
                ROUND(COALESCE(SUM(t.AllocatedHours), 0), 1)
                    AS AllocatedHours
            FROM Mission m
            LEFT JOIN MissionTask t
                ON t.MissionID = m.MissionID
            LEFT JOIN Service s
                ON s.ServiceID = m.ServiceID
               AND s.TenantID = m.TenantID
            WHERE m.TenantID = ?
            GROUP BY
                m.MissionID,
                m.IDHonorary,
                m.CustomerName,
                s.ServiceName,
                m.FiscalYear,
                m.WindowStart,
                m.WindowEnd
            ORDER BY m.WindowStart
            """,
            (tenant_id,)
        ).fetchall()

        today = date.today().isoformat()
        output = []

        for row in rows:
            item = dict(row)
            start = item.get("WindowStart")
            end = item.get("WindowEnd")

            if start and today < start:
                item["WindowStatus"] = "not_started"
            elif end and today > end:
                item["WindowStatus"] = "overdue"
            else:
                item["WindowStatus"] = "open"

            output.append(item)

        return output

    finally:
        c.close()

@router.get("/export/{mission_id}")
def export_mission(mission_id: int, user=Depends(current_user)):
    """Export a mission only if it belongs to the current tenant."""

    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        mission = c.execute(
            """
            SELECT MissionID, CustomerName, IDHonorary
            FROM Mission
            WHERE MissionID = ?
              AND TenantID = ?
            """,
            (mission_id, tenant_id)
        ).fetchone()

    finally:
        c.close()

    if not mission:
        raise HTTPException(404, "Mission not found.")

    try:
        # export_mission_to_bytes must also enforce TenantID internally.
        data = export_mission_to_bytes(
            mission_id,
            tenant_id=tenant_id
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except TypeError:
        # Do not silently fall back to an unscoped export.
        raise HTTPException(
            500,
            "The mission export script must be updated to accept tenant_id."
        )

    safe_customer = "".join(
        ch if ch.isalnum() else "_"
        for ch in (mission["CustomerName"] or "Customer")
    ).strip("_")

    filename = (
        f"{safe_customer}_{mission['IDHonorary'] or mission_id}_mission.xlsx"
    )

    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )

# ============================================================
# TIME LOGS
# ============================================================

def _get_team_employee_names(c, user, tenant_id):
    """Get a Team Leader's employees from the same tenant only."""

    rows = c.execute(
        """
        SELECT EmployeeName
        FROM Employee
        WHERE TenantID = ?
          AND TeamLeader = ?
          AND IsActive = 1
        ORDER BY EmployeeName
        """,
        (tenant_id, user["EmployeeName"])
    ).fetchall()

    names = [row["EmployeeName"] for row in rows]
    names.append(user["EmployeeName"])

    return list(dict.fromkeys(names))

def _get_logs_for_user(user, tenant_id):
    classification = str(
        user.get("Classification") or ""
    ).strip().lower()

    if classification in ("administrator", "managing partner"):
        return get_filtered_logs_as_list(
            all_logs=True,
            tenant_id=tenant_id
        )

    if classification == "team leader":
        c = connect_tenant(tenant_id)
        try:
            employees = _get_team_employee_names(
                c, user, tenant_id
            )
        finally:
            c.close()

        return get_filtered_logs_as_list(
            employees=employees,
            tenant_id=tenant_id
        )

    return get_filtered_logs_as_list(
        employees=[user["EmployeeName"]],
        tenant_id=tenant_id
    )

@router.get("/time-logs")
def view_time_logs(user=Depends(current_user)):
    """Return time logs restricted by tenant and user role."""

    tenant_id = _tenant_id(user)

    try:
        logs = _get_logs_for_user(user, tenant_id)
    except TypeError:
        raise HTTPException(
            500,
            "The time-log script must be updated to accept tenant_id."
        )

    formatted_logs = []

    for log in logs:
        section = log.get("SectionName") or ""
        subsection = log.get("SubSectionName") or ""
        taskname = log.get("SubSubSectionName") or ""

        if section or subsection:
            display_task = f"{section} / {subsection} - {taskname}"
        else:
            display_task = taskname or "-"

        signout = log.get("Sign Out Time")

        formatted_logs.append({
            "Date": log.get("Date"),
            "Employee": log.get("Employee"),
            "TaskName": display_task,
            "SignIn": log.get("Sign In Time") or "-",
            "SignOut": signout or "-",
            "Hours": (
                str(log.get("Hours Logged"))
                if log.get("Hours Logged") is not None
                else "-"
            ),
            "Description": log.get("Job Description") or "-",
            "Status": "Signed Out" if signout else "Signed In",
        })

    return formatted_logs

@router.get("/download-timelogs")
def download_timelogs(user=Depends(current_user)):
    """Download only the current tenant's time logs."""

    tenant_id = _tenant_id(user)
    classification = str(
        user.get("Classification") or ""
    ).strip().lower()

    if classification not in (
        "administrator",
        "managing partner",
        "team leader"
    ):
        raise HTTPException(
            403,
            "Only Team Leaders, Administrators, and Managing Partners "
            "can download time logs."
        )

    c = connect_tenant(tenant_id)

    try:
        if classification in ("administrator", "managing partner"):
            employees = [
                row["EmployeeName"]
                for row in c.execute(
                    """
                    SELECT EmployeeName
                    FROM Employee
                    WHERE TenantID = ?
                     
                    ORDER BY EmployeeName
                    """,
                    (tenant_id,)
                ).fetchall()
            ]
            filename = "Company_TimeLogs.xlsx"

        else:
            employees = _get_team_employee_names(
                c, user, tenant_id
            )
            filename = "My_Team_TimeLogs.xlsx"

    finally:
        c.close()

    try:
        data = export_user_logs_to_bytes(
            employees,
            tenant_id=tenant_id
        )
    except TypeError:
        raise HTTPException(
            500,
            "The time-log export script must be updated to accept tenant_id."
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )

# ============================================================
# TEAMS
# ============================================================

class TeamIn(BaseModel):
    TeamName: Optional[str] = None
    LeaderEmployeeID: Optional[int] = None
    MemberIDs: List[int] = Field(default_factory=list)

def _save_team(payload: TeamIn, user):
    tenant_id = _tenant_id(user)

    if not payload.LeaderEmployeeID:
        raise HTTPException(400, "LeaderEmployeeID is required.")

    member_ids = list(dict.fromkeys(payload.MemberIDs))

    if payload.LeaderEmployeeID in member_ids:
        member_ids.remove(payload.LeaderEmployeeID)

    c = connect_tenant(tenant_id)

    try:
        leader = _get_employee(
            c,
            payload.LeaderEmployeeID,
            tenant_id
        )

        if not leader:
            raise HTTPException(404, "Leader employee not found.")

        # Every member must belong to this tenant.
        for employee_id in member_ids:
            member = _get_employee(c, employee_id, tenant_id)

            if not member:
                raise HTTPException(
                    400,
                    f"Employee {employee_id} does not belong to your company."
                )

        leader_name = leader["EmployeeName"]

        # Prevent a leader from being assigned as a member elsewhere.
        c.execute(
            """
            UPDATE Employee
            SET Classification = 'Team Leader',
                TeamLeader = NULL
            WHERE EmployeeID = ?
              AND TenantID = ?
            """,
            (payload.LeaderEmployeeID, tenant_id)
        )

        # Clear this leader's previous members only within this tenant.
        c.execute(
            """
            UPDATE Employee
            SET TeamLeader = NULL
            WHERE TenantID = ?
              AND TeamLeader = ?
            """,
            (tenant_id, leader_name)
        )

        # Assign the new members.
        for employee_id in member_ids:
            c.execute(
                """
                UPDATE Employee
                SET TeamLeader = ?
                WHERE EmployeeID = ?
                  AND TenantID = ?
                """,
                (leader_name, employee_id, tenant_id)
            )

        c.commit()

        return {
            "ok": True,
            "TeamName": f"{leader_name}'s Team"
        }

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.get("/teams")
def list_teams(user=Depends(_require_admin)):
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        leaders = c.execute(
            """
            SELECT EmployeeID, EmployeeName
            FROM Employee
            WHERE TenantID = ?
              AND LOWER(COALESCE(Classification, '')) = 'team leader'
            ORDER BY EmployeeName
            """,
            (tenant_id,)
        ).fetchall()

        output = []

        for leader in leaders:
            members = c.execute(
                """
                SELECT EmployeeID, EmployeeName
                FROM Employee
                WHERE TenantID = ?
                  AND TeamLeader = ?
                ORDER BY EmployeeName
                """,
                (tenant_id, leader["EmployeeName"])
            ).fetchall()

            output.append({
                "TeamName": f"{leader['EmployeeName']}'s Team",
                "LeaderID": leader["EmployeeID"],
                "LeaderName": leader["EmployeeName"],
                "MemberCount": len(members),
                "member_ids": [m["EmployeeID"] for m in members],
                "members": [dict(m) for m in members]
            })

        return output

    finally:
        c.close()

@router.post("/teams")
def create_team(payload: TeamIn, user=Depends(_require_admin)):
    return _save_team(payload, user)

@router.patch("/teams/{leader_employee_id}")
def update_team(
    leader_employee_id: int,
    payload: TeamIn,
    user=Depends(_require_admin)
):
    if payload.LeaderEmployeeID != leader_employee_id:
        raise HTTPException(
            400,
            "The URL leader ID and payload LeaderEmployeeID must match."
        )

    return _save_team(payload, user)

@router.delete("/teams/{leader_employee_id}")
def delete_team(
    leader_employee_id: int,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        leader = _get_employee(
            c,
            leader_employee_id,
            tenant_id
        )

        if not leader:
            raise HTTPException(404, "Leader not found.")

        c.execute(
            """
            UPDATE Employee
            SET TeamLeader = NULL
            WHERE TenantID = ?
              AND TeamLeader = ?
            """,
            (tenant_id, leader["EmployeeName"])
        )

        c.execute(
            """
            UPDATE Employee
            SET Classification = 'Member'
            WHERE EmployeeID = ?
              AND TenantID = ?
            """,
            (leader_employee_id, tenant_id)
        )

        c.commit()
        return {"ok": True}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

# ============================================================
# EMPLOYEES
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
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        rows = c.execute(
            """
            SELECT
                EmployeeID,
                EmployeeName,
                LoginCode,
                Username,
                Classification,
                TeamLeader,
                IsActive,
                IsTeamLead
            FROM Employee
            WHERE TenantID = ?
            ORDER BY EmployeeName
            """,
            (tenant_id,)
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        c.close()

@router.post("/employees")
def create_employee(
    payload: EmployeeIn,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)

    employee_name = _clean(payload.EmployeeName)
    username = _clean(payload.Username)
    team_leader = _clean(payload.TeamLeader)

    if not employee_name or not username:
        raise HTTPException(
            400,
            "EmployeeName and Username are required."
        )

    if not payload.Password:
        raise HTTPException(
            400,
            "Password is required for a new employee."
        )

    c = connect_tenant(tenant_id)

    try:
        _validate_team_leader(c, team_leader, tenant_id)

        password_hash = hash_password(payload.Password)

        cur = c.execute(
            """
            INSERT INTO Employee (
                TenantID,
                EmployeeName,
                LoginCode,
                Username,
                PasswordHash,
                Classification,
                TeamLeader,
                IsActive
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                tenant_id,
                employee_name,
                username,
                username,
                password_hash,
                payload.Classification.strip() or "Member",
                team_leader
            )
        )

        employee_id = cur.lastrowid
        c.commit()

        return {"EmployeeID": employee_id}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.patch("/employees/{emp_id}")
def update_employee(
    emp_id: int,
    payload: EmployeeIn,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)

    employee_name = _clean(payload.EmployeeName)
    username = _clean(payload.Username)
    team_leader = _clean(payload.TeamLeader)

    if not employee_name or not username:
        raise HTTPException(
            400,
            "EmployeeName and Username are required."
        )

    c = connect_tenant(tenant_id)

    try:
        existing = _get_employee(c, emp_id, tenant_id)

        if not existing:
            raise HTTPException(404, "Employee not found.")

        _validate_team_leader(c, team_leader, tenant_id)

        if team_leader == employee_name:
            raise HTTPException(
                400,
                "An employee cannot be their own Team Leader."
            )

        classification = payload.Classification.strip() or "Member"

        if payload.Password:
            c.execute(
                """
                UPDATE Employee
                SET EmployeeName = ?,
                    LoginCode = ?,
                    Username = ?,
                    PasswordHash = ?,
                    Classification = ?,
                    TeamLeader = ?
                WHERE EmployeeID = ?
                  AND TenantID = ?
                """,
                (
                    employee_name,
                    username,
                    username,
                    hash_password(payload.Password),
                    classification,
                    team_leader,
                    emp_id,
                    tenant_id
                )
            )
        else:
            c.execute(
                """
                UPDATE Employee
                SET EmployeeName = ?,
                    LoginCode = ?,
                    Username = ?,
                    Classification = ?,
                    TeamLeader = ?
                WHERE EmployeeID = ?
                  AND TenantID = ?
                """,
                (
                    employee_name,
                    username,
                    username,
                    classification,
                    team_leader,
                    emp_id,
                    tenant_id
                )
            )

        # If the employee is no longer a Team Leader, detach their members.
        if classification.lower() != "team leader":
            c.execute(
                """
                UPDATE Employee
                SET TeamLeader = NULL
                WHERE TenantID = ?
                  AND TeamLeader = ?
                """,
                (tenant_id, existing["EmployeeName"])
            )

        c.commit()
        return {"ok": True}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.delete("/employees/{emp_id}")
def delete_employee(
    emp_id: int,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        employee = _get_employee(c, emp_id, tenant_id)

        if not employee:
            raise HTTPException(404, "Employee not found.")

        # Do not allow an administrator to delete their own account here.
        if employee["EmployeeID"] == user["EmployeeID"]:
            raise HTTPException(
                400,
                "You cannot delete your own account."
            )

        # Detach employees who reported to this Team Leader.
        c.execute(
            """
            UPDATE Employee
            SET TeamLeader = NULL
            WHERE TenantID = ?
              AND TeamLeader = ?
            """,
            (tenant_id, employee["EmployeeName"])
        )

        c.execute(
            """
            DELETE FROM Employee
            WHERE EmployeeID = ?
              AND TenantID = ?
            """,
            (emp_id, tenant_id)
        )

        c.commit()
        return {"ok": True}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

# ============================================================
# CLIENTS
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
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        rows = c.execute(
            """
            SELECT
                cl.ClientID,
                cl.CustomerName,
                cl.IDHonorary,
                cl.Contact,
                cl.Email,
                cl.Phone,
                cl.Phone2,
                cl.Address,
                cl.Building,
                cl.Street,
                cl.City,
                cl.Region,
                cl.Country,
                cl.Nationality,
                cl.ClientType,
                cl.TeamLeader,
                cl.IndustryID,
                i.Industry AS IndustryName,
                i.ClientType AS IndustryGroup
            FROM Client cl
            LEFT JOIN Industry i
                ON i.IndustryID = cl.IndustryID
               AND i.TenantID = cl.TenantID
            WHERE cl.TenantID = ?
            ORDER BY cl.CustomerName
            """,
            (tenant_id,)
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        c.close()

@router.post("/clients")
def create_client(
    payload: ClientIn,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    customer_name = _clean(payload.CustomerName)

    if not customer_name:
        raise HTTPException(400, "CustomerName is required.")

    c = connect_tenant(tenant_id)

    try:
        _validate_industry(c, payload.IndustryID, tenant_id)
        _validate_team_leader(c, _clean(payload.TeamLeader), tenant_id)

        cur = c.execute(
            """
            INSERT INTO Client (
                TenantID,
                CustomerName,
                IDHonorary,
                Contact,
                Email,
                Phone,
                Phone2,
                Address,
                Building,
                Street,
                City,
                Region,
                Country,
                Nationality,
                ClientType,
                TeamLeader,
                IndustryID
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                customer_name,
                payload.IDHonorary,
                payload.Contact,
                payload.Email,
                payload.Phone,
                payload.Phone2,
                payload.Address,
                payload.Building,
                payload.Street,
                payload.City,
                payload.Region,
                payload.Country,
                payload.Nationality,
                payload.ClientType,
                _clean(payload.TeamLeader),
                payload.IndustryID
            )
        )

        client_id = cur.lastrowid
        c.commit()

        return {"ClientID": client_id}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.patch("/clients/{client_id}")
def update_client(
    client_id: int,
    payload: ClientIn,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    customer_name = _clean(payload.CustomerName)

    if not customer_name:
        raise HTTPException(400, "CustomerName is required.")

    c = connect_tenant(tenant_id)

    try:
        existing = c.execute(
            """
            SELECT ClientID
            FROM Client
            WHERE ClientID = ?
              AND TenantID = ?
            """,
            (client_id, tenant_id)
        ).fetchone()

        if not existing:
            raise HTTPException(404, "Client not found.")

        _validate_industry(c, payload.IndustryID, tenant_id)
        _validate_team_leader(c, _clean(payload.TeamLeader), tenant_id)

        c.execute(
            """
            UPDATE Client
            SET CustomerName = ?,
                IDHonorary = ?,
                Contact = ?,
                Email = ?,
                Phone = ?,
                Phone2 = ?,
                Address = ?,
                Building = ?,
                Street = ?,
                City = ?,
                Region = ?,
                Country = ?,
                Nationality = ?,
                ClientType = ?,
                TeamLeader = ?,
                IndustryID = ?
            WHERE ClientID = ?
              AND TenantID = ?
            """,
            (
                customer_name,
                payload.IDHonorary,
                payload.Contact,
                payload.Email,
                payload.Phone,
                payload.Phone2,
                payload.Address,
                payload.Building,
                payload.Street,
                payload.City,
                payload.Region,
                payload.Country,
                payload.Nationality,
                payload.ClientType,
                _clean(payload.TeamLeader),
                payload.IndustryID,
                client_id,
                tenant_id
            )
        )

        c.commit()
        return {"ok": True}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.delete("/clients/{client_id}")
def delete_client(
    client_id: int,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        cursor = c.execute(
            """
            DELETE FROM Client
            WHERE ClientID = ?
              AND TenantID = ?
            """,
            (client_id, tenant_id)
        )

        if cursor.rowcount == 0:
            raise HTTPException(404, "Client not found.")

        c.commit()
        return {"ok": True}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

# ============================================================
# SERVICES
# ============================================================

class ServiceIn(BaseModel):
    ServiceName: str
    Letter: Optional[str] = ""

@router.get("/services")
def list_services(user=Depends(_require_admin)):
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        rows = c.execute(
            """
            SELECT ServiceID, ServiceName, COALESCE(Letter, '') AS Letter
            FROM Service
            WHERE TenantID = ?
            ORDER BY ServiceName
            """,
            (tenant_id,)
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        c.close()

@router.post("/services")
def create_service(
    payload: ServiceIn,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    service_name = _clean(payload.ServiceName)

    if not service_name:
        raise HTTPException(400, "ServiceName is required.")

    c = connect_tenant(tenant_id)

    try:
        cur = c.execute(
            """
            INSERT INTO Service (TenantID, ServiceName, Letter)
            VALUES (?, ?, ?)
            """,
            (tenant_id, service_name, payload.Letter or "")
        )

        service_id = cur.lastrowid
        c.commit()

        return {"ServiceID": service_id}

    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.patch("/services/{service_id}")
def update_service(
    service_id: int,
    payload: ServiceIn,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    service_name = _clean(payload.ServiceName)

    if not service_name:
        raise HTTPException(400, "ServiceName is required.")

    c = connect_tenant(tenant_id)

    try:
        cursor = c.execute(
            """
            UPDATE Service
            SET ServiceName = ?,
                Letter = ?
            WHERE ServiceID = ?
              AND TenantID = ?
            """,
            (
                service_name,
                payload.Letter or "",
                service_id,
                tenant_id
            )
        )

        if cursor.rowcount == 0:
            raise HTTPException(404, "Service not found.")

        c.commit()
        return {"ok": True}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.delete("/services/{service_id}")
def delete_service(
    service_id: int,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        service = c.execute(
            """
            SELECT ServiceID
            FROM Service
            WHERE ServiceID = ?
              AND TenantID = ?
            """,
            (service_id, tenant_id)
        ).fetchone()

        if not service:
            raise HTTPException(404, "Service not found.")

        used = c.execute(
            """
            SELECT COUNT(*) AS n
            FROM Mission
            WHERE ServiceID = ?
              AND TenantID = ?
            """,
            (service_id, tenant_id)
        ).fetchone()

        if used and used["n"] > 0:
            raise HTTPException(
                400,
                "Cannot delete: this service is used by existing missions."
            )

        c.execute(
            """
            DELETE FROM Service
            WHERE ServiceID = ?
              AND TenantID = ?
            """,
            (service_id, tenant_id)
        )

        c.commit()
        return {"ok": True}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

# ============================================================
# INDUSTRIES — TENANT-SPECIFIC
# ============================================================

class IndustryIn(BaseModel):
    ClientType: str
    Industry: str

@router.get("/industries")
def list_industries(user=Depends(_require_admin)):
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        rows = c.execute(
            """
            SELECT IndustryID, ClientType, Industry
            FROM Industry
            WHERE TenantID = ?
            ORDER BY ClientType, Industry
            """,
            (tenant_id,)
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        c.close()

@router.post("/industries")
def create_industry(
    payload: IndustryIn,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    client_type = _clean(payload.ClientType)
    industry = _clean(payload.Industry)

    if not client_type or not industry:
        raise HTTPException(
            400,
            "ClientType and Industry are required."
        )

    c = connect_tenant(tenant_id)

    try:
        existing = c.execute(
            """
            SELECT IndustryID
            FROM Industry
            WHERE TenantID = ?
              AND ClientType = ?
              AND Industry = ?
            """,
            (tenant_id, client_type, industry)
        ).fetchone()

        if existing:
            raise HTTPException(
                409,
                "This industry already exists in your company."
            )

        cur = c.execute(
            """
            INSERT INTO Industry (TenantID, ClientType, Industry)
            VALUES (?, ?, ?)
            """,
            (tenant_id, client_type, industry)
        )

        industry_id = cur.lastrowid
        c.commit()

        return {"IndustryID": industry_id}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.patch("/industries/{industry_id}")
def update_industry(
    industry_id: int,
    payload: IndustryIn,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    client_type = _clean(payload.ClientType)
    industry = _clean(payload.Industry)

    if not client_type or not industry:
        raise HTTPException(
            400,
            "ClientType and Industry are required."
        )

    c = connect_tenant(tenant_id)

    try:
        existing = c.execute(
            """
            SELECT IndustryID
            FROM Industry
            WHERE IndustryID = ?
              AND TenantID = ?
            """,
            (industry_id, tenant_id)
        ).fetchone()

        if not existing:
            raise HTTPException(404, "Industry not found.")

        duplicate = c.execute(
            """
            SELECT IndustryID
            FROM Industry
            WHERE TenantID = ?
              AND ClientType = ?
              AND Industry = ?
              AND IndustryID != ?
            """,
            (tenant_id, client_type, industry, industry_id)
        ).fetchone()

        if duplicate:
            raise HTTPException(
                409,
                "Another industry with these values already exists."
            )

        c.execute(
            """
            UPDATE Industry
            SET ClientType = ?,
                Industry = ?
            WHERE IndustryID = ?
              AND TenantID = ?
            """,
            (client_type, industry, industry_id, tenant_id)
        )

        c.commit()
        return {"ok": True}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.delete("/industries/{industry_id}")
def delete_industry(
    industry_id: int,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        existing = c.execute(
            """
            SELECT IndustryID
            FROM Industry
            WHERE IndustryID = ?
              AND TenantID = ?
            """,
            (industry_id, tenant_id)
        ).fetchone()

        if not existing:
            raise HTTPException(404, "Industry not found.")

        used = c.execute(
            """
            SELECT COUNT(*) AS n
            FROM Client
            WHERE IndustryID = ?
              AND TenantID = ?
            """,
            (industry_id, tenant_id)
        ).fetchone()

        if used and used["n"] > 0:
            raise HTTPException(
                400,
                "Cannot delete: this industry is assigned to existing clients."
            )

        c.execute(
            """
            DELETE FROM Industry
            WHERE IndustryID = ?
              AND TenantID = ?
            """,
            (industry_id, tenant_id)
        )

        c.commit()
        return {"ok": True}

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

# ============================================================
# SECTION CATALOG — TENANT-SPECIFIC
# ============================================================

class SectionIn(BaseModel):
    Industry: str
    Service: str
    SectionName: Optional[str] = None
    SubSectionName: Optional[str] = None
    SubSubSectionName: Optional[str] = None
    Remarks: Optional[str] = None
    DefaultHours: float = 1.0

def _section_values(data):
    industry = _clean(data.Industry)
    service = _clean(data.Service)
    section = _clean(data.SectionName)
    subsection = _clean(data.SubSectionName)
    subsubsection = _clean(data.SubSubSectionName)
    remarks = _clean(data.Remarks)

    if not industry or not service:
        raise HTTPException(
            400,
            "Industry and Service are required."
        )

    if not (section or subsection or subsubsection):
        raise HTTPException(
            400,
            "At least one section name is required."
        )

    if data.DefaultHours < 0:
        raise HTTPException(
            400,
            "DefaultHours cannot be negative."
        )

    return (
        industry,
        service,
        section,
        subsection,
        subsubsection,
        remarks,
        data.DefaultHours
    )

def _validate_section_catalog_values(c, tenant_id, values):
    industry, service = values[0], values[1]

    industry_exists = c.execute(
        """
        SELECT IndustryID
        FROM Industry
        WHERE TenantID = ?
          AND Industry = ?
        LIMIT 1
        """,
        (tenant_id, industry)
    ).fetchone()

    if not industry_exists:
        raise HTTPException(
            400,
            "The selected industry does not belong to your company."
        )

    service_exists = c.execute(
        """
        SELECT ServiceID
        FROM Service
        WHERE TenantID = ?
          AND ServiceName = ?
        LIMIT 1
        """,
        (tenant_id, service)
    ).fetchone()

    if not service_exists:
        raise HTTPException(
            400,
            "The selected service does not belong to your company."
        )

def _check_section_duplicate(
    c,
    tenant_id,
    values,
    exclude_id=None
):
    sql = """
        SELECT SectionID
        FROM SectionCatalog
        WHERE TenantID = ?
          AND Industry = ?
          AND Service = ?
          AND COALESCE(SectionName, '') = COALESCE(?, '')
          AND COALESCE(SubSectionName, '') = COALESCE(?, '')
          AND COALESCE(SubSubSectionName, '') = COALESCE(?, '')
          AND IsDeleted = 0
    """

    params = [tenant_id, *values[:5]]

    if exclude_id is not None:
        sql += " AND SectionID != ?"
        params.append(exclude_id)

    return c.execute(sql, params).fetchone()

@router.get("/sections")
def get_admin_sections(
    industry: Optional[str] = None,
    service: Optional[str] = None,
    search: Optional[str] = None,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        sql = """
            SELECT
                SectionID,
                Industry,
                Service,
                SectionName,
                SubSectionName,
                SubSubSectionName,
                Remarks,
                DefaultHours
            FROM SectionCatalog
            WHERE TenantID = ?
              AND IsDeleted = 0
        """

        params = [tenant_id]

        if industry:
            sql += " AND Industry = ?"
            params.append(industry)

        if service:
            sql += " AND Service = ?"
            params.append(service)

        if search:
            term = f"%{search.strip()}%"
            sql += """
                AND (
                    Industry LIKE ?
                    OR Service LIKE ?
                    OR SectionName LIKE ?
                    OR SubSectionName LIKE ?
                    OR SubSubSectionName LIKE ?
                    OR Remarks LIKE ?
                )
            """
            params.extend([term] * 6)

        sql += """
            ORDER BY Industry, Service,
                     SectionName, SubSectionName,
                     SubSubSectionName
        """

        rows = c.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    finally:
        c.close()

@router.post("/sections")
def create_admin_section(
    data: SectionIn,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    values = _section_values(data)
    c = connect_tenant(tenant_id)

    try:
        _validate_section_catalog_values(c, tenant_id, values)

        if _check_section_duplicate(c, tenant_id, values):
            raise HTTPException(
                409,
                "This Section Catalog entry already exists."
            )

        cur = c.execute(
            """
            INSERT INTO SectionCatalog (
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (tenant_id, *values)
        )

        section_id = cur.lastrowid
        c.commit()

        return {
            "ok": True,
            "SectionID": section_id,
            "message": "Section created successfully."
        }

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.patch("/sections/{section_id}")
def update_admin_section(
    section_id: int,
    data: SectionIn,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    values = _section_values(data)
    c = connect_tenant(tenant_id)

    try:
        existing = c.execute(
            """
            SELECT SectionID
            FROM SectionCatalog
            WHERE SectionID = ?
              AND TenantID = ?
              AND IsDeleted = 0
            """,
            (section_id, tenant_id)
        ).fetchone()

        if not existing:
            raise HTTPException(404, "Section not found.")

        _validate_section_catalog_values(c, tenant_id, values)

        if _check_section_duplicate(
            c,
            tenant_id,
            values,
            exclude_id=section_id
        ):
            raise HTTPException(
                409,
                "Another Section Catalog entry already has these values."
            )

        c.execute(
            """
            UPDATE SectionCatalog
            SET Industry = ?,
                Service = ?,
                SectionName = ?,
                SubSectionName = ?,
                SubSubSectionName = ?,
                Remarks = ?,
                DefaultHours = ?
            WHERE SectionID = ?
              AND TenantID = ?
              AND IsDeleted = 0
            """,
            (*values, section_id, tenant_id)
        )

        c.commit()

        return {
            "ok": True,
            "message": "Section updated successfully."
        }

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()

@router.delete("/sections/{section_id}")
def delete_admin_section(
    section_id: int,
    user=Depends(_require_admin)
):
    tenant_id = _tenant_id(user)
    c = connect_tenant(tenant_id)

    try:
        cursor = c.execute(
            """
            UPDATE SectionCatalog
            SET IsDeleted = 1
            WHERE SectionID = ?
              AND TenantID = ?
              AND IsDeleted = 0
            """,
            (section_id, tenant_id)
        )

        if cursor.rowcount == 0:
            raise HTTPException(404, "Section not found.")

        c.commit()

        return {
            "ok": True,
            "message": "Section deleted successfully."
        }

    except HTTPException:
        c.rollback()
        raise
    except Exception as exc:
        c.rollback()
        raise HTTPException(400, str(exc))
    finally:
        c.close()