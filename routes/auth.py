
"""Authentication routes for employees and Super Admin."""

from fastapi import APIRouter, Depends

from core.database import connect_master
from core.dependencies import current_session_user
from models.auth import LoginIn, SuperAdminLoginIn
from services import auth_service


router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.get("/companies")
def get_login_companies():
    """Return active companies available for employee login."""

    db = connect_master()

    try:
        rows = db.execute(
            """
            SELECT CompanyCode, CompanyName
            FROM TenantDirectory
            WHERE IsActive = 1
            ORDER BY CompanyName COLLATE NOCASE
            """
        ).fetchall()

        return {
            "companies": [
                {
                    "CompanyCode": row["CompanyCode"],
                    "CompanyName": row["CompanyName"],
                }
                for row in rows
            ]
        }
    finally:
        db.close()


@router.post("/login")
def employee_login(body: LoginIn):
    token, employee, tenant = auth_service.login_employee(
        company_code=body.company_code,
        username=body.username,
        password=body.password,
    )

    return {
        "token": token,
        "employee": employee,
        "tenant": tenant,
    }


@router.post("/super-admin/login")
def super_admin_login(body: SuperAdminLoginIn):
    token, super_admin = auth_service.login_super_admin(
        username=body.username,
        password=body.password,
    )

    return {
        "token": token,
        "super_admin": super_admin,
    }


@router.post("/logout")
def logout(user=Depends(current_session_user)):
    token = user["_AuthToken"]

    auth_service.logout(token, user)

    return {"ok": True}
