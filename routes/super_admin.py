# routes/super_admin.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core.database import connect
from core.security import hash_password, verify_password, generate_token
from core.dependencies import current_user

router = APIRouter(prefix="/api/super-admin", tags=["super-admin"])

class AdminLogin(BaseModel):
    username: str
    password: str

class TenantCreate(BaseModel):
    company_name: str
    industry: str
    admin_username: str
    admin_password: str

# --- Super Admin Login ---
@router.post("/login")
def super_admin_login(body: AdminLogin):
    c = connect()
    row = c.execute(
        "SELECT * FROM Employee WHERE LOWER(Username) = LOWER(?) AND Classification = 'SuperAdmin'", 
        (body.username.strip(),)
    ).fetchone()
    
    if not row or not verify_password(body.password, row["PasswordHash"]):
        c.close()
        raise HTTPException(401, "Invalid Super Admin credentials")
        
    token = generate_token()
    c.execute("INSERT INTO Token VALUES (?,?,?)", (token, row["EmployeeID"], "2026-01-01T00:00:00"))
    c.commit()
    c.close()
    
    return {"token": token, "name": row["EmployeeName"]}

# --- PROTECTED: Create Tenant ---
@router.post("/tenants")
def create_tenant(data: TenantCreate, user=Depends(current_user)):
    if user.get("Classification") != "SuperAdmin":
        raise HTTPException(403, "Access denied. Super Admin only.")
        
    c = connect()
    try:
        # 1. Create Tenant
        c.execute("INSERT INTO Tenant (CompanyName, Industry) VALUES (?, ?)", 
                  (data.company_name, data.industry))
        tenant_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
                
        # 2. Create Admin User for this Tenant
        c.execute("""
            INSERT INTO Employee (TenantID, EmployeeName, Username, PasswordHash, Classification)
            VALUES (?, ?, ?, ?, 'Administrator')
        """, (tenant_id, f"{data.company_name} Admin", data.admin_username, hash_password(data.admin_password)))
        
        c.commit()
        return {"ok": True, "tenant_id": tenant_id}
    except Exception as e:
        c.rollback()
        raise HTTPException(400, str(e))
    finally:
        c.close()
@router.get("/tenants")
def list_tenants(user=Depends(current_user)):
    if user.get("Classification") != "SuperAdmin":
        raise HTTPException(403, "Access denied.")
    
    c = connect()
    rows = c.execute("""
        SELECT t.TenantID, t.CompanyName, t.Industry, COUNT(e.EmployeeID) as EmployeeCount
        FROM Tenant t
        LEFT JOIN Employee e ON e.TenantID = t.TenantID
        GROUP BY t.TenantID
    """).fetchall()
    c.close()
    return [dict(r) for r in rows]
# Add this Pydantic model
class TenantUpdate(BaseModel):
    company_name: str
    industry: str
    admin_username: str | None = None
    admin_password: str | None = None

# Add this endpoint to routes/super_admin.py
@router.put("/tenants/{tenant_id}")
def update_tenant(tenant_id: int, data: TenantUpdate, user=Depends(current_user)):
    if user.get("Classification") != "SuperAdmin":
        raise HTTPException(403, "Access denied. Super Admin only.")
        
    c = connect()
    try:
        # 1. Update the Tenant details
        c.execute("UPDATE Tenant SET CompanyName = ?, Industry = ? WHERE TenantID = ?", 
                  (data.company_name, data.industry, tenant_id))
        
        # 2. If a new Admin Username/Password is provided, update the Admin
        if data.admin_username and data.admin_password:
            # Find the admin of this tenant
            admin = c.execute("SELECT EmployeeID FROM Employee WHERE TenantID = ? AND Classification = 'Administrator'", (tenant_id,)).fetchone()
            
            if admin:
                c.execute("UPDATE Employee SET Username = ?, PasswordHash = ? WHERE EmployeeID = ?", 
                          (data.admin_username, hash_password(data.admin_password), admin["EmployeeID"]))
            else:
                # If no admin exists for some reason, create one
                c.execute("""
                    INSERT INTO Employee (TenantID, EmployeeName, Username, PasswordHash, Classification)
                    VALUES (?, ?, ?, ?, 'Administrator')
                """, (tenant_id, f"{data.company_name} Admin", data.admin_username, hash_password(data.admin_password)))
        
        c.commit()
        return {"ok": True}
    except Exception as e:
        c.rollback()
        raise HTTPException(400, str(e))
    finally:
        c.close()
@router.get("/tenants/{tenant_id}/employees")
def get_tenant_employees(tenant_id: int, user=Depends(current_user)):
    if user.get("Classification") != "SuperAdmin":
        raise HTTPException(403, "Access denied.")
    
    c = connect()
    rows = c.execute("""
        SELECT EmployeeName, Username, Classification, TeamLeader 
        FROM Employee 
        WHERE TenantID = ?
        ORDER BY Classification, EmployeeName
    """, (tenant_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]