from fastapi import APIRouter, Depends
from core.dependencies import current_user
from services import mission_service

router = APIRouter(prefix="/api/me", tags=["me"])

# ADDED THIS ENDPOINT:
@router.get("")
def get_me(user=Depends(current_user)):
    return {
        "EmployeeName": user["EmployeeName"],
        "Username": user["Username"]
    }

@router.get("/summary")
def summary(user=Depends(current_user)):
    s = mission_service.summary(user["EmployeeID"])
    return {
        "EmployeeName": user["EmployeeName"],
        "Username":     user["Username"],
        **s,
    }

@router.get("/missions")
def my_missions(user=Depends(current_user)):
    return mission_service.list_missions(user["EmployeeID"])