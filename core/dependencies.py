"""Authentication dependencies and tenant-aware session resolution."""

from datetime import datetime

from fastapi import Header, HTTPException

from core.database import connect_master, connect_tenant


INVALID_TOKEN = "Invalid or expired token"


def _get_bearer_token(authorization: str) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = authorization.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    return token


def _delete_expired_session(master, token: str) -> None:
    master.execute(
        "DELETE FROM AuthSession WHERE Token = ?",
        (token,),
    )
    master.commit()


def _load_authenticated_user(token: str) -> dict:
    """Resolve a central session and load its account from the correct database."""

    master = connect_master()

    try:
        session = master.execute(
            """
            SELECT Token, UserType, SuperAdminID,
                   TenantID, EmployeeID, CreatedAt, ExpiresAt
            FROM AuthSession
            WHERE Token = ?
            """,
            (token,),
        ).fetchone()

        if not session:
            raise HTTPException(status_code=401, detail=INVALID_TOKEN)

        session = dict(session)

        try:
            expires_at = datetime.fromisoformat(session["ExpiresAt"])
        except (TypeError, ValueError):
            _delete_expired_session(master, token)
            raise HTTPException(status_code=401, detail=INVALID_TOKEN)

        if datetime.utcnow() >= expires_at:
            _delete_expired_session(master, token)
            raise HTTPException(status_code=401, detail=INVALID_TOKEN)

        user_type = session["UserType"]

        if user_type == "employee":
            tenant_id = session["TenantID"]
            employee_id = session["EmployeeID"]

            if tenant_id is None or employee_id is None:
                raise HTTPException(status_code=401, detail=INVALID_TOKEN)

            tenant = master.execute(
                """
                SELECT TenantID, CompanyName, CompanyCode,
                       Industry, IsActive
                FROM TenantDirectory
                WHERE TenantID = ?
                """,
                (tenant_id,),
            ).fetchone()

            if not tenant or not tenant["IsActive"]:
                raise HTTPException(
                    status_code=401,
                    detail="Company account is inactive",
                )

            tenant_data = dict(tenant)

            # The tenant ID comes from the trusted master session,
            # never from a request parameter or browser-supplied value.
            tenant_db = connect_tenant(int(tenant_id))

            try:
                identity = tenant_db.execute(
                    """
                    SELECT TenantID
                    FROM Tenant
                    LIMIT 1
                    """
                ).fetchone()

                if not identity or int(identity["TenantID"]) != int(tenant_id):
                    raise HTTPException(
                        status_code=403,
                        detail="Tenant database identity verification failed",
                    )

                employee = tenant_db.execute(
                    """
                    SELECT *
                    FROM Employee
                    WHERE EmployeeID = ?
                      AND IsActive = 1
                    LIMIT 1
                    """,
                    (employee_id,),
                ).fetchone()

                if not employee:
                    raise HTTPException(
                        status_code=401,
                        detail="Employee account is inactive or unavailable",
                    )

                user = dict(employee)

            finally:
                tenant_db.close()

            user.pop("PasswordHash", None)
            user["TenantID"] = int(tenant_id)
            user["CompanyName"] = tenant_data["CompanyName"]
            user["CompanyCode"] = tenant_data["CompanyCode"]
            user["UserType"] = "employee"
            user["_AuthToken"] = token

            return user

        if user_type == "superadmin":
            super_admin_id = session["SuperAdminID"]

            if super_admin_id is None:
                raise HTTPException(status_code=401, detail=INVALID_TOKEN)

            row = master.execute(
                """
                SELECT SuperAdminID, FullName, Username, IsActive
                FROM SuperAdmin
                WHERE SuperAdminID = ?
                  AND IsActive = 1
                LIMIT 1
                """,
                (super_admin_id,),
            ).fetchone()

            if not row:
                raise HTTPException(
                    status_code=401,
                    detail="Super Admin account is inactive or unavailable",
                )

            user = dict(row)
            user["UserType"] = "superadmin"
            user["_AuthToken"] = token

            return user

        raise HTTPException(status_code=401, detail=INVALID_TOKEN)

    finally:
        master.close()


def current_session_user(authorization: str = Header(default="")):
    """Accept either an employee or a Super Admin session."""

    token = _get_bearer_token(authorization)
    return _load_authenticated_user(token)


def current_user(authorization: str = Header(default="")):
    """Employee-only dependency for company operational endpoints."""

    user = current_session_user(authorization)

    if user.get("UserType") != "employee":
        raise HTTPException(
            status_code=403,
            detail="Employee access required",
        )

    return user


def current_super_admin(authorization: str = Header(default="")):
    """Super-Admin-only dependency for central administration endpoints."""

    user = current_session_user(authorization)

    if user.get("UserType") != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="Super Admin access required",
        )

    return user