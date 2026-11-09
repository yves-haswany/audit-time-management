"""Excel round-trip exporter.

Reads the DB for a mission and writes the current state of the
Adopted / Launched / Suspended / Accomplished booleans and the
Sign-in/out date+time columns back into a copy of the mission Excel
file. Everything else (columns A-K, formatting, row order) is
preserved exactly as in the source.

Usage from Python:
    from scripts.export_mission import export_mission_to_bytes
    data = export_mission_to_bytes(mission_id=12)

Usage from CLI:
    python scripts/export_mission.py --mission-id 12 --out exported.xlsx
"""
from __future__ import annotations

import sys
from datetime import datetime, time
from io import BytesIO
from pathlib import Path

# Allow running as a script (python scripts/export_mission.py ...)
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import load_workbook      # noqa: E402

from config import MIS_XLS              # noqa: E402
from core.database import connect       # noqa: E402


SHEET_NAME = "Yves_TemplateMission"

# Excel column letters for the fields we overwrite.
#   L = Adopted, M = Launched, N = Suspended, O = Accomplished
#   P = Signindate, Q = Signintime, R = Signoutdate, S = Signouttime
COL_ADOPTED      = "L"
COL_LAUNCHED     = "M"
COL_SUSPENDED    = "N"
COL_ACCOMPLISHED = "O"
COL_SIGNINDATE   = "P"
COL_SIGNINTIME   = "Q"
COL_SIGNOUTDATE  = "R"
COL_SIGNOUTTIME  = "S"

# Excel row 1 is the header. The importer stored `ExcelRow` as the
# 0-based pandas index (0 for the first data row), which corresponds to
# Excel row = ExcelRow + 2.
def _excel_row(pandas_index: int) -> int:
    return pandas_index + 2

def _parse_date(dt_str: str | None):
    """Extract just the date object from the DB timestamp."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str).date()
    except ValueError:
        return None

def _parse_time(dt_str: str | None):
    """Extract just the HH:MM time object from the DB timestamp (dropping seconds)."""
    if not dt_str:
        return None
    try:
        # Handle the case where SQLite returns just the time (e.g., "14:32:05")
        if len(dt_str) <= 8 and ":" in dt_str:
            dt = datetime.strptime(dt_str, "%H:%M:%S")
        else:
            # Handle full ISO timestamps just in case
            dt = datetime.fromisoformat(dt_str)
            
        return time(dt.hour, dt.minute)  # Create time object with 0 seconds
    except ValueError:
        return None

def _fetch_mission_state(mission_id: int) -> list[dict]:
    """Return one dict per mission task with the data we'll write back."""
    c = connect()
    rows = c.execute(
        """
        SELECT
            t.TaskID,
            t.ExcelRow,
            t.Adopted,
            t.Launched,
            t.Suspended,
            t.Accomplished,
            ts.Signindate,
            ts.Signintime,
            ts.Signoutdate,
            ts.Signouttime,
            (SELECT JobDesc FROM WorkSession ws 
             WHERE ws.TaskID = t.TaskID AND ws.JobDesc IS NOT NULL 
             ORDER BY ws.SessionID DESC LIMIT 1) AS LatestJobDesc
        FROM MissionTask t
        LEFT JOIN TaskSignTimes ts ON ts.TaskID = t.TaskID
        WHERE t.MissionID = ?
        ORDER BY t.ExcelRow
        """,
        (mission_id,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]

def _write_row(ws, excel_row: int, state: dict) -> None:
    """Overwrite the reporting cells for one task row."""
    ws[f"{COL_ADOPTED}{excel_row}"]      = bool(state["Adopted"])
    ws[f"{COL_LAUNCHED}{excel_row}"]     = bool(state["Launched"])
    ws[f"{COL_SUSPENDED}{excel_row}"]    = bool(state["Suspended"])
    ws[f"{COL_ACCOMPLISHED}{excel_row}"] = bool(state["Accomplished"])

    # Write the JobDesc into column K if one exists
    if state.get("LatestJobDesc"):
        ws[f"K{excel_row}"] = state["LatestJobDesc"]

    # Write the Dates
    ws[f"{COL_SIGNINDATE}{excel_row}"]  = _parse_date(state["Signindate"])
    ws[f"{COL_SIGNOUTDATE}{excel_row}"] = _parse_date(state["Signoutdate"])

    # Write the Times and FORCE Excel to only display hh:mm
    signin_cell = ws[f"{COL_SIGNINTIME}{excel_row}"]
    signin_cell.value = _parse_time(state["Signintime"])
    signin_cell.number_format = 'hh:mm'

    signout_cell = ws[f"{COL_SIGNOUTTIME}{excel_row}"]
    signout_cell.value = _parse_time(state["Signouttime"])
    signout_cell.number_format = 'hh:mm'

def export_mission_to_bytes(mission_id: int) -> bytes:
    """Return the filled-in workbook as bytes (ready for HTTP download)."""
    states = _fetch_mission_state(mission_id)
    if not states:
        raise ValueError(f"No mission tasks found for MissionID={mission_id}")

    # Load the source workbook, keeping formatting and every other cell.
    wb = load_workbook(filename=MIS_XLS, keep_vba=False)
    if SHEET_NAME not in wb.sheetnames:
        ws = wb.worksheets[0]
    else:
        ws = wb[SHEET_NAME]

    for state in states:
        row = _excel_row(state["ExcelRow"])
        _write_row(ws, row, state)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()

def export_mission_to_path(mission_id: int, out_path: str | Path) -> Path:
    """CLI helper — writes the file to disk and returns the path."""
    data = export_mission_to_bytes(mission_id)
    out_path = Path(out_path)
    out_path.write_bytes(data)
    return out_path

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Export a mission to Excel.")
    ap.add_argument("--mission-id", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    p = export_mission_to_path(args.mission_id, args.out)
    print(f"[export] wrote {p} "
          f"({p.stat().st_size} bytes) for MissionID={args.mission_id}")