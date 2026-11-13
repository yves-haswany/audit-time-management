import sqlite3
from core.security import hash_password

# Connect to the database
c = sqlite3.connect('db/audit.db')

# Check if the Super Admin already exists
existing = c.execute("SELECT * FROM Employee WHERE Username = 'superadmin'").fetchone()

if existing:
    print("✅ Super Admin already exists.")
else:
    # Insert the Super Admin
    c.execute("""
        INSERT INTO Employee (TenantID, EmployeeName, LoginCode, Username, PasswordHash, Classification)
        VALUES (0, 'Super Admin', 'SA', 'superadmin', ?, 'SuperAdmin')
    """, (hash_password('admin123'),))
    
    c.commit()
    print("✅ Super Admin created successfully!")
    print("Username: superadmin")
    print("Password: admin123")

c.close()