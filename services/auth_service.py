"""Login / logout."""
from datetime import datetime

from fastapi import HTTPException

from core.database import connect
from core.security import generate_token, verify_password


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def login(username: str, password: str) -> tuple[str, dict]:
    c = connect()
    row = c.execute(
        """SELECT * FROM Employee
           WHERE LOWER(Username) = LOWER(?) AND IsActive = 1""",
        (username.strip(),),
    ).fetchone()
    if not row or not verify_password(password, row["PasswordHash"]):
        c.close()
        raise HTTPException(401, "Invalid credentials")

    token = generate_token()
    c.execute("INSERT INTO Token VALUES (?,?,?)",
              (token, row["EmployeeID"], _now_iso()))
    c.commit()
    employee = dict(row)
    employee["PasswordHash"] = None
    c.close()
    return token, employee


def logout(employee_id: int) -> None:
    c = connect()
    c.execute(
        """UPDATE WorkSession SET LogoutTime = ?
           WHERE EmployeeID = ? AND LogoutTime IS NULL""",
        (_now_iso(), employee_id),
    )
    c.execute("DELETE FROM Token WHERE EmployeeID = ?", (employee_id,))
    c.commit()
    c.close()