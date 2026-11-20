
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.dependencies import current_user
from core.database import connect_tenant
from models.session import TaskUpdateIn
from services import task_service

from scripts.export_timelog import (
    log_start_time,
    log_end_time,
)


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class StopTaskIn(BaseModel):
    JobDesc: str


@router.get("/active")
def get_active_task(user=Depends(current_user)):
    tenant_id = user["TenantID"]
    employee_id = user["EmployeeID"]

    c = connect_tenant(tenant_id)

    try:
        row = c.execute(
            """
            SELECT ws.LoginTime, t.*
            FROM WorkSession ws
            JOIN MissionTask t
                ON t.TaskID = ws.TaskID
            JOIN Mission m
                ON m.MissionID = t.MissionID
            WHERE ws.EmployeeID = ?
              AND ws.LogoutTime IS NULL
              AND m.TenantID = ?
            ORDER BY ws.LoginTime DESC
            LIMIT 1
            """,
            (employee_id, tenant_id),
        ).fetchone()

        if not row:
            return {"active": False}

        data = dict(row)
        data["active"] = True

        total_row = c.execute(
            """
            SELECT SUM(
                (
                    julianday(
                        COALESCE(ws.LogoutTime, datetime('now'))
                    ) - julianday(ws.LoginTime)
                ) * 24
            ) AS total_hours
            FROM WorkSession ws
            JOIN MissionTask t
                ON t.TaskID = ws.TaskID
            JOIN Mission m
                ON m.MissionID = t.MissionID
            WHERE ws.EmployeeID = ?
              AND ws.TaskID = ?
              AND m.TenantID = ?
            """,
            (employee_id, data["TaskID"], tenant_id),
        ).fetchone()

        previous_hours = (
            total_row["total_hours"]
            if total_row and total_row["total_hours"]
            else 0
        )

        login_dt = datetime.fromisoformat(data["LoginTime"])

        current_session_hours = (
            datetime.utcnow() - login_dt
        ).total_seconds() / 3600

        data["PreviousHours"] = max(
            0,
            previous_hours - current_session_hours,
        )

        return data

    finally:
        c.close()


@router.post("/{task_id}/start")
def start_task(task_id: int, user=Depends(current_user)):
    tenant_id = user["TenantID"]
    employee_id = user["EmployeeID"]

    # The service validates that the task is assigned to this employee.
    result = task_service.start(
        employee_id,
        task_id,
        tenant_id,
    )

    c = connect_tenant(tenant_id)

    try:
        info = c.execute(
            """
            SELECT
                m.IDHonorary,
                m.CustomerName,
                s.ServiceName AS Service,
                t.TaskName,
                t.TaskDescription
            FROM MissionTask t
            JOIN Mission m
                ON m.MissionID = t.MissionID
            JOIN Service s
                ON s.ServiceID = m.ServiceID
               AND s.TenantID = m.TenantID
            WHERE t.TaskID = ?
              AND t.EmployeeID = ?
              AND m.TenantID = ?
            """,
            (task_id, employee_id, tenant_id),
        ).fetchone()

        session = c.execute(
            """
            SELECT SessionID, LoginTime
            FROM WorkSession
            WHERE EmployeeID = ?
              AND TaskID = ?
              AND LogoutTime IS NULL
            ORDER BY SessionID DESC
            LIMIT 1
            """,
            (employee_id, task_id),
        ).fetchone()

    finally:
        c.close()

    if info and session:
        description = info["TaskDescription"] or ""
        parts = description.split(" / ")

        section_name = parts[0] if len(parts) > 0 else "-"
        subsection_name = parts[1] if len(parts) > 1 else "-"
        subsubsection_name = info["TaskName"]

        record_id = log_start_time(
            user["EmployeeName"],
            info["IDHonorary"],
            info["CustomerName"],
            info["Service"],
            section_name,
            subsection_name,
            subsubsection_name,
            session["LoginTime"],
            tenant_id,
        )

        c = connect_tenant(tenant_id)

        try:
            c.execute(
                """
                UPDATE WorkSession
                SET TimeLogID = ?
                WHERE SessionID = ?
                  AND EmployeeID = ?
                  AND TaskID = ?
                """,
                (
                    record_id,
                    session["SessionID"],
                    employee_id,
                    task_id,
                ),
            )

            c.commit()

        except Exception:
            c.rollback()
            raise

        finally:
            c.close()

    return result


@router.post("/{task_id}/stop")
def stop_task(
    task_id: int,
    body: StopTaskIn,
    user=Depends(current_user),
):
    tenant_id = user["TenantID"]
    employee_id = user["EmployeeID"]

    c = connect_tenant(tenant_id)

    try:
        now = datetime.utcnow().replace(
            microsecond=0
        ).isoformat()

        session = c.execute(
            """
            SELECT
                ws.SessionID,
                ws.LoginTime,
                ws.TimeLogID
            FROM WorkSession ws
            JOIN MissionTask t
                ON t.TaskID = ws.TaskID
            JOIN Mission m
                ON m.MissionID = t.MissionID
            WHERE ws.EmployeeID = ?
              AND ws.TaskID = ?
              AND ws.LogoutTime IS NULL
              AND m.TenantID = ?
            ORDER BY ws.SessionID DESC
            LIMIT 1
            """,
            (employee_id, task_id, tenant_id),
        ).fetchone()

        if not session:
            raise HTTPException(
                404,
                "No active session found for this task.",
            )

        login_dt = datetime.fromisoformat(
            session["LoginTime"]
        )

        logout_dt = datetime.fromisoformat(now)

        hours_logged = (
            logout_dt - login_dt
        ).total_seconds() / 3600.0

        # Close the tenant database session.
        c.execute(
            """
            UPDATE WorkSession
            SET LogoutTime = ?,
                JobDesc = ?
            WHERE SessionID = ?
              AND EmployeeID = ?
              AND TaskID = ?
              AND LogoutTime IS NULL
            """,
            (
                now,
                body.JobDesc,
                session["SessionID"],
                employee_id,
                task_id,
            ),
        )

        c.commit()

    except Exception:
        c.rollback()
        raise

    finally:
        c.close()

    # Update the separate tenant-specific Excel time log.
    # If this fails, the database session remains correctly closed.
    if session["TimeLogID"]:
        try:
            log_end_time(
                session["TimeLogID"],
                now,
                hours_logged,
                body.JobDesc,
                tenant_id,
            )
        except Exception as exc:
            raise HTTPException(
                500,
                (
                    "The task session was stopped, but the Excel "
                    f"time log could not be updated: {str(exc)}"
                ),
            )

    return {"ok": True}


@router.patch("/{task_id}")
def update_task(
    task_id: int,
    body: TaskUpdateIn,
    user=Depends(current_user),
):
    changes = body.model_dump(exclude_none=True)

    return task_service.update(
        user["EmployeeID"],
        task_id,
        user["TenantID"],
        changes,
    )
