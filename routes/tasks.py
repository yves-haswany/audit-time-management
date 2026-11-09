from fastapi import APIRouter, Depends
from pydantic import BaseModel
from core.dependencies import current_user
from models.session import TaskUpdateIn
from services import task_service
from core.database import connect
from datetime import datetime
import os

from scripts.export_mission import export_mission_to_path

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# Create the exports directory if it doesn't exist
EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

# New Pydantic model to accept the job description on stop
class StopTaskIn(BaseModel):
    JobDesc: str

# IMPORTANT: This must be placed BEFORE the /{task_id} routes
@router.get("/active")
def get_active_task(user=Depends(current_user)):
    c = connect()
    # Find the open session
    row = c.execute(
        """
        SELECT ws.LoginTime, t.*
        FROM WorkSession ws
        JOIN MissionTask t ON t.TaskID = ws.TaskID
        WHERE ws.EmployeeID = ? AND ws.LogoutTime IS NULL
        ORDER BY ws.LoginTime DESC LIMIT 1
        """,
        (user["EmployeeID"],)
    ).fetchone()

    if not row:
        c.close()
        return {"active": False}

    data = dict(row)
    data["active"] = True
    
    # Calculate the total time already spent on this task across ALL sessions
    total_row = c.execute(
        """
        SELECT SUM(
            (julianday(COALESCE(LogoutTime, datetime('now')))-julianday(LoginTime))*24
        ) as total_hours
        FROM WorkSession
        WHERE EmployeeID = ? AND TaskID = ?
        """,
        (user["EmployeeID"], data["TaskID"])
    ).fetchone()
    
    c.close()

    # total_hours is the time spent BEFORE this current session started
    previous_hours = total_row["total_hours"] if total_row and total_row["total_hours"] else 0
    
    # We subtract the current session's elapsed time from the total so we can pass
    # just the "previous" time to the frontend.
    login_dt = datetime.fromisoformat(data["LoginTime"])
    current_session_hours = (datetime.utcnow() - login_dt).total_seconds() / 3600
    
    data["PreviousHours"] = max(0, previous_hours - current_session_hours)
    
    return data

@router.post("/{task_id}/start")
def start_task(task_id: int, user=Depends(current_user)):
    result = task_service.start(user["EmployeeID"], task_id)
    
    # Auto-export on start
    c = connect()
    mid = c.execute("SELECT MissionID FROM MissionTask WHERE TaskID = ?", (task_id,)).fetchone()
    c.close()
    if mid:
        out_path = os.path.join(EXPORT_DIR, f"mission_{mid['MissionID']}.xlsx")
        try:
            export_mission_to_path(mid["MissionID"], out_path)
        except Exception as e:
            print(f"Auto-export failed on start: {e}")

    return result

@router.post("/{task_id}/stop")
def stop_task(task_id: int, body: StopTaskIn, user=Depends(current_user)):
    c = connect()
    
    # Update the open session with LogoutTime and JobDesc
    c.execute(
        """UPDATE WorkSession SET LogoutTime = ?, JobDesc = ?
           WHERE EmployeeID = ? AND LogoutTime IS NULL""",
        (datetime.utcnow().replace(microsecond=0).isoformat(), body.JobDesc, user["EmployeeID"]),
    )
    
    mid = c.execute("SELECT MissionID FROM MissionTask WHERE TaskID = ?", (task_id,)).fetchone()
    c.commit()
    c.close()
    
    # Auto-export on stop
    if mid:
        out_path = os.path.join(EXPORT_DIR, f"mission_{mid['MissionID']}.xlsx")
        try:
            export_mission_to_path(mid["MissionID"], out_path)
        except Exception as e:
            print(f"Auto-export failed on stop: {e}")

    return {"ok": True}

@router.patch("/{task_id}")
def update_task(task_id: int, body: TaskUpdateIn, user=Depends(current_user)):
    changes = body.model_dump(exclude_none=True)
    return task_service.update(user["EmployeeID"], task_id, changes)
@router.get("/missions/{mid}/tasks")
def mission_tasks(mid: int, user=Depends(current_user)):
    c = connect()
    rows = c.execute("""SELECT t.*, ts.Signindate, ts.Signintime,
                               ts.Signoutdate, ts.Signouttime
                        FROM MissionTask t
                        LEFT JOIN TaskSignTimes ts ON ts.TaskID=t.TaskID
                        WHERE t.MissionID=? AND t.EmployeeID=?
                        ORDER BY t.TaskID""",
                     (mid, user["EmployeeID"])).fetchall()
    c.close()
    return [dict(r) for r in rows]