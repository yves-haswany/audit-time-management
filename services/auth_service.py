"""Centralized authentication for TymeNaro."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from config import TOKEN_TTL_HOURS
from core.database import connect_master, connect_tenant
from core.security import generate_token, verify_password


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _now_iso() -> str:
    return _now().isoformat()


def _expiry_iso() -> str:
    return (_now() + timedelta(hours=TOKEN_TTL_HOURS)).isoformat()


def _create_session(
    *,
    user_type: str,
    super_admin_id: int | None = None,
    tenant_id: int | None = None,
    employee_id: int | None = None,
) -> str:
    token = generate_token()

    db = connect_master()
    try:
        db.execute(
            """
            INSERT INTO AuthSession (
                Token,
                UserType,
                SuperAdminID,
                TenantID,
                EmployeeID,
                CreatedAt,
                ExpiresAt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                user_type,
                super_admin_id,
                tenant_id,
                employee_id,
                _now_iso(),
                _expiry_iso(),
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return token


def login_employee(
    company_code: str,
    username: str,
    password: str,
) -> tuple[str, dict, dict]:
    """Authenticate an employee using company code, username and password."""

    company_code = company_code.strip()
    username = username.strip()

    if not company_code or not username or not password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    master = connect_master()

    try:
        tenant = master.execute(
            """
            SELECT TenantID, CompanyName, CompanyCode, Industry,
                   IsActive, DatabaseFile
            FROM TenantDirectory
            WHERE CompanyCode = ? COLLATE NOCASE
              AND IsActive = 1
            """,
            (company_code,),
        ).fetchone()
    finally:
        master.close()

    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    tenant_id = int(tenant["TenantID"])
    tenant_db = connect_tenant(tenant_id)

    try:
        # Verify that the tenant database belongs to this tenant.
        identity = tenant_db.execute(
            """
            SELECT TenantID, CompanyName
            FROM Tenant
            LIMIT 1
            """
        ).fetchone()

        if not identity or int(identity["TenantID"]) != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Tenant database identity verification failed",
            )

        employee = tenant_db.execute(
            """
            SELECT *
            FROM Employee
            WHERE LOWER(TRIM(Username)) = LOWER(TRIM(?))
              AND IsActive = 1
            LIMIT 1
            """,
            (username,),
        ).fetchone()

        if not employee:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not verify_password(password, employee["PasswordHash"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        employee_data = dict(employee)

    finally:
        tenant_db.close()

    employee_id = int(employee_data["EmployeeID"])

    token = _create_session(
        user_type="employee",
        tenant_id=tenant_id,
        employee_id=employee_id,
    )

    # Never return password hashes to the browser.
    employee_data.pop("PasswordHash", None)

    # Attach trusted tenant information from the master database.
    employee_data["TenantID"] = tenant_id
    employee_data["CompanyName"] = tenant["CompanyName"]
    employee_data["CompanyCode"] = tenant["CompanyCode"]
    employee_data["UserType"] = "employee"

    tenant_data = {
        "TenantID": tenant_id,
        "CompanyName": tenant["CompanyName"],
        "CompanyCode": tenant["CompanyCode"],
        "Industry": tenant["Industry"],
    }

    return token, employee_data, tenant_data


def login_super_admin(
    username: str,
    password: str,
) -> tuple[str, dict]:
    """Authenticate a Super Admin against the central master database."""

    username = username.strip()

    if not username or not password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    master = connect_master()

    try:
        row = master.execute(
            """
            SELECT SuperAdminID, FullName, Username,
                   PasswordHash, IsActive
            FROM SuperAdmin
            WHERE Username = ? COLLATE NOCASE
              AND IsActive = 1
            LIMIT 1
            """,
            (username,),
        ).fetchone()
    finally:
        master.close()

    if not row or not verify_password(password, row["PasswordHash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    super_admin = dict(row)

    token = _create_session(
        user_type="superadmin",
        super_admin_id=int(super_admin["SuperAdminID"]),
    )

    super_admin.pop("PasswordHash", None)
    super_admin["UserType"] = "superadmin"

    return token, super_admin


def logout(token: str, user: dict) -> None:
    """Delete this exact central session and close this employee's open sessions."""

    if user.get("UserType") == "employee":
        tenant_id = user.get("TenantID")
        employee_id = user.get("EmployeeID")

        if tenant_id is not None and employee_id is not None:
            tenant_db = connect_tenant(int(tenant_id))

            try:
                tenant_db.execute(
                    """
                    UPDATE WorkSession
                    SET LogoutTime = ?
                    WHERE EmployeeID = ?
                      AND LogoutTime IS NULL
                    """,
                    (_now_iso(), int(employee_id)),
                )
                tenant_db.commit()
            except Exception:
                tenant_db.rollback()
                raise
            finally:
                tenant_db.close()

    master = connect_master()

    try:
        master.execute(
            "DELETE FROM AuthSession WHERE Token = ?",
            (token,),
        )
        master.commit()
    except Exception:
        master.rollback()
        raise
    finally:
        master.close()