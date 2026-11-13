import os
from io import BytesIO
from datetime import datetime
from pathlib import Path
from openpyxl import Workbook, load_workbook

LOG_FILE = Path("exports") / "TimeLogs.xlsx"
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

    # Write to exact coordinates to prevent column shifting
    new_row = last_row + 1
    ws.cell(row=new_row, column=1).value = new_id
    ws.cell(row=new_row, column=2).value = id_honorary
    ws.cell(row=new_row, column=3).value = date_str
    ws.cell(row=new_row, column=4).value = employee_name
    ws.cell(row=new_row, column=5).value = customer_name
    ws.cell(row=new_row, column=6).value = service
    ws.cell(row=new_row, column=7).value = section_name
    ws.cell(row=new_row, column=8).value = subsection_name
    ws.cell(row=new_row, column=9).value = subsubsection_name
    ws.cell(row=new_row, column=10).value = time_str
    ws.cell(row=new_row, column=11).value = ""  # Sign Out Time
    ws.cell(row=new_row, column=12).value = ""  # Hours Logged
    ws.cell(row=new_row, column=13).value = ""  # Job Description
    
    wb.save(LOG_FILE)
    return new_id

def log_end_time(record_id: int, logout_time: str, hours_logged: float, job_desc: str):
    """Updates the row with the matching RecordID."""
    if not LOG_FILE.exists():
        print("[ERROR] TimeLogs.xlsx does not exist!")
        return

    wb = load_workbook(LOG_FILE)
    ws = wb.active
    
    dt = datetime.fromisoformat(logout_time)
    time_str = dt.strftime("%H:%M")

    found = False
    for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
        if row[0].value == record_id:
            found = True
            # 13-Column Schema:
            # Col 11 = Sign Out Time
            # Col 12 = Hours Logged
            # Col 13 = Job Description
            ws.cell(row=row_idx, column=11).value = time_str
            ws.cell(row=row_idx, column=12).value = round(hours_logged, 2)
            ws.cell(row=row_idx, column=13).value = job_desc
            break
            
    if found:
        wb.save(LOG_FILE)
        print(f"[DEBUG] Updated RecordID {record_id} successfully.")
    else:
        print(f"[ERROR] RecordID {record_id} not found in Excel file!")

def get_filtered_logs_as_list(employees: list[str] = None, all_logs: bool = False) -> list[dict]:
    if not LOG_FILE.exists():
        return []

    wb = load_workbook(LOG_FILE, data_only=True)
    ws = wb.active
    
    headers = [cell.value for cell in ws[1]]
    results = []

    for row in ws.iter_rows(min_row=2):
        row_data = {headers[i]: row[i].value for i in range(len(headers))}
        
        if all_logs or (employees and row_data.get("Employee") in employees):
            if row_data.get("Date") and hasattr(row_data["Date"], "strftime"):
                row_data["Date"] = row_data["Date"].strftime("%Y-%m-%d")
            results.append(row_data)
            
    return results

def export_user_logs_to_bytes(employees: list[str]) -> bytes:
    if not LOG_FILE.exists():
        raise FileNotFoundError("No time logs exist yet.")

    wb = load_workbook(LOG_FILE)
    ws = wb.active
    
    new_wb = Workbook()
    new_ws = new_wb.active
    new_ws.append(HEADERS)
    
    for row in ws.iter_rows(min_row=2):
        if row[3].value in employees:
            new_ws.append([cell.value for cell in row])
            
    buf = BytesIO()
    new_wb.save(buf)
    return buf.getvalue()