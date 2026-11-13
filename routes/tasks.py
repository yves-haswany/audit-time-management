from fastapi import APIRouter, Depends
from pydantic import BaseModel
from core.dependencies import current_user
from models.session import TaskUpdateIn
from services import task_service
from core.database import connect
from datetime import datetime
import os

from scripts.export_timelog import log_start_time, log_end_time

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

class StopTaskIn(BaseModel):
    JobDesc: str

@router.get("/active")
def get_active_task(user=Depends(current_user)):
    c = connect()
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

    previous_hours = total_row["total_hours"] if total_row and total_row["total_hours"] else 0
    login_dt = datetime.fromisoformat(data["LoginTime"])
    current_session_hours = (datetime.utcnow() - login_dt).total_seconds() / 3600
    
    data["PreviousHours"] = max(0, previous_hours - current_session_hours)
    return data

@router.post("/{task_id}/start")
def start_task(task_id: int, user=Depends(current_user)):
    result = task_service.start(user["EmployeeID"], task_id)
    
    c = connect()
    info = c.execute("""
        SELECT m.IDHonorary, m.CustomerName, s.ServiceName AS Service, 
               t.TaskName, t.TaskDescription 
        FROM MissionTask t 
        JOIN Mission m ON m.MissionID = t.MissionID 
        JOIN Service s ON s.ServiceID = m.ServiceID
        WHERE t.TaskID = ?
    """, (task_id,)).fetchone()
    
    session = c.execute("""
        SELECT SessionID, LoginTime FROM WorkSession 
        WHERE EmployeeID = ? AND LogoutTime IS NULL ORDER BY SessionID DESC LIMIT 1
    """, (user["EmployeeID"],)).fetchone()
    c.close()

    if info and session:
        # Split the description into Section / SubSection
        desc = info["TaskDescription"] or ""
        parts = desc.split(" / ")
        section_name = parts[0] if len(parts) > 0 else "-"
        subsection_name = parts[1] if len(parts) > 1 else "-"
        subsubsection_name = info["TaskName"]  # Use the TaskName as SubSubSection

        record_id = log_start_time(
            user["EmployeeName"], 
            info["IDHonorary"], 
            info["CustomerName"], 
            info["Service"],
            section_name,
            subsection_name,
            subsubsection_name,
            session["LoginTime"]
        )
        c = connect()
        c.execute("UPDATE WorkSession SET TimeLogID = ? WHERE SessionID = ?", (record_id, session["SessionID"]))
        c.commit()
        c.close()

    return result

@router.post("/{task_id}/stop")
def stop_task(task_id: int, body: StopTaskIn, user=Depends(current_user)):
    c = connect()
    now = datetime.utcnow().replace(microsecond=0).isoformat()
    
    session = c.execute("""
        SELECT SessionID, LoginTime, TimeLogID 
        FROM WorkSession 
        WHERE EmployeeID = ? AND LogoutTime IS NULL
    """, (user["EmployeeID"],)).fetchone()

    if session:
        c.execute(
            """UPDATE WorkSession SET LogoutTime = ?, JobDesc = ?
               WHERE SessionID = ?""",
            (now, body.JobDesc, session["SessionID"]),
        )
        
        login_dt = datetime.fromisoformat(session["LoginTime"])
        logout_dt = datetime.fromisoformat(now)
        hours_logged = (logout_dt - login_dt).total_seconds() / 3600.0
        
        if session["TimeLogID"]:
            log_end_time(session["TimeLogID"], now, hours_logged, body.JobDesc)

    c.commit()
    c.close()
    return {"ok": True}

@router.patch("/{task_id}")
def update_task(task_id: int, body: TaskUpdateIn, user=Depends(current_user)):
    changes = body.model_dump(exclude_none=True)
    return task_service.update(user["EmployeeID"], task_id, changes)