"""Admin endpoints — currently the Excel exporter and mission list.

NOTE: these endpoints are open to any logged-in user for now. See §7
of the companion guide for how to gate them behind a team-lead role.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from core.dependencies import current_user
from core.database import connect
from scripts.export_mission import export_mission_to_bytes

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/missions")
def all_missions(user=Depends(current_user)):
    c = connect()
    rows = c.execute(
        """
        SELECT
            m.MissionID,
            m.IDHonorary,
            m.CustomerName,
            m.Service,
            m.FiscalYear,  -- ADD THIS
            m.WindowStart,
            m.WindowEnd,
            COUNT(t.TaskID)                 AS TasksTotal,
            ROUND(SUM(t.AllocatedHours), 1) AS AllocatedHours
        FROM Mission m
        LEFT JOIN MissionTask t ON t.MissionID = m.MissionID
        GROUP BY m.MissionID
        ORDER BY m.WindowStart
        """
    ).fetchall()


@router.get("/export/{mission_id}")
def export_mission(mission_id: int, user=Depends(current_user)):
    """Download the mission as an .xlsx with current progress filled in."""
    c = connect()
    m = c.execute(
        "SELECT MissionID, CustomerName, IDHonorary FROM Mission WHERE MissionID = ?",
        (mission_id,),
    ).fetchone()
    c.close()
    if not m:
        raise HTTPException(404, "Mission not found")

    try:
        data = export_mission_to_bytes(mission_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

    safe_customer = "".join(
        ch if ch.isalnum() else "_" for ch in m["CustomerName"]
    ).strip("_")
    filename = f"{safe_customer}_{m['IDHonorary']}_mission.xlsx"

    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )