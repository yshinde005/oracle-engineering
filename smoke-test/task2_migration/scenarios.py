"""12 schema migration scenarios built on the Task 1 database.

Each scenario specifies:
  current_schema  — the relevant part of the current schema
  target_schema   — the desired end state
  constraints     — invariants the migration must preserve
  affected_tables — ground-truth set of tables the plan MUST address
  affected_cols   — ground-truth set of (table, column) pairs affected

The affected_tables / affected_cols fields are the oracle's answer key for Check A.
They are NOT given to the generator or mirror.
"""

CURRENT_SCHEMA = """
departments(id INTEGER PK, name TEXT, budget REAL)
employees(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, salary REAL, hire_date TEXT)
projects(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, start_date TEXT, status TEXT CHECK('active','completed','cancelled'))
assignments(employee_id INTEGER FK→employees.id, project_id INTEGER FK→projects.id, role TEXT, hours REAL, PK(employee_id,project_id))
""".strip()

SCENARIOS = [
    # ── SIMPLE ──────────────────────────────────────────────────────────
    {
        "id": "s01",
        "complexity": "simple",
        "title": "Add nullable email column to employees",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": CURRENT_SCHEMA.replace(
            "employees(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, salary REAL, hire_date TEXT)",
            "employees(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, salary REAL, hire_date TEXT, email TEXT NULL)"
        ),
        "constraints": ["Zero downtime", "Existing rows get NULL email", "Rollback required"],
        "affected_tables": ["employees"],
        "affected_cols": [("employees", "email")],
        "notes": "Simplest case: single nullable column addition.",
    },
    {
        "id": "s02",
        "complexity": "simple",
        "title": "Add budget_used column to departments with a default of 0",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": CURRENT_SCHEMA.replace(
            "departments(id INTEGER PK, name TEXT, budget REAL)",
            "departments(id INTEGER PK, name TEXT, budget REAL, budget_used REAL NOT NULL DEFAULT 0)"
        ),
        "constraints": ["All existing rows must have budget_used = 0", "Rollback required"],
        "affected_tables": ["departments"],
        "affected_cols": [("departments", "budget_used")],
        "notes": "NOT NULL with default — tests whether the plan handles backfill.",
    },
    {
        "id": "s03",
        "complexity": "simple",
        "title": "Add end_date column to projects",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": CURRENT_SCHEMA.replace(
            "projects(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, start_date TEXT, status TEXT CHECK('active','completed','cancelled'))",
            "projects(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, start_date TEXT, end_date TEXT NULL, status TEXT CHECK('active','completed','cancelled'))"
        ),
        "constraints": ["end_date NULL for active projects", "end_date should be populated for completed/cancelled"],
        "affected_tables": ["projects"],
        "affected_cols": [("projects", "end_date")],
        "notes": "Nullable column with conditional backfill (completed/cancelled rows).",
    },
    # ── MEDIUM ──────────────────────────────────────────────────────────
    {
        "id": "s04",
        "complexity": "medium",
        "title": "Rename hire_date to start_date in employees",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": CURRENT_SCHEMA.replace(
            "employees(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, salary REAL, hire_date TEXT)",
            "employees(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, salary REAL, start_date TEXT)"
        ),
        "constraints": [
            "All existing data must be preserved",
            "Any queries referencing hire_date must use start_date after migration",
            "Rollback required",
        ],
        "affected_tables": ["employees"],
        "affected_cols": [("employees", "hire_date"), ("employees", "start_date")],
        "notes": (
            "Column rename in SQLite requires table recreation. "
            "Also conflicts with projects.start_date — tests whether plan distinguishes them."
        ),
    },
    {
        "id": "s05",
        "complexity": "medium",
        "title": "Add unique department_code column to departments",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": CURRENT_SCHEMA.replace(
            "departments(id INTEGER PK, name TEXT, budget REAL)",
            "departments(id INTEGER PK, name TEXT, budget REAL, department_code TEXT NOT NULL UNIQUE)"
        ),
        "constraints": [
            "Must backfill department_code for all 5 existing departments",
            "Values must be unique (e.g. 'ENG', 'SALES', 'MKT', 'HR', 'RES')",
            "Rollback required",
        ],
        "affected_tables": ["departments"],
        "affected_cols": [("departments", "department_code")],
        "notes": "NOT NULL UNIQUE requires careful backfill before constraint is added.",
    },
    {
        "id": "s06",
        "complexity": "medium",
        "title": "Add manager_id self-reference to employees",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": CURRENT_SCHEMA.replace(
            "employees(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, salary REAL, hire_date TEXT)",
            "employees(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, salary REAL, hire_date TEXT, manager_id INTEGER NULL FK→employees.id)"
        ),
        "constraints": [
            "Self-referential FK (manager is also an employee)",
            "Top-level employees have manager_id NULL",
            "Rollback required",
        ],
        "affected_tables": ["employees"],
        "affected_cols": [("employees", "manager_id")],
        "notes": "Self-referential FK; tests whether plan understands the circular reference.",
    },
    # ── HARD ─────────────────────────────────────────────────────────────
    {
        "id": "s07",
        "complexity": "hard",
        "title": "Split employees into employees + employee_contacts",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": (
            CURRENT_SCHEMA.replace(
                "employees(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, salary REAL, hire_date TEXT)",
                "employees(id INTEGER PK, dept_id INTEGER FK→departments.id, salary REAL, hire_date TEXT)"
            )
            + "\nemployee_contacts(id INTEGER PK, employee_id INTEGER FK→employees.id, name TEXT, email TEXT NULL, phone TEXT NULL)"
        ),
        "constraints": [
            "All existing employee.name values must migrate to employee_contacts.name",
            "Data preservation: no row may be lost",
            "FKs must remain valid after migration",
            "Rollback: must recreate original employees table with name column",
        ],
        "affected_tables": ["employees", "employee_contacts"],
        "affected_cols": [
            ("employees", "name"),
            ("employee_contacts", "id"),
            ("employee_contacts", "employee_id"),
            ("employee_contacts", "name"),
        ],
        "notes": "Table split with data migration — high-risk, multi-step.",
    },
    {
        "id": "s08",
        "complexity": "hard",
        "title": "Change assignments.hours from REAL to INTEGER (truncating decimals)",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": CURRENT_SCHEMA.replace(
            "assignments(employee_id INTEGER FK→employees.id, project_id INTEGER FK→projects.id, role TEXT, hours REAL, PK(employee_id,project_id))",
            "assignments(employee_id INTEGER FK→employees.id, project_id INTEGER FK→projects.id, role TEXT, hours INTEGER, PK(employee_id,project_id))"
        ),
        "constraints": [
            "Existing fractional hour values must be truncated (not rounded) to INTEGER",
            "No rows may be lost",
            "Rollback required",
        ],
        "affected_tables": ["assignments"],
        "affected_cols": [("assignments", "hours")],
        "notes": "Type change with data conversion; tests whether plan includes CAST/TRUNC.",
    },
    {
        "id": "s09",
        "complexity": "hard",
        "title": "Normalize role in assignments into a lookup table",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": (
            CURRENT_SCHEMA.replace(
                "assignments(employee_id INTEGER FK→employees.id, project_id INTEGER FK→projects.id, role TEXT, hours REAL, PK(employee_id,project_id))",
                "assignments(employee_id INTEGER FK→employees.id, project_id INTEGER FK→projects.id, role_id INTEGER FK→roles.id, hours REAL, PK(employee_id,project_id))"
            )
            + "\nroles(id INTEGER PK, name TEXT NOT NULL UNIQUE)"
        ),
        "constraints": [
            "All distinct role strings in assignments must become rows in roles",
            "assignments.role column must be replaced by assignments.role_id (FK)",
            "All existing assignments must reference the correct role in roles",
            "Rollback: drop roles table, restore role TEXT column with original values",
        ],
        "affected_tables": ["assignments", "roles"],
        "affected_cols": [
            ("assignments", "role"),
            ("assignments", "role_id"),
            ("roles", "id"),
            ("roles", "name"),
        ],
        "notes": "Normalization: create lookup table, backfill FKs, drop original column.",
    },
    {
        "id": "s10",
        "complexity": "hard",
        "title": "Create salary_history table and backfill from current employee salaries",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": (
            CURRENT_SCHEMA
            + "\nsalary_history(id INTEGER PK AUTOINCREMENT, employee_id INTEGER FK→employees.id, salary REAL, effective_date TEXT, recorded_at TEXT)"
        ),
        "constraints": [
            "Current salary of each employee becomes the first salary_history entry",
            "effective_date = hire_date for the initial backfill",
            "recorded_at = current timestamp at migration time",
            "Rollback: drop salary_history table",
        ],
        "affected_tables": ["employees", "salary_history"],
        "affected_cols": [
            ("salary_history", "id"),
            ("salary_history", "employee_id"),
            ("salary_history", "salary"),
            ("salary_history", "effective_date"),
            ("salary_history", "recorded_at"),
        ],
        "notes": "Additive change (new table) + INSERT...SELECT for backfill.",
    },
    {
        "id": "s11",
        "complexity": "hard",
        "title": "Delete cancelled projects and clean up orphan assignments",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": CURRENT_SCHEMA,   # schema unchanged; data changes
        "constraints": [
            "All projects with status='cancelled' must be deleted",
            "All assignments referencing deleted projects must be deleted first (FK order)",
            "employees table is NOT modified",
            "Rollback: restore deleted rows from a backup",
        ],
        "affected_tables": ["projects", "assignments"],
        "affected_cols": [],  # data deletion, no schema change
        "notes": "FK ordering constraint: assignments must be deleted before projects.",
    },
    {
        "id": "s12",
        "complexity": "hard",
        "title": "Add priority column to projects with CHECK constraint",
        "current_schema": CURRENT_SCHEMA,
        "target_schema": CURRENT_SCHEMA.replace(
            "projects(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, start_date TEXT, status TEXT CHECK('active','completed','cancelled'))",
            "projects(id INTEGER PK, name TEXT, dept_id INTEGER FK→departments.id, start_date TEXT, status TEXT CHECK('active','completed','cancelled'), priority INTEGER NOT NULL DEFAULT 3 CHECK(priority BETWEEN 1 AND 5))"
        ),
        "constraints": [
            "All existing projects get priority = 3 (medium) by default",
            "Active projects should be reviewed and updated post-migration",
            "CHECK constraint must be enforced",
            "Rollback: drop the priority column",
        ],
        "affected_tables": ["projects"],
        "affected_cols": [("projects", "priority")],
        "notes": "Column with both DEFAULT and CHECK; SQLite CHECK constraints are permissive.",
    },
]
