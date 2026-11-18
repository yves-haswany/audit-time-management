"""Import employees and missions from the Excel source files."""
import re
import os
import pandas as pd

from config import EMP_XLS, MIS_XLS, TEAMS_XLS, ALIASES, MISSING_EMPLOYEES
from core.database import connect
from core.security import hash_password


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def load_data(report: list) -> None:
    c = connect()

    # ---------- Employees ----------
    if c.execute("SELECT COUNT(*) FROM Employee").fetchone()[0] == 0:
        try:
            df = pd.read_excel(EMP_XLS)
        except Exception as e:
            raise RuntimeError(f"Could not read the Excel file: {e}")

        print(f"\n[DEBUG] Reading file: {EMP_XLS}")
        print(f"[DEBUG] Columns found: {df.columns.tolist()}\n")

        class_col = next((col for col in df.columns if str(col).strip().lower() == "classification"), None)

        for _, r in df.iterrows():
            name  = str(r["EmployeeName"]).strip()
            login = str(r["Login"]).strip()
            uname = str(r["Username"]).strip()

            classification = ""
            if class_col and pd.notna(r[class_col]):
                classification = str(r[class_col]).strip()

            c.execute(
                """INSERT OR IGNORE INTO Employee
                   (EmployeeName, LoginCode, Username, PasswordHash, Classification, TenantID)
                   VALUES (?,?,?,?,?,1)""",
                (name, login, uname, hash_password(login), classification),
            )

        for e in MISSING_EMPLOYEES:
            c.execute(
                """INSERT OR IGNORE INTO Employee
                   (EmployeeName, LoginCode, Username, PasswordHash, TenantID)
                   VALUES (?,?,?,?,1)""",
                (e["name"], e["login"], e["username"], hash_password(e["login"])),
            )
            report.append(("INFO", e["name"],
                           f"created employee (username {e['username']}) — confirm with HR"))

    # ---------- Team Leader Assignments ----------
    if os.path.exists(TEAMS_XLS):
        teams_df = pd.read_excel(TEAMS_XLS)
        print(f"\n[DEBUG] Reading teams from: {TEAMS_XLS}")
        for _, r in teams_df.iterrows():
            leader = str(r["Team Leader"]).strip()
            member = str(r["Team Member"]).strip()

            c.execute(
                "UPDATE Employee SET TeamLeader = ? WHERE LOWER(EmployeeName) = LOWER(?)",
                (leader, member)
            )
    else:
        print(f"\n[WARNING] Teams file not found at {TEAMS_XLS}. Team Leader assignments skipped.")

    emp = {_norm(r["EmployeeName"]): r["EmployeeID"]
           for r in c.execute("SELECT EmployeeID, EmployeeName FROM Employee")}

    # ---------- Missions + Tasks ----------
    if c.execute("SELECT COUNT(*) FROM MissionTask").fetchone()[0] == 0:
        df = pd.read_excel(MIS_XLS, sheet_name="Yves_TemplateMission")

        fiscal_col = next((col for col in df.columns if str(col).strip().lower() == "fiscal year"), None)

        for excel_row, r in df.iterrows():
            ws_str = str(r["Date1"])[:10]
            we_str = str(r["Date2"])[:10]

            fiscal_yr = ""
            if fiscal_col and pd.notna(r[fiscal_col]):
                fiscal_yr = str(r[fiscal_col]).strip()

            service_text = str(r["Service"]).strip()
            service_row = c.execute("SELECT ServiceID FROM Service WHERE TenantID=1 AND ServiceName = ?", (service_text,)).fetchone()

            if service_row:
                service_id = service_row["ServiceID"]
            else:
                c.execute("INSERT INTO Service (TenantID, ServiceName) VALUES (1, ?)", (service_text,))
                service_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

            c.execute(
                """INSERT OR IGNORE INTO Mission
                   (TenantID, IDHonorary, CustomerName, ServiceID, FiscalYear, WindowStart, WindowEnd)
                   VALUES (1, ?, ?, ?, ?, ?, ?)""",
                (int(r["IDHonorary"]),
                 str(r["Customer Name"]).strip(),
                 service_id,
                 fiscal_yr,
                 ws_str, we_str),
            )
            mid = c.execute(
                """SELECT MissionID FROM Mission
                   WHERE TenantID=1 AND IDHonorary=? AND CustomerName=?
                     AND WindowStart=? AND WindowEnd=?""",
                (int(r["IDHonorary"]),
                 str(r["Customer Name"]).strip(),
                 ws_str, we_str),
            ).fetchone()["MissionID"]

            raw = str(r["Team Member"]).strip()
            key = ALIASES.get(_norm(raw), _norm(raw))
            eid = emp.get(key)
            if eid is None:
                raise RuntimeError(
                    f"Row {excel_row + 2}: unknown team member '{raw}'. "
                    f"Fix the name or add it to ALIASES / MISSING_EMPLOYEES "
                    f"in config.py before starting."
                )

            task_name = ""
            if "TaskName" in df.columns:
                task_name = str(r["TaskName"]).strip()
            elif "SubSubSectionName" in df.columns:
                task_name = str(r["SubSubSectionName"]).strip()

            task_desc = ""
            if "TaskDescription" in df.columns:
                task_desc = str(r["TaskDescription"]).strip()
            elif "SectionName" in df.columns:
                section = str(r.get("SectionName", "")).strip()
                sub = str(r.get("SubSectionName", "")).strip()
                task_desc = f"{section} / {sub}" if section else sub

            c.execute(
                """INSERT OR IGNORE INTO MissionTask
                   (MissionID, TaskName, TaskDescription, TeamMemberName, EmployeeID, AllocatedHours, Date1, Date2, JobDesc, ExcelRow)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (mid,
                 task_name, task_desc,
                 raw, eid,
                 float(r["NbHours"]) if pd.notna(r["NbHours"]) else 0.0,
                 ws_str, we_str,
                 r.get("JobDesc"),
                 int(excel_row)),
            )

    c.commit()
    c.close()


# ============================================================
# NEW: Seed Industries from Excel
# ============================================================

# ============================================================
# NEW: Seed Industries from Excel
# ============================================================

def seed_industries_from_excel():
    """Populate Industry from data/Industry.xls (idempotent).

    Column names have changed over the years:
      - Old (2019):  ClientType | Industry
      - Mid:         IndustryGroup | Industry
      - New (2025):  IndustryName | IndustryGroup

    This function detects whichever pair is present and maps them:
      - group  → Industry.ClientType
      - name   → Industry.Industry
    """
    c = connect()
    inserted = 0
    skipped = 0
    try:
        df = pd.read_excel("data/Industry.xls", sheet_name="ClientType")
        df.columns = [str(col).strip() for col in df.columns]

        cols = set(df.columns)

        # Detect the group column (ClientType in old files, IndustryGroup in new)
        if "IndustryGroup" in cols:
            group_col = "IndustryGroup"
        elif "ClientType" in cols:
            group_col = "ClientType"
        else:
            print(f"[seed_industries] failed: no group column found in {sorted(cols)}")
            return

        # Detect the name column (Industry in old files, IndustryName in new)
        if "IndustryName" in cols:
            name_col = "IndustryName"
        elif "Industry" in cols:
            name_col = "Industry"
        else:
            print(f"[seed_industries] failed: no industry-name column found in {sorted(cols)}")
            return

        print(f"[seed_industries] using group='{group_col}', name='{name_col}'")

        for _, row in df.iterrows():
            client_type = str(row.get(group_col) or "").strip()
            industry    = str(row.get(name_col) or "").strip()

            if not industry or industry.lower() == "nan":
                skipped += 1
                continue
            if not client_type or client_type.lower() == "nan":
                client_type = "Other"

            cur = c.execute(
                "INSERT OR IGNORE INTO Industry (ClientType, Industry) VALUES (?, ?)",
                (client_type, industry),
            )
            if cur.rowcount > 0:
                inserted += 1

        c.commit()
        print(f"[seed_industries] inserted {inserted} new industries (skipped {skipped} empty rows)")
    except FileNotFoundError:
        print("[seed_industries] skipped — data/Industry.xls not found")
    except Exception as e:
        print(f"[seed_industries] failed: {e}")
    finally:
        c.close()
# ============================================================
# BACKFILL CLIENTS + LINK INDUSTRIES FROM EXISTING MISSIONS
# ============================================================

def seed_clients_from_missions():
    """Backfill the Client table from distinct customers in Mission (idempotent)."""
    c = connect()
    inserted = 0
    try:
        rows = c.execute("""
            SELECT DISTINCT CustomerName, MIN(IDHonorary) AS IDHonorary
            FROM Mission
            WHERE CustomerName IS NOT NULL AND CustomerName != ''
            GROUP BY CustomerName
        """).fetchall()

        for r in rows:
            cur = c.execute(
                """INSERT OR IGNORE INTO Client
                   (TenantID, CustomerName, IDHonorary)
                   VALUES (1, ?, ?)""",
                (r["CustomerName"], str(r["IDHonorary"]) if r["IDHonorary"] else None),
            )
            if cur.rowcount > 0:
                inserted += 1

        c.commit()
        print(f"[seed_clients] inserted {inserted} clients from missions")
    except Exception as e:
        print(f"[seed_clients] failed: {e}")
    finally:
        c.close()


def seed_industries_unclassified_fallback():
    """Ensure a generic 'Other / Unclassified' industry exists for clients
    whose industry can't be inferred. Safe to call every startup."""
    c = connect()
    try:
        c.execute(
            """INSERT OR IGNORE INTO Industry (ClientType, Industry)
               VALUES ('Other', 'Unclassified')"""
        )
        c.commit()
        row = c.execute(
            "SELECT IndustryID FROM Industry WHERE ClientType='Other' AND Industry='Unclassified'"
        ).fetchone()
        print(f"[seed_industries_fallback] 'Other / Unclassified' → IndustryID={row['IndustryID']}")
    except Exception as e:
        print(f"[seed_industries_fallback] failed: {e}")
    finally:
        c.close()


def link_clients_to_industries():
    """Assign every client without an IndustryID to 'Other / Unclassified'
    so the admin sees a complete Clients table. Idempotent."""
    c = connect()
    linked = 0
    try:
        fallback = c.execute(
            """SELECT IndustryID FROM Industry
               WHERE ClientType='Other' AND Industry='Unclassified'"""
        ).fetchone()
        if not fallback:
            print("[link_clients] no fallback industry — skipped")
            return
        fallback_id = fallback["IndustryID"]

        cur = c.execute(
            "UPDATE Client SET IndustryID = ? WHERE IndustryID IS NULL",
            (fallback_id,),
        )
        linked = cur.rowcount
        c.commit()
        print(f"[link_clients] assigned 'Other / Unclassified' to {linked} clients")
    except Exception as e:
        print(f"[link_clients] failed: {e}")
    finally:
        c.close()
def seed_services_from_excel():
    """Populate Service from data/Services.xls (idempotent).

    Expects columns: 'ServiceType' (name), 'Letter' (optional engagement letter).
    If a service already exists (e.g. Audit was created by the mission importer),
    it is left alone — INSERT OR IGNORE skips it via UNIQUE(TenantID, ServiceName).
    """
    c = connect()
    inserted = 0
    skipped = 0
    try:
        df = pd.read_excel("data/Services.xls", sheet_name="ServiceType")
        df.columns = [str(col).strip() for col in df.columns]

        cols = set(df.columns)

        # Detect the name column
        if "ServiceType" in cols:
            name_col = "ServiceType"
        elif "ServiceName" in cols:
            name_col = "ServiceName"
        elif "Service" in cols:
            name_col = "Service"
        else:
            print(f"[seed_services] failed: no service-name column found in {sorted(cols)}")
            return

        # Detect optional Letter column
        letter_col = "Letter" if "Letter" in cols else None

        for _, row in df.iterrows():
            name = str(row.get(name_col) or "").strip()
            if not name or name.lower() == "nan":
                skipped += 1
                continue

            letter = ""
            if letter_col:
                raw = row.get(letter_col)
                if raw is not None and str(raw).strip().lower() != "nan":
                    letter = str(raw)

            cur = c.execute(
                "INSERT OR IGNORE INTO Service (TenantID, ServiceName, Letter) VALUES (1, ?, ?)",
                (name, letter),
            )
            if cur.rowcount > 0:
                inserted += 1

        c.commit()
        print(f"[seed_services] inserted {inserted} new services (skipped {skipped} empty rows)")
    except FileNotFoundError:
        print("[seed_services] skipped — data/Services.xls not found")
    except Exception as e:
        print(f"[seed_services] failed: {e}")
    finally:
        c.close()
# ============================================================
# SEED: Section Catalog from Sections.xls
# ============================================================

def seed_sections_from_excel():
    """Populate SectionCatalog from data/Sections.xls (idempotent).

    Column names accepted:
      - Industry, Service, SectionName, SubSectionName, SubSubSectionName, Remarks, NbHours
    Rows with all three of SectionName / SubSectionName / SubSubSectionName empty
    are skipped (they carry no information).

    Does NOT touch MissionTask — existing missions are untouched.
    """
    c = connect()
    inserted = 0
    skipped = 0
    try:
        df = pd.read_excel("data/Sections.xls", sheet_name="SubSubSection")
        df.columns = [str(col).strip() for col in df.columns]

        def clean(v):
            if v is None:
                return ""
            s = str(v).strip()
            if s.lower() in ("nan", "none"):
                return ""
            return s

        for _, row in df.iterrows():
            industry = clean(row.get("Industry"))
            service  = clean(row.get("Service"))
            section  = clean(row.get("SectionName"))
            subsec   = clean(row.get("SubSectionName"))
            subsub   = clean(row.get("SubSubSectionName"))
            remarks  = clean(row.get("Remarks"))

            if not industry or not service:
                skipped += 1
                continue
            if not (section or subsec or subsub):
                skipped += 1
                continue

            hours = 1.0
            try:
                hv = row.get("NbHours")
                if hv is not None and str(hv).strip().lower() != "nan":
                    hours = float(hv)
            except Exception:
                pass

            cur = c.execute(
                """INSERT OR IGNORE INTO SectionCatalog
                   (Industry, Service, SectionName, SubSectionName, SubSubSectionName, Remarks, DefaultHours)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (industry, service, section, subsec, subsub, remarks, hours),
            )
            if cur.rowcount > 0:
                inserted += 1

        c.commit()
        print(f"[seed_sections] inserted {inserted} new catalog rows (skipped {skipped} empty rows)")
    except FileNotFoundError:
        print("[seed_sections] skipped — data/Sections.xls not found")
    except Exception as e:
        print(f"[seed_sections] failed: {e}")
    finally:
        c.close()
# ============================================================
# SEED: Customers from Customers.xls
# ============================================================

def seed_customers_from_excel():
    """Populate / enrich the Client table from data/Customers.xls (idempotent).

    Rules:
      - Match existing client by CustomerName (case-insensitive).
      - New client      → insert all fields.
      - Existing client → ONLY fill empty/NULL columns; never overwrite.
      - Skip 'ALREADY EXIST' and 'not available anymore' rows.
      - File's 'ClientType' column = INDUSTRY NAME; 'Industry' column = INDUSTRY GROUP.
    """
    c = connect()
    inserted = updated = skipped = 0
    try:
        df = pd.read_excel("data/Customers.xls", sheet_name="Customers")
        df.columns = [str(col).strip() for col in df.columns]

        def clean(v):
            if v is None: return ""
            s = str(v).strip()
            if s.lower() in ("nan", "none"): return ""
            return s

        def get_industry_id(name):
            if not name: return None
            r = c.execute(
                "SELECT IndustryID FROM Industry WHERE LOWER(Industry)=LOWER(?) LIMIT 1",
                (name,)
            ).fetchone()
            return r["IndustryID"] if r else None

        for _, row in df.iterrows():
            name = clean(row.get("Customer Name"))
            if not name:
                skipped += 1; continue

            industry_group_raw = clean(row.get("Industry"))
            if industry_group_raw.upper().startswith("ALREADY EXIST"):
                skipped += 1; continue
            if industry_group_raw.lower() == "not available anymore":
                skipped += 1; continue

            industry_name = clean(row.get("ClientType"))   # yes: file's ClientType = industry NAME
            industry_id   = get_industry_id(industry_name)

            values = {
                "IDHonorary":  clean(row.get("Customer ID")),
                "Contact":     clean(row.get("Salesman Name")),
                "Email":       clean(row.get("E-mail")),
                "Phone":       clean(row.get("Phone1")),
                "Phone2":      clean(row.get("Phone2")),
                "Address":     clean(row.get("Address")),
                "Building":    clean(row.get("Building")),
                "Street":      clean(row.get("Street")),
                "City":        clean(row.get("City")),
                "Region":      clean(row.get("Region")),
                "Country":     clean(row.get("COUNTRY")),
                "Nationality": clean(row.get("Nationality")),
                "ClientType":  industry_group_raw,   # the GROUP, stored as ClientType column
                "TeamLeader":  clean(row.get("Team Leader")),
            }

            existing = c.execute(
                "SELECT * FROM Client WHERE LOWER(CustomerName)=LOWER(?)",
                (name,)
            ).fetchone()

            if existing:
                sets, params = [], []
                for col, val in values.items():
                    if not val: continue
                    cur = existing[col]
                    if cur is None or str(cur).strip() == "":
                        sets.append(f"{col}=?"); params.append(val)
                if industry_id is not None and existing["IndustryID"] is None:
                    sets.append("IndustryID=?"); params.append(industry_id)
                if sets:
                    params.append(existing["ClientID"])
                    c.execute(f"UPDATE Client SET {', '.join(sets)} WHERE ClientID=?", tuple(params))
                    updated += 1
            else:
                c.execute(
                    """INSERT INTO Client
                       (TenantID, CustomerName, IDHonorary, Contact, Email,
                        Phone, Phone2, Address, Building, Street, City, Region,
                        Country, Nationality, ClientType, TeamLeader, IndustryID)
                       VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (name, values["IDHonorary"], values["Contact"], values["Email"],
                     values["Phone"], values["Phone2"], values["Address"],
                     values["Building"], values["Street"], values["City"],
                     values["Region"], values["Country"], values["Nationality"],
                     values["ClientType"], values["TeamLeader"], industry_id),
                )
                inserted += 1

        c.commit()
        print(f"[seed_customers] inserted {inserted}, enriched {updated}, skipped {skipped}")
    except FileNotFoundError:
        print("[seed_customers] skipped — data/Customers.xls not found")
    except Exception as e:
        print(f"[seed_customers] failed: {e}")
    finally:
        c.close()