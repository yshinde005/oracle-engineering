"""SQLite database: schema, seed data, and query utilities."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "results" / "company.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    id     INTEGER PRIMARY KEY,
    name   TEXT    NOT NULL,
    budget REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    id        INTEGER PRIMARY KEY,
    name      TEXT    NOT NULL,
    dept_id   INTEGER REFERENCES departments(id),
    salary    REAL    NOT NULL,
    hire_date TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    dept_id    INTEGER REFERENCES departments(id),
    start_date TEXT    NOT NULL,
    status     TEXT    NOT NULL CHECK(status IN ('active', 'completed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS assignments (
    employee_id INTEGER REFERENCES employees(id),
    project_id  INTEGER REFERENCES projects(id),
    role        TEXT    NOT NULL,
    hours       REAL    NOT NULL,
    PRIMARY KEY (employee_id, project_id)
);
"""

SCHEMA_DESCRIPTION = """
Tables:
  departments(id, name, budget)
  employees(id, name, dept_id, salary, hire_date)
    dept_id → departments.id
  projects(id, name, dept_id, start_date, status)
    dept_id → departments.id
    status ∈ {'active', 'completed', 'cancelled'}
  assignments(employee_id, project_id, role, hours)
    employee_id → employees.id, project_id → projects.id
    PRIMARY KEY (employee_id, project_id)

All dates are ISO 8601 strings (YYYY-MM-DD).
""".strip()

DEPARTMENTS = [
    (1, "Engineering", 500000),
    (2, "Sales",       300000),
    (3, "Marketing",   200000),
    (4, "HR",          150000),
    (5, "Research",    100000),   # intentionally has no employees
]

EMPLOYEES = [
    (1,  "Alice Chen",      1, 120000, "2020-03-15"),
    (2,  "Bob Smith",       1, 110000, "2021-07-01"),
    (3,  "Carol White",     1,  95000, "2022-01-10"),
    (4,  "Dave Johnson",    1, 130000, "2019-08-20"),
    (5,  "Eve Martinez",    1, 105000, "2023-02-28"),
    (6,  "Frank Lee",       2,  85000, "2020-11-15"),
    (7,  "Grace Kim",       2,  90000, "2021-04-01"),
    (8,  "Henry Park",      2,  78000, "2022-09-12"),
    (9,  "Iris Tang",       2,  92000, "2020-06-30"),
    (10, "Jack Brown",      2,  82000, "2023-05-01"),
    (11, "Kate Anderson",   3,  88000, "2021-01-15"),
    (12, "Liam Wilson",     3,  82000, "2022-03-20"),
    (13, "Mia Davis",       3,  76000, "2023-07-08"),
    (14, "Noah Garcia",     3,  80000, "2021-11-30"),
    (15, "Olivia Taylor",   4,  72000, "2020-04-22"),
    (16, "Peter Moore",     4,  68000, "2022-06-15"),
    (17, "Quinn Jackson",   4,  75000, "2021-09-01"),
    (18, "Rachel Harris",   4,  70000, "2023-01-20"),
    (19, "Sam Lewis",       1, 118000, "2020-01-05"),
    (20, "Tom Clark",       2,  86000, "2022-08-18"),
]

PROJECTS = [
    (1, "Platform Redesign",    1, "2023-01-01", "active"),
    (2, "Sales Automation",     2, "2023-03-01", "active"),
    (3, "Marketing Rebranding", 3, "2023-06-01", "active"),
    (4, "HR System Upgrade",    4, "2022-01-01", "completed"),
    (5, "Data Pipeline",        1, "2022-06-01", "completed"),
    (6, "Mobile App",           1, "2023-09-01", "active"),
    (7, "CRM Integration",      2, "2022-03-01", "cancelled"),
    (8, "Analytics Dashboard",  1, "2024-01-01", "active"),
    (9, "Website Refresh",      3, "2024-03-01", "active"),  # no assignments (for Q12)
]

# (employee_id, project_id, role, hours)
ASSIGNMENTS = [
    (1,  1, "Tech Lead",       200),
    (2,  1, "Developer",       150),
    (3,  1, "Developer",       120),
    (19, 1, "Developer",       130),
    (1,  3, "Tech Advisor",     40),  # Alice cross-dept (Marketing Rebranding)
    (1,  6, "Reviewer",         50),
    (2,  6, "Developer",        80),
    (5,  6, "Developer",       180),
    (19, 6, "Developer",       100),
    (1,  8, "Tech Lead",       100),
    (4,  8, "Architect",        80),
    (5,  8, "Developer",        60),
    (19, 8, "Developer",        40),
    (4,  5, "Tech Lead",       300),
    (19, 5, "Developer",       220),
    (6,  5, "Business Analyst", 30),  # Frank cross-dept (Data Pipeline)
    (6,  2, "Sales Lead",      160),
    (7,  2, "Sales Rep",       140),
    (9,  2, "Sales Lead",      170),
    (10, 2, "Sales Rep",       110),
    (6,  7, "Sales Rep",        60),
    (8,  7, "Sales Rep",        90),
    (11, 3, "Marketing Lead",  200),
    (12, 3, "Designer",        180),
    (13, 3, "Copywriter",      150),
    (15, 4, "PM",              250),
    (16, 4, "HR Analyst",      200),
]


def get_connection(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_and_seed(path: Path = DB_PATH) -> sqlite3.Connection:
    """Create the database from scratch and seed all data. Idempotent."""
    if path.exists():
        path.unlink()
    conn = get_connection(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO departments VALUES (?,?,?)", DEPARTMENTS
    )
    conn.executemany(
        "INSERT INTO employees VALUES (?,?,?,?,?)", EMPLOYEES
    )
    conn.executemany(
        "INSERT INTO projects VALUES (?,?,?,?,?)", PROJECTS
    )
    conn.executemany(
        "INSERT INTO assignments VALUES (?,?,?,?)", ASSIGNMENTS
    )
    conn.commit()
    return conn


def run_query(sql: str, conn: sqlite3.Connection | None = None) -> list[tuple]:
    """Execute a SELECT and return rows as plain tuples."""
    close_after = conn is None
    if conn is None:
        conn = get_connection()
    try:
        cur = conn.execute(sql)
        return [tuple(row) for row in cur.fetchall()]
    finally:
        if close_after:
            conn.close()


def run_query_safe(sql: str, conn: sqlite3.Connection | None = None) -> tuple[list[tuple] | None, str | None]:
    """Execute a SELECT; returns (rows, None) or (None, error_message)."""
    close_after = conn is None
    if conn is None:
        conn = get_connection()
    try:
        cur = conn.execute(sql)
        return [tuple(row) for row in cur.fetchall()], None
    except Exception as e:
        return None, str(e)
    finally:
        if close_after:
            conn.close()


if __name__ == "__main__":
    conn = create_and_seed()
    print("Database created at", DB_PATH)
    rows = run_query("SELECT COUNT(*) FROM employees", conn)
    print(f"  Employees: {rows[0][0]}")
    rows = run_query("SELECT COUNT(*) FROM projects", conn)
    print(f"  Projects: {rows[0][0]}")
    rows = run_query("SELECT COUNT(*) FROM assignments", conn)
    print(f"  Assignments: {rows[0][0]}")
    conn.close()
