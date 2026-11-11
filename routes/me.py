from fastapi import APIRouter, Depends
from core.dependencies import current_user
from core.database import connect
from services import mission_service

router = APIRouter(prefix="/api/me", tags=["me"])

@router.get("")
def get_me(user=Depends(current_user)):
    return {
        "EmployeeName": user["EmployeeName"],
        "Username": user["Username"],
        "Classification": user.get("Classification", ""),
        "IsTeamLead": user.get("IsTeamLead", 0),
        "TeamLeader": user.get("TeamLeader", "")
    }

@router.get("/summary")
def summary(user=Depends(current_user)):
    s = mission_service.summary(user["EmployeeID"])
    return {
        "EmployeeName": user["EmployeeName"],
        "Username":     user["Username"],
        **s,
    }

@router.get("/missions")
def my_missions(user=Depends(current_user)):
    classification = str(user.get("Classification", "")).strip().lower()
    
    if classification in ["team leader", "administrator"]:
        c = connect()
        team = c.execute("SELECT EmployeeID FROM Employee WHERE TeamLeader = ?", (user["EmployeeName"],)).fetchall()
        c.close()
        
        employee_ids = [t["EmployeeID"] for t in team]
        employee_ids.append(user["EmployeeID"])
        
        all_missions = []
        for eid in employee_ids:
            all_missions.extend(mission_service.list_missions(eid))
            
        unique_missions = {m["MissionID"]: m for m in all_missions}.values()
        return list(unique_missions)
        
    return mission_service.list_missions(user["EmployeeID"])

# ADDED THIS ENDPOINT:
@router.get("/missions/{mid}/tasks")
def mission_tasks(mid: int, user=Depends(current_user)):
    c = connect()
    classification = str(user.get("Classification", "")).strip().lower()
    
    if classification in ["team leader", "administrator"]:
        # Team Leaders and Admins get ALL tasks in the mission
        rows = c.execute("""
            SELECT t.*, t.TeamMemberName as EmployeeName, 
                   ts.Signindate, ts.Signintime, ts.Signoutdate, ts.Signouttime
            FROM MissionTask t
            LEFT JOIN TaskSignTimes ts ON ts.TaskID = t.TaskID
            WHERE t.MissionID = ?
            ORDER BY t.TaskID
        """, (mid,)).fetchall()
    else:
        # Regular employees get only their own tasks
        rows = c.execute("""
            SELECT t.*, t.TeamMemberName as EmployeeName, 
                   ts.Signindate, ts.Signintime, ts.Signoutdate, ts.Signouttime
            FROM MissionTask t
            LEFT JOIN TaskSignTimes ts ON ts.TaskID = t.TaskID
            WHERE t.MissionID = ? AND t.EmployeeID = ?
            ORDER BY t.TaskID
        """, (mid, user["EmployeeID"])).fetchall()
        
    c.close()
    return [dict(r) for r in rows]