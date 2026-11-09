from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    employee: dict