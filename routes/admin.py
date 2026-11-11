"""Admin endpoints — currently the Excel exporter and mission list."""
from __future__ import annotations

import os
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response

from core.dependencies import current_user
from core.database import connect
from scripts.export_mission import export_mission_to_bytes
from scripts.export_timelog import get_filtered_logs_as_list, export_user_logs_to_bytes

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/missions")
def all_missions(user=Depends(current_user)):
    # ... (keep your existing code here) ...
    pass


@router.get("/export/{mission_id}")
def export_mission(mission_id: int, user=Depends(current_user)):
    # ... (keep your existing code here) ...
    pass


@router.get("/time-logs")
def view_time_logs(user=Depends(current_user)):
    """Returns a filtered list of time logs based on the user's role."""
    
    # 1. Administrator: Gets all logs
    if user.get("Classification") == "Administrator":
        return get_filtered_logs_as_list(all_logs=True)
        
    # 2. Team Leader: Gets their team's logs + their own
    # We check the Classification field to find leaders
    elif user.get("Classification") in ["Team Leader", "Team leader"]:
        c = connect()
        # Find everyone who has this user as their TeamLeader
        team = c.execute(
            "SELECT EmployeeName FROM Employee WHERE TeamLeader = ?", 
            (user["EmployeeName"],)
        ).fetchall()
        c.close()
        
        # Add the leader's own name to the list
        team_names = [t["EmployeeName"] for t in team]
        team_names.append(user["EmployeeName"])
        
        return get_filtered_logs_as_list(employees=team_names)
        
    # 3. Regular Employee: Gets only their own logs
    else:
        return get_filtered_logs_as_list(employees=[user["EmployeeName"]])


@router.get("/download-timelogs")
def download_timelogs(user=Depends(current_user)):
    """Downloads the Excel file based on the user's role."""
    
    # 1. Administrator: Gets the master file with everyone's data
    if user.get("Classification") == "Administrator":
        file_path = os.path.join("exports", "TimeLogs.xlsx")
        if not os.path.exists(file_path):
            raise HTTPException(404, "No logs exist yet.")
        return FileResponse(
            path=file_path,
            filename="All_Company_TimeLogs.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    # 2. Team Leader: Generate a file with their team + themselves
    elif user.get("Classification") in ["Team Leader", "Team leader"]:
        c = connect()
        team = c.execute(
            "SELECT EmployeeName FROM Employee WHERE TeamLeader = ?", 
            (user["EmployeeName"],)
        ).fetchall()
        c.close()
        
        team_names = [t["EmployeeName"] for t in team]
        team_names.append(user["EmployeeName"])
        
        # --- DEBUG PRINT ---
        print(f"\n[DEBUG] Download Request from Team Leader: {user['EmployeeName']}")
        print(f"[DEBUG] List of employees to include: {team_names}\n")
        # -------------------

        try:
            data = export_user_logs_to_bytes(team_names)
            return Response(
                content=data,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="My_Team_TimeLogs.xlsx"'}
            )
        except Exception as e:
            raise HTTPException(404, str(e))

    # 3. Regular Employee: Generate a file with only their own data
    else:
        try:
            data = export_user_logs_to_bytes([user["EmployeeName"]])
            return Response(
                content=data,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="My_TimeLogs.xlsx"'}
            )
        except Exception as e:
            raise HTTPException(404, str(e))