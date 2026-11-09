"""FastAPI dependencies — currently just current_user()."""
from fastapi import Header, HTTPException
from core.database import connect


def current_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    token = authorization.split(" ", 1)[1]
    c = connect()
    row = c.execute("""
        SELECT e.* FROM Token t
        JOIN Employee e ON e.EmployeeID = t.EmployeeID
        WHERE t.Token = ?
    """, (token,)).fetchone()
    c.close()
    if not row:
        raise HTTPException(401, "Invalid token")
    return dict(row)