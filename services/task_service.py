"""Per-task timer and status updates."""
from datetime import datetime

from fastapi import HTTPException

from core.database import connect


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def start(employee_id: int, task_id: int) -> dict:
    c = connect()
    t = c.execute(
        "SELECT * FROM MissionTask WHERE TaskID = ? AND EmployeeID = ?",
        (task_id, employee_id),
    ).fetchone()
    if not t:
        c.close()
        raise HTTPException(404, "Task not found or not yours")

    # Close any open session (task-level or mission-level)
    c.execute(
        """UPDATE WorkSession SET LogoutTime = ?
           WHERE EmployeeID = ? AND LogoutTime IS NULL""",
        (_now_iso(), employee_id),
    )
    c.execute(
        """INSERT INTO WorkSession(EmployeeID, MissionID, TaskID, LoginTime)
           VALUES (?,?,?,?)""",
        (employee_id, t["MissionID"], task_id, _now_iso()),
    )
    c.commit()
    c.close()
    return {"ok": True}


def update(employee_id: int, task_id: int, changes: dict) -> dict:
    allowed = {"Launched", "Suspended", "Accomplished", "Adopted"}
    upd = {k: int(bool(v)) for k, v in changes.items() if k in allowed}
    if not upd:
        raise HTTPException(400, "No valid fields to update")

    c = connect()
    sets = ", ".join(f"{k} = ?" for k in upd)
    c.execute(
        f"UPDATE MissionTask SET {sets} WHERE TaskID = ? AND EmployeeID = ?",
        (*upd.values(), task_id, employee_id),
    )
    c.commit()
    c.close()
    return {"ok": True}