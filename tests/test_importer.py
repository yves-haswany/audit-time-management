def test_all_mission_rows_imported(temp_env):
    from core.database import connect
    c = connect()
    n = c.execute("SELECT COUNT(*) FROM MissionTask").fetchone()[0]
    c.close()
    assert n == 129


def test_no_orphaned_tasks(temp_env):
    from core.database import connect
    c = connect()
    n = c.execute(
        "SELECT COUNT(*) FROM MissionTask WHERE EmployeeID IS NULL"
    ).fetchone()[0]
    c.close()
    assert n == 0


def test_toufic_created(temp_env):
    from core.database import connect
    c = connect()
    row = c.execute(
        "SELECT * FROM Employee WHERE EmployeeName = 'Toufic Antoine Daoud'"
    ).fetchone()
    c.close()
    assert row is not None