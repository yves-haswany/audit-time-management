from pydantic import BaseModel


class StartMissionResponse(BaseModel):
    ok: bool
    outside_window: bool = False


class TaskUpdateIn(BaseModel):
    Launched: bool | None = None
    Suspended: bool | None = None
    Accomplished: bool | None = None
    Adopted: bool | None = None