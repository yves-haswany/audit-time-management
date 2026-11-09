from pydantic import BaseModel


class MissionOut(BaseModel):
    MissionID: int
    CustomerName: str
    IDHonorary: int
    WindowStart: str
    WindowEnd: str
    WindowStatus: str          # open | not_started | overdue
    DaysRemaining: int
    AllocatedHours: float
    ConsumedHours: float
    PctConsumed: float | None
    TasksDone: int
    TasksTotal: int


class TaskOut(BaseModel):
    TaskID: int
    MissionID: int
    SectionName: str | None = None
    SubSectionName: str | None = None
    SubSubSectionName: str | None = None
    AllocatedHours: float
    Launched: int
    Suspended: int
    Accomplished: int
    Adopted: int
    Signindate: str | None = None
    Signintime: str | None = None
    Signoutdate: str | None = None
    Signouttime: str | None = None