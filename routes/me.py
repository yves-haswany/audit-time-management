
from fastapi import APIRouter, Depends

from core.dependencies import current_user
from core.database import connect_tenant
from services import mission_service


router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("")
def get_me(user=Depends(current_user)):
    return {
        "EmployeeName": user["EmployeeName"],
        "Username": user["Username"],
        "Classification": user.get("Classification", ""),
        "IsTeamLead": user.get("IsTeamLead", 0),
        "TeamLeader": user.get("TeamLeader", ""),
        "TenantID": user["TenantID"],
        "CompanyName": user.get("CompanyName", ""),
        "CompanyCode": user.get("CompanyCode", ""),
    }


@router.get("/summary")
def summary(user=Depends(current_user)):
    result = mission_service.summary(
        user["EmployeeID"],
        user["TenantID"],
    )

    return {
        "EmployeeName": user["EmployeeName"],
        "Username": user["Username"],
        **result,
    }


@router.get("/missions")
def my_missions(user=Depends(current_user)):
    tenant_id = user["TenantID"]
    employee_id = user["EmployeeID"]

    classification = str(
        user.get("Classification", "")
    ).strip().lower()

    if classification in ("team leader", "administrator"):
        c = connect_tenant(tenant_id)

        try:
            team = c.execute(
                """
                SELECT EmployeeID
                FROM Employee
                WHERE TeamLeader = ?
                  AND IsActive = 1
                """,
                (user["EmployeeName"],),
            ).fetchall()

            employee_ids = [
                row["EmployeeID"] for row in team
            ]

        finally:
            c.close()

        employee_ids.append(employee_id)

        all_missions = []

        for eid in employee_ids:
            all_missions.extend(
                mission_service.list_missions(eid, tenant_id)
            )

        unique_missions = {
            mission["MissionID"]: mission
            for mission in all_missions
        }

        return list(unique_missions.values())

    return mission_service.list_missions(
        employee_id,
        tenant_id,
    )


@router.get("/missions/{mid}/tasks")
def my_mission_tasks(mid: int, user=Depends(current_user)):
    return mission_service.tasks(
        user["EmployeeID"],
        mid,
        user["TenantID"],
    )


@router.get("/missions/{mid}/team-tasks")
def team_mission_tasks(mid: int, user=Depends(current_user)):
    classification = str(
        user.get("Classification", "")
    ).strip().lower()

    if classification not in ("team leader", "administrator"):
        return []

    tenant_id = user["TenantID"]
    c = connect_tenant(tenant_id)

    try:
        rows = c.execute(
            """
            SELECT
                t.*,
                t.TeamMemberName AS EmployeeName,
                ts.Signindate,
                ts.Signintime,
                ts.Signoutdate,
                ts.Signouttime
            FROM MissionTask t
            JOIN Mission m
                ON m.MissionID = t.MissionID
            LEFT JOIN TaskSignTimes ts
                ON ts.TaskID = t.TaskID
            WHERE t.MissionID = ?
              AND m.TenantID = ?
            ORDER BY t.TaskID
            """,
            (mid, tenant_id),
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        c.close()
