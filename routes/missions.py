from fastapi import APIRouter, Depends

from core.dependencies import current_user
from services import mission_service

router = APIRouter(prefix="/api", tags=["missions"])


@router.post("/me/missions/{mission_id}/start")
def start_mission(mission_id: int,
                  force: bool = False,
                  user=Depends(current_user)):
    return mission_service.start(user["EmployeeID"], mission_id, force)


@router.get("/missions/{mission_id}/tasks")
def mission_tasks(mission_id: int, user=Depends(current_user)):
    return mission_service.tasks(user["EmployeeID"], mission_id)