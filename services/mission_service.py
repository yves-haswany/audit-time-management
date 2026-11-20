
"""Tenant-isolated mission listing, selection and summary."""

from datetime import date, datetime

from fastapi import HTTPException

from core.database import connect_tenant


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _status(win_start: str, win_end: str) -> str:
    today = date.today().isoformat()

    if today < win_start:
        return "not_started"

    if today > win_end:
        return "overdue"

    return "open"


def summary(employee_id: int, tenant_id: int) -> dict:
    c = connect_tenant(tenant_id)

    try:
        employee = c.execute(
            """
            SELECT EmployeeID
            FROM Employee
            WHERE EmployeeID = ?
              AND IsActive = 1
            """,
            (employee_id,),
        ).fetchone()

        if not employee:
            raise HTTPException(404, "Employee not found.")

        tasks = c.execute(
            """
            SELECT COUNT(*)
            FROM MissionTask
            WHERE EmployeeID = ?
            """,
            (employee_id,),
        ).fetchone()[0]

        missions = c.execute(
            """
            SELECT COUNT(*)
            FROM MemberMissionBudget
            WHERE EmployeeID = ?
            """,
            (employee_id,),
        ).fetchone()[0]

        return {
            "MissionCount": missions,
            "TaskCount": tasks,
            "HasWork": tasks > 0,
        }

    finally:
        c.close()


def list_missions(employee_id: int, tenant_id: int) -> list[dict]:
    c = connect_tenant(tenant_id)

    try:
        emp = c.execute(
            """
            SELECT EmployeeName
            FROM Employee
            WHERE EmployeeID = ?
              AND IsActive = 1
            """,
            (employee_id,),
        ).fetchone()

        if not emp:
            return []

        emp_name = emp["EmployeeName"]

        rows = c.execute(
            """
            SELECT
                m.MissionID,
                m.CustomerName,
                m.IDHonorary,
                m.FiscalYear,
                m.WindowStart,
                m.WindowEnd,
                s.ServiceName AS Service,
                COUNT(t.TaskID) AS TasksTotal,
                SUM(t.AllocatedHours) AS AllocatedHours,
                SUM(t.Accomplished) AS TasksDone,
                0.0 AS ConsumedHours,
                0.0 AS PctConsumed
            FROM Mission m
            JOIN MissionTask t
                ON t.MissionID = m.MissionID
            LEFT JOIN Service s
                ON s.ServiceID = m.ServiceID
            WHERE m.TenantID = ?
              AND (
                  t.TeamMemberName = ?
                  OR t.TeamMemberName IN (
                      SELECT EmployeeName
                      FROM Employee
                      WHERE TeamLeader = ?
                        AND IsActive = 1
                  )
              )
            GROUP BY m.MissionID
            ORDER BY m.WindowStart
            """,
            (tenant_id, emp_name, emp_name),
        ).fetchall()

        output = []

        for row in rows:
            item = dict(row)

            item["WindowStatus"] = _status(
                item["WindowStart"],
                item["WindowEnd"],
            )

            item["DaysRemaining"] = (
                date.fromisoformat(item["WindowEnd"]) - date.today()
            ).days

            output.append(item)

        return output

    finally:
        c.close()


def start(
    employee_id: int,
    mission_id: int,
    tenant_id: int,
    force: bool = False,
) -> dict:
    c = connect_tenant(tenant_id)

    try:
        employee = c.execute(
            """
            SELECT EmployeeID
            FROM Employee
            WHERE EmployeeID = ?
              AND IsActive = 1
            """,
            (employee_id,),
        ).fetchone()

        if not employee:
            raise HTTPException(404, "Employee not found.")

        mission = c.execute(
            """
            SELECT *
            FROM Mission
            WHERE MissionID = ?
              AND TenantID = ?
            """,
            (mission_id, tenant_id),
        ).fetchone()

        if not mission:
            raise HTTPException(404, "Mission not found.")

        today = date.today().isoformat()

        window_start = mission["WindowStart"]
        window_end = mission["WindowEnd"]

        outside = not (window_start <= today <= window_end)

        if outside and not force:
            raise HTTPException(
                409,
                (
                    f"Outside mission window "
                    f"({window_start} -> {window_end}). "
                    "Retry with ?force=true."
                ),
            )

        now = _now_iso()

        # Close any previous open session for this employee
        # inside this tenant database only.
        c.execute(
            """
            UPDATE WorkSession
            SET LogoutTime = ?
            WHERE EmployeeID = ?
              AND LogoutTime IS NULL
            """,
            (now, employee_id),
        )

        c.execute(
            """
            INSERT INTO WorkSession (
                EmployeeID,
                MissionID,
                LoginTime
            )
            VALUES (?, ?, ?)
            """,
            (employee_id, mission_id, now),
        )

        c.commit()

        return {
            "ok": True,
            "outside_window": outside,
        }

    except Exception:
        c.rollback()
        raise

    finally:
        c.close()


def tasks(
    employee_id: int,
    mission_id: int,
    tenant_id: int,
) -> list[dict]:
    c = connect_tenant(tenant_id)

    try:
        rows = c.execute(
            """
            SELECT
                t.*,
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
              AND t.EmployeeID = ?
              AND m.TenantID = ?
            ORDER BY t.TaskID
            """,
            (mission_id, employee_id, tenant_id),
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        c.close()
