
"""
One-time migration from audit.db to master.db and tenant databases.

The legacy database is opened read-only in intent: this script performs
no INSERT, UPDATE, DELETE, or schema changes against audit.db.

Run from the project root:
        python scripts/migrate_to_tenant_databases.py
"""

import sqlite3
import sys
from pathlib import Path

# Add the project root to Python's module search path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    LEGACY_DB_PATH,
    MASTER_DB_PATH,
    tenant_db_path,
)

TENANTS = {
    1: {
        "company": "Fiduciaire du Moyen Orient",
        "code": "FMO",
        "industry": "Auditing",
    },
    2: {
        "company": "Company 2",
        "code": "C2",
        "industry": "Industry 2",
    },
}

# Parent tables must be copied before their dependent tables.
TENANT_TABLES = [
    "Employee",
    "Industry",
    "Service",
    "Client",
    "SectionCatalog",
    "Mission",
    "MissionTask",
    "WorkSession",
]

# Tables whose records are directly associated with TenantID.
DIRECT_TENANT_TABLES = [
    "Employee",
    "Industry",
    "Service",
    "Client",
    "SectionCatalog",
    "Mission",
]


def table_columns(db, schema, table):
    rows = db.execute(
        f'PRAGMA "{schema}".table_info("{table}")'
    ).fetchall()
    return [row[1] for row in rows]


def table_count(db, schema, table):
    return db.execute(
        f'SELECT COUNT(*) FROM "{schema}"."{table}"'
    ).fetchone()[0]


def assert_empty(db, schema, tables):
    for table in tables:
        count = table_count(db, schema, table)
        if count != 0:
            raise RuntimeError(
                f"Destination {schema}.{table} is not empty "
                f"({count} records). Migration aborted."
            )


