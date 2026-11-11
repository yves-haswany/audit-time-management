import os
from io import BytesIO
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
    
    last_row = ws.max_row
    new_id = 1 if last_row == 1 else ws.cell(row=last_row, column=1).value + 1
    
    dt = datetime.fromisoformat(login_time)
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H:%M")

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
            ws.cell(row=row[0].row, column=11).value = time_str
            ws.cell(row=row[0].row, column=12).value = round(hours_logged, 2)
            ws.cell(row=row[0].row, column=13).value = job_desc
            break
            
    wb.save(LOG_FILE)

def get_filtered_logs_as_list(employees: list[str] = None, all_logs: bool = False) -> list[dict]:
    """Returns TimeLogs as a JSON-ready list, optionally filtered by employee names."""
    if not LOG_FILE.exists():
        return []

    wb = load_workbook(LOG_FILE, data_only=True)
    ws = wb.active
    
    headers = [cell.value for cell in ws[1]]
    results = []

    for row in ws.iter_rows(min_row=2):
        row_data = {headers[i]: row[i].value for i in range(len(headers))}
        
        if all_logs or (employees and row_data.get("Employee") in employees):
            # Format dates/times for JSON
            if row_data.get("Date") and hasattr(row_data["Date"], "strftime"):
                row_data["Date"] = row_data["Date"].strftime("%Y-%m-%d")
            results.append(row_data)
            
    return results
def export_user_logs_to_bytes(employees: list[str]) -> bytes:
    """Returns an Excel file containing only the logs for the specific employees."""
    if not LOG_FILE.exists():
        raise FileNotFoundError("No time logs exist yet.")

    wb = load_workbook(LOG_FILE)
    ws = wb.active
    
    # Create a new workbook for the filtered data
    new_wb = Workbook()
    new_ws = new_wb.active
    new_ws.append(HEADERS)
    
    # Copy rows where the Employee column (Column D / Index 3) matches the list
    for row in ws.iter_rows(min_row=2):
        if row[3].value in employees:
            new_ws.append([cell.value for cell in row])
            
    buf = BytesIO()
    new_wb.save(buf)
    return buf.getvalue()

def get_filtered_logs_as_list(employees: list[str] = None, all_logs: bool = False) -> list[dict]:
    """Returns TimeLogs as a JSON-ready list, optionally filtered by employee names."""
    if not LOG_FILE.exists():
        return []

    wb = load_workbook(LOG_FILE, data_only=True)
    ws = wb.active
    
    headers = [cell.value for cell in ws[1]]
    results = []

    for row in ws.iter_rows(min_row=2):
        row_data = {headers[i]: row[i].value for i in range(len(headers))}
        
        if all_logs or (employees and row_data.get("Employee") in employees):
            # Format dates/times for JSON
            if row_data.get("Date") and hasattr(row_data["Date"], "strftime"):
                row_data["Date"] = row_data["Date"].strftime("%Y-%m-%d")
            results.append(row_data)
            
    return results