import os
from datetime import datetime
from pathlib import Path
from openpyxl import Workbook, load_workbook

LOG_FILE = Path("exports") / "TimeLogs.xlsx"

# Ensure folder exists
LOG_FILE.parent.mkdir(exist_ok=True)

HEADERS = [
    "RecordID", "IDHonorary", "Date", "Employee", "Customer", "Service", 
    "SectionName", "SubSectionName", "SubSubSectionName", 
    "Sign In Time", "Sign Out Time", "Hours Logged", "Job Description"
]

def log_start_time(employee_name: str, id_honorary: int, customer_name: str, service: str, 
                   section_name: str, subsection_name: str, subsubsection_name: str, 
                   login_time: str) -> int:
    """Creates a new row and returns the RecordID."""
    if not LOG_FILE.exists():
        wb = Workbook()
        ws = wb.active
        ws.append(HEADERS)
        wb.save(LOG_FILE)

    wb = load_workbook(LOG_FILE)
    ws = wb.active
    
    # Generate new RecordID
    last_row = ws.max_row
    new_id = 1 if last_row == 1 else ws.cell(row=last_row, column=1).value + 1
    
    # Format date and time
    dt = datetime.fromisoformat(login_time)
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H:%M")

    # Append new row
    ws.append([
        new_id, id_honorary, date_str, employee_name, customer_name, service,
        section_name, subsection_name, subsubsection_name,
        time_str, "", "", "" 
    ])
    
    wb.save(LOG_FILE)
    return new_id

def log_end_time(record_id: int, logout_time: str, hours_logged: float, job_desc: str):
    """Updates the row with the matching RecordID."""
    if not LOG_FILE.exists():
        return

    wb = load_workbook(LOG_FILE)
    ws = wb.active
    
    dt = datetime.fromisoformat(logout_time)
    time_str = dt.strftime("%H:%M")

    for row in ws.iter_rows(min_row=2):
        if row[0].value == record_id:
            # Columns are 1-indexed (A=1, B=2, etc.)
            # 11 = Sign Out Time (Col K)
            # 12 = Hours Logged (Col L)
            # 13 = Job Description (Col M)
            ws.cell(row=row[0].row, column=11).value = time_str
            ws.cell(row=row[0].row, column=12).value = round(hours_logged, 2)
            ws.cell(row=row[0].row, column=13).value = job_desc
            break
            
    wb.save(LOG_FILE)