def assert_tenant_directory(db):
    for tenant_id, expected in TENANTS.items():
        row = db.execute(
            """
            SELECT TenantID, CompanyName, CompanyCode,
                   Industry, IsActive, DatabaseFile
            FROM masterdb.TenantDirectory
            WHERE TenantID = ?
            """,
            (tenant_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                f"Tenant {tenant_id} is missing from master.db."
            )

        actual = tuple(row)
        expected_values = (
            tenant_id,
            expected["company"],
            expected["code"],
            expected["industry"],
            1,
            f"tenant_{tenant_id}.db",
        )

        if actual != expected_values:
            raise RuntimeError(
                f"Tenant directory mismatch for TenantID={tenant_id}. "
                f"Expected {expected_values}, found {actual}."
            )

def assert_tenant_identity(db, schema, tenant_id):
    expected = TENANTS[tenant_id]

    rows = db.execute(
        f'SELECT TenantID, CompanyName, Industry '
        f'FROM "{schema}".Tenant'
    ).fetchall()

    if len(rows) != 1:
        raise RuntimeError(
            f"{schema} must contain exactly one Tenant identity row."
        )

    actual = tuple(rows[0])
    expected_values = (
        tenant_id,
        expected["company"],
        expected["industry"],
    )

    if actual != expected_values:
        raise RuntimeError(
            f"Tenant identity mismatch in {schema}. "
            f"Expected {expected_values}, found {actual}."
        )
def assert_schema_compatible(db, source_table, destination_schema):
    source_columns = set(
        table_columns(db, "main", source_table)
    )
    destination_columns = set(
        table_columns(db, destination_schema, source_table)
    )

    if source_columns != destination_columns:
        raise RuntimeError(
            f"Schema mismatch for {source_table} in {destination_schema}.\n"
            f"Source-only columns: {sorted(source_columns - destination_columns)}\n"
            f"Destination-only columns: {sorted(destination_columns - source_columns)}"
        )

    # Use the destination order for the INSERT column list.
    return table_columns(db, destination_schema, source_table)


def copy_direct_table(db, table, tenant_id, destination_schema):
    columns = assert_schema_compatible(
        db, table, destination_schema
    )

    column_sql = ", ".join(f'"{column}"' for column in columns)

    db.execute(
        f"""
        INSERT INTO "{destination_schema}"."{table}" ({column_sql})
        SELECT {column_sql}
        FROM main."{table}"
        WHERE TenantID = ?
        """,
        (tenant_id,),
    )

    return db.execute(
        f'SELECT changes()'
    ).fetchone()[0]


def copy_mission_tasks(db, tenant_id, destination_schema):
    columns = assert_schema_compatible(
        db, "MissionTask", destination_schema
    )

    column_sql = ", ".join(f'"{column}"' for column in columns)

    db.execute(
        f"""
        INSERT INTO "{destination_schema}"."MissionTask" ({column_sql})
        SELECT {column_sql}
        FROM main."MissionTask"
        WHERE MissionID IN (
            SELECT MissionID
            FROM main."Mission"
            WHERE TenantID = ?
        )
        """,
        (tenant_id,),
    )

    return db.execute("SELECT changes()").fetchone()[0]


def copy_work_sessions(db, tenant_id, destination_schema):
    columns = assert_schema_compatible(
        db, "WorkSession", destination_schema
    )

    column_sql = ", ".join(f'"{column}"' for column in columns)

    db.execute(
        f"""
        INSERT INTO "{destination_schema}"."WorkSession" ({column_sql})
        SELECT {column_sql}
        FROM main."WorkSession"
        WHERE MissionID IN (
            SELECT MissionID
            FROM main."Mission"
            WHERE TenantID = ?
        )
        """,
        (tenant_id,),
    )

    return db.execute("SELECT changes()").fetchone()[0]


def validate_source_relationships(db):
    # MissionTask records must belong to a valid mission.
    bad_tasks = db.execute(
        """
        SELECT COUNT(*)
        FROM main.MissionTask mt
        LEFT JOIN main.Mission m ON m.MissionID = mt.MissionID
        WHERE mt.MissionID IS NULL OR m.MissionID IS NULL
        """
    ).fetchone()[0]

    if bad_tasks:
        raise RuntimeError(
            f"{bad_tasks} MissionTask records have no valid mission."
        )

    # WorkSession records must belong to a valid mission.
    bad_sessions = db.execute(
        """
        SELECT COUNT(*)
        FROM main.WorkSession ws
        JOIN main.Mission m
          ON m.MissionID = ws.MissionID
        LEFT JOIN main.Employee e
          ON e.EmployeeID = ws.EmployeeID
        LEFT JOIN main.MissionTask mt
          ON mt.TaskID = ws.TaskID
        WHERE e.EmployeeID IS NULL
           OR e.TenantID <> m.TenantID
           OR (
                ws.TaskID IS NOT NULL
                AND (
                    mt.TaskID IS NULL
                    OR mt.MissionID <> ws.MissionID
                )
           )
        """
    ).fetchone()[0]

    if bad_sessions:
        raise RuntimeError(
            f"{bad_sessions} WorkSession records have invalid "
            "employee, tenant, or task relationships."
        )

    # No tenant 1 or tenant 2 employee should reference an employee
    # belonging to another tenant through MissionTask.
    cross_tenant_tasks = db.execute(
        """
        SELECT COUNT(*)
        FROM main.MissionTask mt
        JOIN main.Mission m ON m.MissionID = mt.MissionID
        JOIN main.Employee e ON e.EmployeeID = mt.EmployeeID
        WHERE e.TenantID <> m.TenantID
        """
    ).fetchone()[0]

    if cross_tenant_tasks:
        raise RuntimeError(
            f"{cross_tenant_tasks} mission tasks reference employees "
            "from another tenant."
        )


def validate_database(db, schema):
    fk_errors = db.execute(
        f'PRAGMA "{schema}".foreign_key_check'
    ).fetchall()

    if fk_errors:
        raise RuntimeError(
            f"Foreign-key errors in {schema}: {fk_errors[:10]}"
        )

    integrity = db.execute(
        f'PRAGMA "{schema}".integrity_check'
    ).fetchone()[0]

    if integrity != "ok":
        raise RuntimeError(
            f"Integrity check failed for {schema}: {integrity}"
        )


def migrate():
    paths = {
        "masterdb": Path(MASTER_DB_PATH),
        "t1": Path(tenant_db_path(1)),
        "t2": Path(tenant_db_path(2)),
    }

    if not Path(LEGACY_DB_PATH).is_file():
        raise FileNotFoundError(
            f"Legacy database not found: {LEGACY_DB_PATH}"
        )

    for schema, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(
                f"{schema} database not found: {path}"
            )

    print("Opening migration databases...")

    # Open the legacy database as the main database.
    db = sqlite3.connect(str(LEGACY_DB_PATH), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    try:
        # Attach all destinations to one SQLite connection.
        for schema, path in paths.items():
            db.execute(
                f'ATTACH DATABASE ? AS "{schema}"',
                (str(path),),
            )

        # Multi-database atomic transactions require rollback-journal
        # mode rather than WAL mode.
        journal_modes = {
            "main": db.execute(
                "PRAGMA main.journal_mode"
            ).fetchone()[0].lower(),
            "masterdb": db.execute(
                "PRAGMA masterdb.journal_mode"
            ).fetchone()[0].lower(),
            "t1": db.execute(
                "PRAGMA t1.journal_mode"
            ).fetchone()[0].lower(),
            "t2": db.execute(
                "PRAGMA t2.journal_mode"
            ).fetchone()[0].lower(),
        }

        print("\nSQLite journal modes:")
        for schema, mode in journal_modes.items():
            print(f"  {schema}: {mode}")

        allowed_modes = {"delete", "truncate", "persist"}

        unsafe_modes = {
            schema: mode
            for schema, mode in journal_modes.items()
            if mode not in allowed_modes
        }

        if unsafe_modes:
            raise RuntimeError(
                "Unsafe SQLite journal mode detected. "
                f"Migration stopped: {unsafe_modes}"
            )

        # Verify central tenant directory.
        assert_tenant_directory(db)
        assert_tenant_identity(db, "t1", 1)
        assert_tenant_identity(db, "t2", 2)

        # All operational destination tables must be empty.
        for schema in ("t1", "t2"):
            assert_empty(
                db,
                schema,
                TENANT_TABLES + ["Token"],
            )

        # Master account/session tables must be empty.
        assert_empty(
            db,
            "masterdb",
            ["SuperAdmin", "AuthSession"],
        )

        # Confirm the source has exactly one Super Admin.
        super_admins = db.execute(
            """
            SELECT EmployeeID, EmployeeName, Username,
                   PasswordHash, IsActive, Classification
            FROM main.Employee
            WHERE TenantID = 0
              AND Classification = 'SuperAdmin'
            """
        ).fetchall()

        if len(super_admins) != 1:
            raise RuntimeError(
                f"Expected exactly one Super Admin; found {len(super_admins)}."
            )

        admin = super_admins[0]

        if admin["EmployeeID"] != 61 or admin["Username"].lower() != "superadmin":
            raise RuntimeError(
                "The Super Admin identity does not match the expected account."
            )

        if not admin["PasswordHash"]:
            raise RuntimeError(
                "Super Admin password hash is empty."
            )

        # Verify there are no ambiguous or invalid operational relationships.
        validate_source_relationships(db)

        # Display pre-migration counts.
        print("\nSource counts:")
        for tenant_id in TENANTS:
            print(f"\nTenant {tenant_id}:")
            for table in DIRECT_TENANT_TABLES:
                count = db.execute(
                    f'SELECT COUNT(*) FROM main."{table}" WHERE TenantID = ?',
                    (tenant_id,),
                ).fetchone()[0]
                print(f"  {table}: {count}")

            task_count = db.execute(
                """
                SELECT COUNT(*)
                FROM main.MissionTask mt
                JOIN main.Mission m ON m.MissionID = mt.MissionID
                WHERE m.TenantID = ?
                """,
                (tenant_id,),
            ).fetchone()[0]

            session_count = db.execute(
                """
                SELECT COUNT(*)
                FROM main.WorkSession ws
                JOIN main.Mission m ON m.MissionID = ws.MissionID
                WHERE m.TenantID = ?
                """,
                (tenant_id,),
            ).fetchone()[0]

            print(f"  MissionTask: {task_count}")
            print(f"  WorkSession: {session_count}")

        print("\nStarting migration transaction...")

        db.execute("BEGIN IMMEDIATE")

        copied = {}

        # Copy each tenant's operational records.
        for tenant_id, schema in ((1, "t1"), (2, "t2")):
            copied[tenant_id] = {}

            for table in DIRECT_TENANT_TABLES:
                copied[tenant_id][table] = copy_direct_table(
                    db, table, tenant_id, schema
                )

            copied[tenant_id]["MissionTask"] = copy_mission_tasks(
                db, tenant_id, schema
            )

            copied[tenant_id]["WorkSession"] = copy_work_sessions(
                db, tenant_id, schema
            )

        # Move the Super Admin account into master.db.
        db.execute(
            """
            INSERT INTO masterdb.SuperAdmin (
                SuperAdminID,
                FullName,
                Username,
                PasswordHash,
                IsActive
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                admin["EmployeeID"],
                admin["EmployeeName"],
                admin["Username"],
                admin["PasswordHash"],
                admin["IsActive"],
            ),
        )

        # Validate each tenant database before committing.
        for schema in ("t1", "t2"):
            validate_database(db, schema)

        validate_database(db, "masterdb")

        # Validate copied record counts against the source.
        for tenant_id, schema in ((1, "t1"), (2, "t2")):
            for table in TENANT_TABLES:
                source_count = copied[tenant_id][table]
                destination_count = table_count(
                    db, schema, table
                )

                if source_count != destination_count:
                    raise RuntimeError(
                        f"Count mismatch for {schema}.{table}: "
                        f"copied {source_count}, found {destination_count}."
                    )

        master_admin_count = table_count(
            db, "masterdb", "SuperAdmin"
        )

        if master_admin_count != 1:
            raise RuntimeError(
                "Super Admin migration verification failed."
            )

        # Verify IDs and password hashes survived the copy.
        for tenant_id, schema in ((1, "t1"), (2, "t2")):
            mismatch = db.execute(
                f"""
                SELECT COUNT(*)
                FROM main.Employee src
                LEFT JOIN "{schema}".Employee dst
                    ON dst.EmployeeID = src.EmployeeID
                WHERE src.TenantID = ?
                  AND (
                      dst.EmployeeID IS NULL
                      OR dst.PasswordHash <> src.PasswordHash
                      OR dst.Username <> src.Username
                  )
                """,
                (tenant_id,),
            ).fetchone()[0]

            if mismatch:
                raise RuntimeError(
                    f"Employee ID or credential mismatch for tenant {tenant_id}."
                )

        admin_match = db.execute(
            """
            SELECT COUNT(*)
            FROM main.Employee src
            JOIN masterdb.SuperAdmin dst
              ON dst.SuperAdminID = src.EmployeeID
            WHERE src.TenantID = 0
              AND dst.Username = src.Username
              AND dst.PasswordHash = src.PasswordHash
            """
        ).fetchone()[0]

        if admin_match != 1:
            raise RuntimeError(
                "Super Admin credential verification failed."
            )

        # All checks passed. Commit all attached database changes.
        db.commit()

        print("\nMIGRATION COMMITTED SUCCESSFULLY")

        for tenant_id, schema in ((1, "t1"), (2, "t2")):
            print(f"\nTenant {tenant_id} ({TENANTS[tenant_id]['code']}):")
            for table in TENANT_TABLES:
                print(
                    f"  {table}: "
                    f"{table_count(db, schema, table)}"
                )

        print("\nMaster database:")
        print(
            "  SuperAdmin:",
            table_count(db, "masterdb", "SuperAdmin"),
        )
        print(
            "  AuthSession:",
            table_count(db, "masterdb", "AuthSession"),
        )

        print("\nLegacy audit.db was not modified by this script.")
        print("Legacy login tokens were not copied.")

    except Exception:
        if db.in_transaction:
            db.rollback()

        print("\nMIGRATION FAILED — transaction rolled back.")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    migrate()
