
"""Tenant-isolated per-task timer and status updates."""

from datetime import datetime

from fastapi import HTTPException

from core.database import connect_tenant


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def start(employee_id: int, task_id: int, tenant_id: int) -> dict:
    if not tenant_id or tenant_id <= 0:
        raise HTTPException(403, "Invalid tenant.")

    c = connect_tenant(tenant_id)

    try:
        task = c.execute(
            """
            SELECT t.TaskID, t.MissionID
            FROM MissionTask t
            JOIN Mission m
                ON m.MissionID = t.MissionID
            WHERE t.TaskID = ?
              AND t.EmployeeID = ?
              AND m.TenantID = ?
            """,
            (task_id, employee_id, tenant_id),
        ).fetchone()

        if not task:
            raise HTTPException(
                404,
                "Task not found or not assigned to you.",
            )

        now = _now_iso()

        # Close previous open sessions belonging to this employee
        # in this tenant database.
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
                TaskID,
                LoginTime
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                employee_id,
                task["MissionID"],
                task_id,
                now,
            ),
        )

        c.commit()

        return {"ok": True}

    except Exception:
        c.rollback()
        raise

    finally:
        c.close()


def update(
    employee_id: int,
    task_id: int,
    tenant_id: int,
    changes: dict,
) -> dict:

    if not tenant_id or tenant_id <= 0:
        raise HTTPException(403, "Invalid tenant.")

    allowed = {
        "Launched",
        "Suspended",
        "Accomplished",
        "Adopted",
    }

    updates = {
        key: int(bool(value))
        for key, value in changes.items()
        if key in allowed
    }

    if not updates:
        raise HTTPException(
            400,
            "No valid fields to update.",
        )

    c = connect_tenant(tenant_id)

    try:
        task = c.execute(
            """
            SELECT t.TaskID
            FROM MissionTask t
            JOIN Mission m
                ON m.MissionID = t.MissionID
            WHERE t.TaskID = ?
              AND t.EmployeeID = ?
              AND m.TenantID = ?
            """,
            (task_id, employee_id, tenant_id),
        ).fetchone()

        if not task:
            raise HTTPException(
                404,
                "Task not found or not assigned to you.",
            )

        columns = ", ".join(
            f"{column} = ?" for column in updates
        )

        c.execute(
            f"""
            UPDATE MissionTask
            SET {columns}
            WHERE TaskID = ?
              AND EmployeeID = ?
            """,
            (
                *updates.values(),
                task_id,
                employee_id,
            ),
        )

        c.commit()

        return {"ok": True}

    except Exception:
        c.rollback()
        raise

    finally:
        c.close()
