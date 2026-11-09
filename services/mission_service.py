"""Mission listing and selection."""
from datetime import date, datetime

from fastapi import HTTPException

from core.database import connect


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _status(win_start: str, win_end: str) -> str:
    today = date.today().isoformat()
    if today < win_start:
        return "not_started"
    if today > win_end:
        return "overdue"
    return "open"


def summary(employee_id: int) -> dict:
    c = connect()
    tasks = c.execute(
        "SELECT COUNT(*) FROM MissionTask WHERE EmployeeID = ?",
        (employee_id,),
    ).fetchone()[0]
    missions = c.execute(
        "SELECT COUNT(*) FROM MemberMissionBudget WHERE EmployeeID = ?",
        (employee_id,),
    ).fetchone()[0]
    c.close()
    return {"MissionCount": missions, "TaskCount": tasks, "HasWork": tasks > 0}


def list_missions(employee_id: int) -> list[dict]:
    c = connect()
    # UPDATE THIS QUERY TO SELECT FiscalYear
    rows = c.execute(
        """SELECT b.*, m.Service, m.FiscalYear 
           FROM MemberMissionBudget b
           JOIN Mission m ON m.MissionID = b.MissionID
           WHERE b.EmployeeID = ? ORDER BY b.WindowStart""",
        (employee_id,),
    ).fetchall()
    
    out = []
    for r in rows:
        d = dict(r)
        d["WindowStatus"] = _status(d["WindowStart"], d["WindowEnd"])
        d["DaysRemaining"] = (
            date.fromisoformat(d["WindowEnd"]) - date.today()
        ).days
        out.append(d)
    c.close()
    return out


def start(employee_id: int, mission_id: int, force: bool) -> dict:
    c = connect()
    m = c.execute("SELECT * FROM Mission WHERE MissionID = ?",
                  (mission_id,)).fetchone()
    if not m:
        c.close()
        raise HTTPException(404, "Mission not found")

    today = date.today().isoformat()
    ws, we = m["WindowStart"], m["WindowEnd"]
    outside = not (ws <= today <= we)
    if outside and not force:
        c.close()
        raise HTTPException(
            409,
            f"Outside mission window ({ws} → {we}). Retry with ?force=true.",
        )

    # Close any open session first
    c.execute(
        """UPDATE WorkSession SET LogoutTime = ?
           WHERE EmployeeID = ? AND LogoutTime IS NULL""",
        (_now_iso(), employee_id),
    )
    c.execute(
        """INSERT INTO WorkSession(EmployeeID, MissionID, LoginTime)
           VALUES (?,?,?)""",
        (employee_id, mission_id, _now_iso()),
    )
    c.commit()
    c.close()
    return {"ok": True, "outside_window": outside}


def tasks(employee_id: int, mission_id: int) -> list[dict]:
    c = connect()
    rows = c.execute(
        """SELECT t.*, ts.Signindate, ts.Signintime,
                  ts.Signoutdate, ts.Signouttime
           FROM MissionTask t
           LEFT JOIN TaskSignTimes ts ON ts.TaskID = t.TaskID
           WHERE t.MissionID = ? AND t.EmployeeID = ?
           ORDER BY t.TaskID""",
        (mission_id, employee_id),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]