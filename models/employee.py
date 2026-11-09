from pydantic import BaseModel


class EmployeeSummary(BaseModel):
    EmployeeName: str
    Username: str
    MissionCount: int
    TaskCount: int
    HasWork: bool