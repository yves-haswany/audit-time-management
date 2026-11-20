from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    company_code: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1)


class SuperAdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    token: str
    employee: dict