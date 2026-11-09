from fastapi import APIRouter, Depends

from core.dependencies import current_user
from models.auth import LoginIn
from services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn):
    token, employee = auth_service.login(body.username, body.password)
    return {"token": token, "employee": employee}


@router.post("/logout")
def logout(user=Depends(current_user)):
    auth_service.logout(user["EmployeeID"])
    return {"ok": True}