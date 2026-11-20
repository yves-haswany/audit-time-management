
"""Tenant-specific Excel time-log storage and exporter."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Optional

from openpyxl import Workbook, load_workbook

from config import tenant_export_dir


HEADERS = [
    "RecordID",
    "IDHonorary",
    "Date",
    "Employee",
    "Customer",
    "Service",
    "SectionName",
    "SubSectionName",
    "SubSubSectionName",
    "Sign In Time",
    "Sign Out Time",
    "Hours Logged",
    "Job Description",
    "TenantID",
]


def _validate_tenant_id(tenant_id: int) -> int:
    if tenant_id is None:
        raise ValueError("TenantID is required.")

    tenant_id = int(tenant_id)

    if tenant_id <= 0:
        raise ValueError("A valid company TenantID is required.")

    return tenant_id


def _log_file(tenant_id: int):
    tenant_id = _validate_tenant_id(tenant_id)

    folder = tenant_export_dir(tenant_id)
    return folder / "TimeLogs.xlsx"


def _open_or_create_workbook(tenant_id: int):
    """Open or create the time-log workbook for one tenant only."""

    path = _log_file(tenant_id)

    if not path.exists():
        wb = Workbook()
        ws = wb.active
        ws.title = "TimeLogs"
        ws.append(HEADERS)
        wb.save(path)
        return wb, ws

    wb = load_workbook(path)
    ws = wb.active

    existing_headers = [
        cell.value for cell in ws[1]
    ]

    for header in HEADERS:
        if header not in existing_headers:
            column = len(existing_headers) + 1
            ws.cell(row=1, column=column).value = header
            existing_headers.append(header)

    wb.save(path)

    return wb, ws


def _header_positions(ws) -> dict:
    return {
        str(cell.value): cell.column
        for cell in ws[1]
        if cell.value is not None
    }


def _cell(row, positions, header):
    column = positions.get(header)

    if not column:
        return None

    return row[column - 1]


def _tenant_matches(value, tenant_id: int) -> bool:
    if value is None:
        return False

    try:
        return int(value) == tenant_id
    except (ValueError, TypeError):
        return False


def _next_record_id(ws, positions) -> int:
    record_column = positions["RecordID"]
    highest = 0

    for row_index in range(2, ws.max_row + 1):
        value = ws.cell(
            row=row_index,
            column=record_column,
        ).value

        try:
            highest = max(highest, int(value))
        except (ValueError, TypeError):
            continue

    return highest + 1


def log_start_time(
    employee_name: str,
    id_honorary: int,
    customer_name: str,
    service: str,
    section_name: str,
    subsection_name: str,
    subsubsection_name: str,
    login_time: str,
    tenant_id: int,
) -> int:

    tenant_id = _validate_tenant_id(tenant_id)

    dt = datetime.fromisoformat(login_time)

    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H:%M")

    wb, ws = _open_or_create_workbook(tenant_id)

    try:
        positions = _header_positions(ws)
        new_id = _next_record_id(ws, positions)

        values = {
            "RecordID": new_id,
            "IDHonorary": id_honorary,
            "Date": date_str,
            "Employee": employee_name,
            "Customer": customer_name,
            "Service": service,
            "SectionName": section_name,
            "SubSectionName": subsection_name,
            "SubSubSectionName": subsubsection_name,
            "Sign In Time": time_str,
            "Sign Out Time": "",
            "Hours Logged": "",
            "Job Description": "",
            "TenantID": tenant_id,
        }

        new_row = ws.max_row + 1

        for header, value in values.items():
            ws.cell(
                row=new_row,
                column=positions[header],
            ).value = value

        wb.save(_log_file(tenant_id))

        return new_id

    finally:
        wb.close()


def log_end_time(
    record_id: int,
    logout_time: str,
    hours_logged: float,
    job_desc: str,
    tenant_id: int,
):
    tenant_id = _validate_tenant_id(tenant_id)

    path = _log_file(tenant_id)

    if not path.exists():
        raise FileNotFoundError(
            "This company's TimeLogs.xlsx does not exist."
        )

    dt = datetime.fromisoformat(logout_time)
    time_str = dt.strftime("%H:%M")

    wb, ws = _open_or_create_workbook(tenant_id)

    try:
        positions = _header_positions(ws)
        found = False

        for row_index in range(2, ws.max_row + 1):
            record_value = ws.cell(
                row=row_index,
                column=positions["RecordID"],
            ).value

            row_tenant = ws.cell(
                row=row_index,
                column=positions["TenantID"],
            ).value

            try:
                same_record = int(record_value) == int(record_id)
            except (ValueError, TypeError):
                same_record = False

            if same_record and _tenant_matches(row_tenant, tenant_id):
                ws.cell(
                    row=row_index,
                    column=positions["Sign Out Time"],
                ).value = time_str

                ws.cell(
                    row=row_index,
                    column=positions["Hours Logged"],
                ).value = round(float(hours_logged), 2)

                ws.cell(
                    row=row_index,
                    column=positions["Job Description"],
                ).value = job_desc

                found = True
                break

        if not found:
            raise ValueError(
                "Time-log record not found for this company."
            )

        wb.save(path)

    finally:
        wb.close()


def get_filtered_logs_as_list(
    employees: Optional[list[str]] = None,
    all_logs: bool = False,
    tenant_id: int = None,
) -> list[dict]:

    tenant_id = _validate_tenant_id(tenant_id)
    path = _log_file(tenant_id)

    if not path.exists():
        return []

    wb = load_workbook(path, data_only=True)

    try:
        ws = wb.active
        positions = _header_positions(ws)

        if "TenantID" not in positions:
            return []

        results = []

        for row in ws.iter_rows(
            min_row=2,
            values_only=True,
        ):
            tenant_value = _cell(
                row,
                positions,
                "TenantID",
            )

            if not _tenant_matches(tenant_value, tenant_id):
                continue

            employee = _cell(
                row,
                positions,
                "Employee",
            )

            if not all_logs:
                if not employees or employee not in employees:
                    continue

            row_data = {
                header: _cell(row, positions, header)
                for header in HEADERS
            }

            if row_data.get("Date") and hasattr(
                row_data["Date"], "strftime"
            ):
                row_data["Date"] = row_data["Date"].strftime(
                    "%Y-%m-%d"
                )

            results.append(row_data)

        return results

    finally:
        wb.close()


def export_user_logs_to_bytes(
    employees: list[str],
    tenant_id: int = None,
) -> bytes:

    tenant_id = _validate_tenant_id(tenant_id)

    logs = get_filtered_logs_as_list(
        employees=employees,
        all_logs=False,
        tenant_id=tenant_id,
    )

    new_wb = Workbook()
    new_ws = new_wb.active
    new_ws.title = "TimeLogs"
    new_ws.append(HEADERS)

    for log in logs:
        new_ws.append([
            log.get(header)
            for header in HEADERS
        ])

    buffer = BytesIO()
    new_wb.save(buffer)
    new_wb.close()

    return buffer.getvalue()
