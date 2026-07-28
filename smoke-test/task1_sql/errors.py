"""12 seeded error SQL samples.

Each is a deliberately wrong version of a question's golden SQL.
Error types are chosen so the SQL runs without syntax errors but
returns the wrong result — the class of error the mirror is expected to miss.

Mirror-miss rationale per error type:
  wrong_aggregation  — SQL looks semantically correct; wrong function is plausible
  wrong_ordering     — ASC vs DESC is syntactically identical; mirror may not check direction
  wrong_null_check   — IS NULL vs IS NOT NULL in WHERE; mirror often treats as equivalent
  wrong_join_type    — LEFT vs INNER JOIN; both produce valid SQL; mirror misses row loss
  no_active_filter   — missing WHERE clause change; plausible-looking subquery
  global_vs_dept_avg — correct correlated structure but wrong scope for subquery
  missing_having     — HAVING removed; returns superset; looks structurally correct
  wrong_agg_in_subq  — MIN vs MAX inside correlated subquery; easy to overlook
  budget_overcounting — missing DISTINCT causes budget to be counted multiple times
  wrong_year         — off-by-one year in LIKE pattern; mirror rarely checks literals
  wrong_pattern      — '%en%' vs '%an%' in LIKE; subtle character swap
  wrong_threshold    — 90000 vs 100000 cutoff; mirror rarely verifies specific constants
"""

SEEDED_ERRORS = [
    # ── E01: wrong aggregation function (COUNT vs SUM) ───────────────────
    {
        "id": "e01",
        "question_id": "q09",
        "error_type": "wrong_aggregation",
        "description": "Uses COUNT(hours) instead of SUM(hours) for total hours",
        "sql": """
SELECT COUNT(a.hours)
FROM assignments a
JOIN projects p ON a.project_id = p.id
WHERE p.name = 'Platform Redesign';
""".strip(),
    },

    # ── E02: wrong ordering direction (ASC vs DESC) ───────────────────────
    {
        "id": "e02",
        "question_id": "q07",
        "error_type": "wrong_ordering",
        "description": "Uses ASC instead of DESC, returns department with LOWEST avg salary",
        "sql": """
SELECT d.name
FROM departments d
JOIN employees e ON d.id = e.dept_id
GROUP BY d.id, d.name
ORDER BY AVG(e.salary) ASC
LIMIT 1;
""".strip(),
    },

    # ── E03: wrong null check (IS NOT NULL instead of IS NULL) ────────────
    {
        "id": "e03",
        "question_id": "q20",
        "error_type": "wrong_null_check",
        "description": "IS NOT NULL instead of IS NULL; returns assigned employees instead of unassigned",
        "sql": """
SELECT e.name
FROM employees e
LEFT JOIN assignments a ON e.id = a.employee_id
WHERE a.employee_id IS NOT NULL
ORDER BY e.name;
""".strip(),
    },

    # ── E04: wrong null check on Q12 ─────────────────────────────────────
    {
        "id": "e04",
        "question_id": "q12",
        "error_type": "wrong_null_check",
        "description": "IS NOT NULL instead of IS NULL; returns projects WITH assignments",
        "sql": """
SELECT p.name
FROM projects p
LEFT JOIN assignments a ON p.id = a.project_id
WHERE a.employee_id IS NOT NULL
ORDER BY p.name;
""".strip(),
    },

    # ── E05: wrong join type loses rows (INNER vs LEFT JOIN) ──────────────
    {
        "id": "e05",
        "question_id": "q06",
        "error_type": "wrong_join_type",
        "description": "INNER JOIN excludes Research (0 employees); LEFT JOIN required",
        "sql": """
SELECT d.name, COUNT(e.id) AS employee_count
FROM departments d
INNER JOIN employees e ON d.id = e.dept_id
GROUP BY d.id, d.name
ORDER BY d.name;
""".strip(),
    },

    # ── E06: missing active-project filter in subquery ────────────────────
    {
        "id": "e06",
        "question_id": "q16",
        "error_type": "no_active_filter",
        "description": "Counts ALL project assignments per employee, not just active projects",
        "sql": """
SELECT e.name, SUM(a.hours) AS total_hours
FROM employees e
JOIN assignments a ON e.id = a.employee_id
WHERE e.id IN (
    SELECT a2.employee_id
    FROM assignments a2
    GROUP BY a2.employee_id
    HAVING COUNT(*) > 2
)
GROUP BY e.id, e.name
ORDER BY total_hours DESC;
""".strip(),
    },

    # ── E07: global average instead of per-dept average ───────────────────
    {
        "id": "e07",
        "question_id": "q18",
        "error_type": "global_vs_dept_avg",
        "description": "Compares against global average salary, not each employee's department average",
        "sql": """
SELECT e.name, e.salary, d.name AS dept_name
FROM employees e
JOIN departments d ON e.dept_id = d.id
WHERE e.salary > (SELECT AVG(salary) FROM employees)
ORDER BY e.name;
""".strip(),
    },

    # ── E08: missing HAVING clause returns all departments ────────────────
    {
        "id": "e08",
        "question_id": "q19",
        "error_type": "missing_having",
        "description": "Missing HAVING COUNT > 4; returns all departments with employees",
        "sql": """
SELECT d.name, COUNT(e.id) AS emp_count
FROM departments d
JOIN employees e ON d.id = e.dept_id
GROUP BY d.id, d.name
ORDER BY emp_count DESC;
""".strip(),
    },

    # ── E09: MIN instead of MAX in correlated subquery ────────────────────
    {
        "id": "e09",
        "question_id": "q22",
        "error_type": "wrong_agg_in_subq",
        "description": "MIN(hours) instead of MAX(hours); returns employee with FEWEST hours per project",
        "sql": """
SELECT p.name AS project_name, e.name AS employee_name, a.hours
FROM projects p
JOIN assignments a ON p.id = a.project_id
JOIN employees e ON a.employee_id = e.id
WHERE p.status = 'active'
  AND a.hours = (
      SELECT MIN(a2.hours)
      FROM assignments a2
      WHERE a2.project_id = p.id
  )
ORDER BY p.name;
""".strip(),
    },

    # ── E10: budget counted multiple times without DISTINCT ───────────────
    {
        "id": "e10",
        "question_id": "q21",
        "error_type": "budget_overcounting",
        "description": "JOIN without dedup: Engineering budget (3 active projects) counted 3×",
        "sql": """
SELECT SUM(d.budget)
FROM departments d
JOIN projects p ON d.id = p.dept_id
WHERE p.status = 'active';
""".strip(),
    },

    # ── E11: off-by-one year in LIKE pattern ──────────────────────────────
    {
        "id": "e11",
        "question_id": "q27",
        "error_type": "wrong_year",
        "description": "Uses '2023-%' instead of '2022-%'; counts 2023 hires (4) not 2022 (5)",
        "sql": "SELECT COUNT(*) FROM employees WHERE hire_date LIKE '2023-%';",
    },

    # ── E12: wrong LIKE pattern character ─────────────────────────────────
    {
        "id": "e12",
        "question_id": "q28",
        "error_type": "wrong_pattern",
        "description": "Searches for '%en%' instead of '%an%'; returns different names",
        "sql": "SELECT name FROM employees WHERE LOWER(name) LIKE '%en%' ORDER BY name;",
    },
]
