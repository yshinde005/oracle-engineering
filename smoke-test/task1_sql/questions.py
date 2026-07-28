"""30 natural-language questions with golden SQL.

Golden SQL is authoritative: executing it against the database
gives the expected result. The oracle compares generated SQL output
against these expected results.
"""

QUESTIONS = [
    # ── EASY (single-table, simple aggregation) ──────────────────────────
    {
        "id": "q01",
        "difficulty": "easy",
        "question": "How many employees are there in total?",
        "golden_sql": "SELECT COUNT(*) FROM employees;",
    },
    {
        "id": "q02",
        "difficulty": "easy",
        "question": "List all department names and their budgets, ordered alphabetically by name.",
        "golden_sql": "SELECT name, budget FROM departments ORDER BY name;",
    },
    {
        "id": "q03",
        "difficulty": "easy",
        "question": "What are the names of all active projects, ordered alphabetically?",
        "golden_sql": "SELECT name FROM projects WHERE status = 'active' ORDER BY name;",
    },
    {
        "id": "q04",
        "difficulty": "easy",
        "question": "What is the salary of Alice Chen?",
        "golden_sql": "SELECT salary FROM employees WHERE name = 'Alice Chen';",
    },
    {
        "id": "q05",
        "difficulty": "easy",
        "question": "How many departments are there?",
        "golden_sql": "SELECT COUNT(*) FROM departments;",
    },
    # ── MEDIUM (joins, aggregations, filtering) ───────────────────────────
    {
        "id": "q06",
        "difficulty": "medium",
        "question": (
            "How many employees are in each department? "
            "Return department name and employee count, ordered by department name."
        ),
        "golden_sql": """
SELECT d.name, COUNT(e.id) AS employee_count
FROM departments d
LEFT JOIN employees e ON d.id = e.dept_id
GROUP BY d.id, d.name
ORDER BY d.name;
""".strip(),
    },
    {
        "id": "q07",
        "difficulty": "medium",
        "question": "Which department has the highest average employee salary? Return only the department name.",
        "golden_sql": """
SELECT d.name
FROM departments d
JOIN employees e ON d.id = e.dept_id
GROUP BY d.id, d.name
ORDER BY AVG(e.salary) DESC
LIMIT 1;
""".strip(),
    },
    {
        "id": "q08",
        "difficulty": "medium",
        "question": "List the names and hire dates of employees hired after January 1, 2022, ordered by hire date.",
        "golden_sql": """
SELECT name, hire_date
FROM employees
WHERE hire_date > '2022-01-01'
ORDER BY hire_date;
""".strip(),
    },
    {
        "id": "q09",
        "difficulty": "medium",
        "question": "What is the total number of hours worked on the 'Platform Redesign' project?",
        "golden_sql": """
SELECT SUM(a.hours)
FROM assignments a
JOIN projects p ON a.project_id = p.id
WHERE p.name = 'Platform Redesign';
""".strip(),
    },
    {
        "id": "q10",
        "difficulty": "medium",
        "question": "Which employees are assigned to the 'Sales Automation' project? Return their names, ordered alphabetically.",
        "golden_sql": """
SELECT e.name
FROM employees e
JOIN assignments a ON e.id = a.employee_id
JOIN projects p ON a.project_id = p.id
WHERE p.name = 'Sales Automation'
ORDER BY e.name;
""".strip(),
    },
    {
        "id": "q11",
        "difficulty": "medium",
        "question": "What is the average salary across all employees? Round to 2 decimal places.",
        "golden_sql": "SELECT ROUND(AVG(salary), 2) FROM employees;",
    },
    {
        "id": "q12",
        "difficulty": "medium",
        "question": "Which projects have no assignments at all? Return project names ordered alphabetically.",
        "golden_sql": """
SELECT p.name
FROM projects p
LEFT JOIN assignments a ON p.id = a.project_id
WHERE a.employee_id IS NULL
ORDER BY p.name;
""".strip(),
    },
    {
        "id": "q13",
        "difficulty": "medium",
        "question": "What is the maximum salary among employees in the Sales department?",
        "golden_sql": """
SELECT MAX(e.salary)
FROM employees e
JOIN departments d ON e.dept_id = d.id
WHERE d.name = 'Sales';
""".strip(),
    },
    {
        "id": "q14",
        "difficulty": "medium",
        "question": "How many employees earn more than $100,000?",
        "golden_sql": "SELECT COUNT(*) FROM employees WHERE salary > 100000;",
    },
    {
        "id": "q15",
        "difficulty": "medium",
        "question": "List all distinct roles that appear in the assignments table, ordered alphabetically.",
        "golden_sql": "SELECT DISTINCT role FROM assignments ORDER BY role;",
    },
    # ── HARD (subqueries, multi-join, correlated queries) ─────────────────
    {
        "id": "q16",
        "difficulty": "hard",
        "question": (
            "List employees who are assigned to more than 2 active projects, "
            "along with their total hours across ALL their assignments (not just active). "
            "Order by total hours descending."
        ),
        "golden_sql": """
SELECT e.name, SUM(a.hours) AS total_hours
FROM employees e
JOIN assignments a ON e.id = a.employee_id
WHERE e.id IN (
    SELECT a2.employee_id
    FROM assignments a2
    JOIN projects p2 ON a2.project_id = p2.id
    WHERE p2.status = 'active'
    GROUP BY a2.employee_id
    HAVING COUNT(*) > 2
)
GROUP BY e.id, e.name
ORDER BY total_hours DESC;
""".strip(),
    },
    {
        "id": "q17",
        "difficulty": "hard",
        "question": (
            "For each department, show department name, number of employees, "
            "and total salary expenditure. Include departments with no employees. "
            "Order by total salary descending."
        ),
        "golden_sql": """
SELECT d.name,
       COUNT(e.id) AS emp_count,
       COALESCE(SUM(e.salary), 0) AS total_salary
FROM departments d
LEFT JOIN employees e ON d.id = e.dept_id
GROUP BY d.id, d.name
ORDER BY total_salary DESC;
""".strip(),
    },
    {
        "id": "q18",
        "difficulty": "hard",
        "question": (
            "Find employees who earn more than the average salary of their own department. "
            "Return name, salary, and department name, ordered by employee name."
        ),
        "golden_sql": """
SELECT e.name, e.salary, d.name AS dept_name
FROM employees e
JOIN departments d ON e.dept_id = d.id
WHERE e.salary > (
    SELECT AVG(e2.salary)
    FROM employees e2
    WHERE e2.dept_id = e.dept_id
)
ORDER BY e.name;
""".strip(),
    },
    {
        "id": "q19",
        "difficulty": "hard",
        "question": "Which departments have more than 4 employees? Return name and employee count, ordered by count descending.",
        "golden_sql": """
SELECT d.name, COUNT(e.id) AS emp_count
FROM departments d
JOIN employees e ON d.id = e.dept_id
GROUP BY d.id, d.name
HAVING COUNT(e.id) > 4
ORDER BY emp_count DESC;
""".strip(),
    },
    {
        "id": "q20",
        "difficulty": "hard",
        "question": "List employees who are not assigned to any project, ordered alphabetically.",
        "golden_sql": """
SELECT e.name
FROM employees e
LEFT JOIN assignments a ON e.id = a.employee_id
WHERE a.employee_id IS NULL
ORDER BY e.name;
""".strip(),
    },
    {
        "id": "q21",
        "difficulty": "hard",
        "question": "What is the total budget of all departments that have at least one active project?",
        "golden_sql": """
SELECT SUM(d.budget)
FROM departments d
WHERE d.id IN (
    SELECT DISTINCT dept_id FROM projects WHERE status = 'active'
);
""".strip(),
    },
    {
        "id": "q22",
        "difficulty": "hard",
        "question": (
            "For each active project, find the employee with the most hours assigned to it. "
            "Return project name, employee name, and hours. Order by project name."
        ),
        "golden_sql": """
SELECT p.name AS project_name, e.name AS employee_name, a.hours
FROM projects p
JOIN assignments a ON p.id = a.project_id
JOIN employees e ON a.employee_id = e.id
WHERE p.status = 'active'
  AND a.hours = (
      SELECT MAX(a2.hours)
      FROM assignments a2
      WHERE a2.project_id = p.id
  )
ORDER BY p.name;
""".strip(),
    },
    {
        "id": "q23",
        "difficulty": "hard",
        "question": (
            "List employees who are assigned to at least one project that belongs to a "
            "department different from their own. Return distinct employee names, ordered alphabetically."
        ),
        "golden_sql": """
SELECT DISTINCT e.name
FROM employees e
JOIN assignments a ON e.id = a.employee_id
JOIN projects p ON a.project_id = p.id
WHERE p.dept_id != e.dept_id
ORDER BY e.name;
""".strip(),
    },
    {
        "id": "q24",
        "difficulty": "hard",
        "question": (
            "What is the average hours per assignment for each project status? "
            "Return status and average hours rounded to 2 decimal places, ordered by status."
        ),
        "golden_sql": """
SELECT p.status, ROUND(AVG(a.hours), 2) AS avg_hours
FROM assignments a
JOIN projects p ON a.project_id = p.id
GROUP BY p.status
ORDER BY p.status;
""".strip(),
    },
    {
        "id": "q25",
        "difficulty": "hard",
        "question": "Which employee has the most project assignments? Return their name and count.",
        "golden_sql": """
SELECT e.name, COUNT(a.project_id) AS num_projects
FROM employees e
JOIN assignments a ON e.id = a.employee_id
GROUP BY e.id, e.name
ORDER BY num_projects DESC, e.name
LIMIT 1;
""".strip(),
    },
    # ── EDGE CASES ────────────────────────────────────────────────────────
    {
        "id": "q26",
        "difficulty": "edge",
        "question": "Which departments have no employees at all? Return department names ordered alphabetically.",
        "golden_sql": """
SELECT d.name
FROM departments d
LEFT JOIN employees e ON d.id = e.dept_id
WHERE e.id IS NULL
ORDER BY d.name;
""".strip(),
    },
    {
        "id": "q27",
        "difficulty": "edge",
        "question": "How many employees were hired in the year 2022?",
        "golden_sql": "SELECT COUNT(*) FROM employees WHERE hire_date LIKE '2022-%';",
    },
    {
        "id": "q28",
        "difficulty": "edge",
        "question": "List employee names that contain the letters 'an' (case-insensitive), ordered alphabetically.",
        "golden_sql": "SELECT name FROM employees WHERE LOWER(name) LIKE '%an%' ORDER BY name;",
    },
    {
        "id": "q29",
        "difficulty": "edge",
        "question": "What fraction of all projects are active? Return as a decimal rounded to 4 places.",
        "golden_sql": """
SELECT ROUND(
    CAST(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS REAL) / COUNT(*),
    4
) AS active_ratio
FROM projects;
""".strip(),
    },
    {
        "id": "q30",
        "difficulty": "edge",
        "question": "List all projects with their department name, start date, and status, ordered by start date.",
        "golden_sql": """
SELECT p.name, d.name AS dept_name, p.start_date, p.status
FROM projects p
JOIN departments d ON p.dept_id = d.id
ORDER BY p.start_date;
""".strip(),
    },
]
