"""Oracle for Task 2: four structural checks, no LLM calls.

Check A — Completeness:   plan mentions all affected tables/columns from the schema diff
Check B — Step ordering:  dependency graph is acyclic and satisfied before use (structured only)
Check C — Rollback:       each destructive forward step has a corresponding rollback
Check D — SQL execution:  extracted SQL runs without errors against a test DB copy

Independence: pure code (set ops, regex, graph, SQLite execution). No LLM.

Coverage:
  A: catches missing-step errors (incomplete plan)
  B: catches ordering violations (structured mode only; abstains on prose)
  C: catches missing rollback errors
  D: catches SQL syntax/semantic errors

Blind spots:
  A: false positives if plan mentions a table for an unrelated reason
  B: dependency inference from prose is unreliable → abstain
  C: structural matching, not semantic; may miss logically wrong rollbacks
  D: cannot catch errors that produce syntactically valid but semantically wrong SQL
"""
import re
import shutil
import sqlite3
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_identifiers(text: str) -> set[str]:
    """Extract table and column name candidates from text (case-insensitive)."""
    # Look for SQL keywords followed by identifiers, quoted identifiers, and bare words
    candidates = set()
    # SQL keyword patterns: TABLE foo, COLUMN foo, INTO foo, FROM foo, JOIN foo, ALTER foo
    kw_pattern = re.compile(
        r'\b(?:TABLE|INTO|FROM|JOIN|ALTER|CREATE|DROP|ADD|COLUMN|UPDATE|ON)\s+`?([A-Za-z_][A-Za-z0-9_]*)`?',
        re.IGNORECASE
    )
    for m in kw_pattern.finditer(text):
        candidates.add(m.group(1).lower())

    # table.column patterns
    dot_pattern = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b')
    for m in dot_pattern.finditer(text):
        candidates.add(m.group(1).lower())
        candidates.add(m.group(2).lower())

    return candidates


def _extract_sql_blocks(text: str) -> list[str]:
    """Extract SQL statements from prose text (code blocks first, then heuristics)."""
    statements = []

    # Fenced code blocks
    block_pattern = re.compile(r'```(?:sql)?\s*(.*?)```', re.DOTALL | re.IGNORECASE)
    for block in block_pattern.finditer(text):
        content = block.group(1).strip()
        for stmt in re.split(r';\s*\n', content):
            stmt = stmt.strip()
            if stmt and re.match(r'^(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|BEGIN|WITH)\b',
                                  stmt, re.IGNORECASE):
                statements.append(stmt.rstrip(";") + ";")

    # If no fenced blocks, look for inline SQL-like lines
    if not statements:
        sql_keywords = re.compile(
            r'^(SELECT|INSERT|UPDATE|DELETE|CREATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE)',
            re.IGNORECASE
        )
        for line in text.splitlines():
            line = line.strip()
            if sql_keywords.match(line) and len(line) > 15:
                statements.append(line.rstrip(";") + ";")

    return statements


# ── Check A — Completeness ────────────────────────────────────────────────────

def check_a_completeness_prose(plan_text: str, scenario: dict) -> dict:
    """Check that the prose plan mentions all affected tables and columns."""
    affected_tables = set(t.lower() for t in scenario["affected_tables"])
    affected_cols = set(col.lower() for _, col in scenario["affected_cols"])

    plan_lower = plan_text.lower()
    mentioned = _extract_identifiers(plan_text)

    missing_tables = affected_tables - mentioned
    missing_cols = affected_cols - mentioned

    # Also do simple substring search as fallback
    for t in list(missing_tables):
        if t in plan_lower:
            missing_tables.discard(t)
    for c in list(missing_cols):
        if c in plan_lower:
            missing_cols.discard(c)

    passed = len(missing_tables) == 0 and len(missing_cols) == 0
    return {
        "passed": passed,
        "missing_tables": sorted(missing_tables),
        "missing_cols": sorted(missing_cols),
        "check": "A-completeness-prose",
    }


def check_a_completeness_structured(plan: dict, scenario: dict) -> dict:
    """Check A on structured JSON: read affected_tables / affected_columns fields."""
    required_tables = set(t.lower() for t in scenario["affected_tables"])
    required_cols: set[str] = set()
    for table, col in scenario["affected_cols"]:
        required_cols.add(col.lower())

    plan_tables = set(t.lower() for t in plan.get("affected_tables", []))
    plan_cols: set[str] = set()
    for table, cols in plan.get("affected_columns", {}).items():
        for col in cols:
            plan_cols.add(col.lower())

    missing_tables = required_tables - plan_tables
    missing_cols = required_cols - plan_cols

    passed = len(missing_tables) == 0 and len(missing_cols) == 0
    return {
        "passed": passed,
        "missing_tables": sorted(missing_tables),
        "missing_cols": sorted(missing_cols),
        "check": "A-completeness-structured",
    }


# ── Check B — Step ordering ───────────────────────────────────────────────────

def check_b_ordering_structured(plan: dict) -> dict:
    """Check B on structured JSON: topological sort on depends_on graph."""
    steps = plan.get("forward_steps", [])
    step_nums = {s["step"] for s in steps}

    # Build adjacency: step → set of steps it depends on
    depends: dict[int, set[int]] = {}
    for s in steps:
        deps = set(s.get("depends_on", []))
        # Filter out invalid references
        invalid_deps = deps - step_nums
        depends[s["step"]] = deps & step_nums

    # Kahn's algorithm for topological sort
    in_degree = {n: 0 for n in step_nums}
    for node, deps in depends.items():
        pass  # we invert below
    # Build reverse: dep → nodes that depend on it
    dependents: dict[int, set[int]] = {n: set() for n in step_nums}
    for node, deps in depends.items():
        for dep in deps:
            dependents[dep].add(node)
        in_degree[node] = len(deps)

    queue = [n for n in step_nums if in_degree[n] == 0]
    order = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in dependents[n]:
            in_degree[m] -= 1
            if in_degree[m] == 0:
                queue.append(m)

    has_cycle = len(order) != len(step_nums)

    # Check sequential ordering: if no explicit depends_on, steps should appear in
    # increasing order (step N depends on all prior steps implicitly)
    sequential_violation = False
    step_by_num = {s["step"]: s for s in steps}
    for i in range(1, len(steps)):
        current = steps[i]
        for dep_num in current.get("depends_on", []):
            if dep_num >= current["step"]:
                sequential_violation = True

    passed = not has_cycle and not sequential_violation
    return {
        "passed": passed,
        "has_cycle": has_cycle,
        "sequential_violation": sequential_violation,
        "topological_order": order,
        "check": "B-ordering-structured",
    }


def check_b_ordering_prose(plan_text: str) -> dict:
    """Check B on prose: abstain (too noisy to reliably parse dependencies)."""
    return {
        "passed": None,   # None = abstain
        "reason": "Dependency ordering cannot be reliably checked from prose; abstaining.",
        "check": "B-ordering-prose",
    }


# ── Check C — Rollback correspondence ────────────────────────────────────────

DESTRUCTIVE_OPS = {"DROP_TABLE", "DROP_COLUMN", "DELETE", "ALTER_TABLE", "UPDATE"}
INVERSE_OPS = {
    "ADD_COLUMN": "DROP_COLUMN",
    "DROP_COLUMN": "ADD_COLUMN",
    "CREATE_TABLE": "DROP_TABLE",
    "DROP_TABLE": "CREATE_TABLE",
    "INSERT": "DELETE",
    "DELETE": "INSERT",
    "ALTER_TABLE": "ALTER_TABLE",
    "UPDATE": "UPDATE",
    "OTHER": "OTHER",
}


def check_c_rollback_structured(plan: dict) -> dict:
    """Check C on structured JSON: every forward step has a reverses_forward_step match."""
    forward_steps = {s["step"]: s for s in plan.get("forward_steps", [])}
    rollback_steps = plan.get("rollback_steps", [])

    covered = {r["reverses_forward_step"] for r in rollback_steps if "reverses_forward_step" in r}
    uncovered = set(forward_steps.keys()) - covered

    # Downgrade: steps with operation=OTHER are expected to have rollback but may be harder
    truly_uncovered = [
        s for n, s in forward_steps.items()
        if n in uncovered and s.get("operation", "OTHER") != "OTHER"
    ]

    passed = len(truly_uncovered) == 0
    return {
        "passed": passed,
        "uncovered_forward_steps": [s["step"] for s in truly_uncovered],
        "rollback_coverage": f"{len(covered)}/{len(forward_steps)}",
        "check": "C-rollback-structured",
    }


def check_c_rollback_prose(plan_text: str, scenario: dict) -> dict:
    """Check C on prose: look for rollback section and structural inverse keywords."""
    plan_lower = plan_text.lower()
    has_rollback_section = bool(
        re.search(r'\b(rollback|undo|revert|reverse)\b', plan_lower)
    )

    # Count forward destructive keywords
    destructive_kws = ["drop table", "drop column", "delete from", "alter table"]
    forward_section = plan_lower
    rollback_section = ""

    # Try to split prose into forward / rollback sections
    rb_match = re.search(r'\b(rollback|undo|revert)\b', plan_lower)
    if rb_match:
        split = rb_match.start()
        forward_section = plan_lower[:split]
        rollback_section = plan_lower[split:]

    destructive_count = sum(forward_section.count(k) for k in destructive_kws)
    rollback_count = sum(rollback_section.count(k) for k in destructive_kws + ["create table", "add column"])

    # Heuristic: if there are destructive ops in forward and nothing in rollback, flag
    if destructive_count > 0 and not has_rollback_section:
        passed = False
        reason = "No rollback section found despite destructive forward steps"
    elif destructive_count > 0 and rollback_count == 0:
        passed = False
        reason = "Rollback section exists but contains no inverse SQL operations"
    else:
        passed = True
        reason = "Rollback section present with inverse operations"

    return {
        "passed": passed,
        "has_rollback_section": has_rollback_section,
        "destructive_forward_ops": destructive_count,
        "inverse_rollback_ops": rollback_count,
        "reason": reason,
        "check": "C-rollback-prose",
    }


# ── Check D — SQL execution ───────────────────────────────────────────────────

def split_sql_statements(sql: str) -> list[str]:
    """Split a string that may hold several SQL statements into single statements.

    Uses sqlite3.complete_statement, so semicolons inside string literals,
    quoted identifiers, comments, and CREATE TRIGGER ... BEGIN ...; END bodies
    do not cause a split. A trailing fragment without a semicolon is kept as
    its own statement (sqlite will report it if it is malformed).
    """
    statements = []
    buf = ""
    for ch in sql:
        buf += ch
        if ch == ";" and sqlite3.complete_statement(buf):
            stmt = buf.strip()
            if stmt.strip(";").strip():
                statements.append(stmt)
            buf = ""
    tail = buf.strip()
    if tail and tail.strip(";").strip():
        statements.append(tail)
    return statements


def check_d_sql_execution(sql_statements: list[str], db_path: Path, legacy: bool = False) -> dict:
    """Execute a plan's SQL against a fresh, throwaway copy of the database.

    Each call copies `db_path` to a temp file and runs there, so every sample
    starts from the same pristine schema. (A rolled-back transaction is not
    enough: Python's sqlite3 autocommits DDL such as ALTER/CREATE/DROP, which
    previously leaked schema changes from one sample into the next.)
    Each entry of `sql_statements` may contain several statements; they are
    split and run one at a time, in order, against the same copy, so multi-step
    plans see their own earlier steps and every failing statement is reported.

    legacy=True reproduces the original Check D exactly, for replaying old
    results: it runs each entry unsplit with conn.execute() (so multi-statement
    entries fail with "You can only execute one statement at a time") directly
    on `db_path`, then rolls back — which does not undo autocommitted DDL.
    """
    if not sql_statements:
        return {
            "passed": None,
            "reason": "No SQL statements found to execute",
            "check": "D-sql-execution",
        }

    if legacy:
        statements = list(sql_statements)
    else:
        statements = [st for entry in sql_statements for st in split_sql_statements(entry)]

    def _execute_all(conn: sqlite3.Connection) -> list[dict]:
        errs = []
        for stmt in statements:
            try:
                conn.execute(stmt)
            except sqlite3.Error as e:
                errs.append({"sql": stmt[:100], "error": str(e)})
        return errs

    if legacy:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            errors = _execute_all(conn)
        finally:
            conn.rollback()
            conn.close()
    else:
        with tempfile.TemporaryDirectory() as tmp:
            scratch_db = Path(tmp) / "check_d.db"
            shutil.copyfile(db_path, scratch_db)
            conn = sqlite3.connect(str(scratch_db))
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                errors = _execute_all(conn)
            finally:
                conn.close()

    passed = len(errors) == 0
    return {
        "passed": passed,
        "sql_count": len(statements),
        "errors": errors,
        "reason": "all SQL executed cleanly" if passed else f"{len(errors)} SQL error(s)",
        "check": "D-sql-execution",
        "mode": "legacy" if legacy else "fresh-copy",
    }


# ── Composite verdict ─────────────────────────────────────────────────────────

def evaluate_prose(
    plan_text: str, scenario: dict, db_path: Path, skip_checks: tuple[str, ...] = (),
    check_d_legacy: bool = False,
) -> tuple[bool, dict]:
    """Run all checks on a prose migration plan. Returns (verdict, details).

    `skip_checks` names checks to leave out entirely, e.g. ("D",).
    `check_d_legacy` runs the original Check D (see check_d_sql_execution).
    """
    sql = _extract_sql_blocks(plan_text)
    runners = {
        "A": lambda: check_a_completeness_prose(plan_text, scenario),
        "B": lambda: check_b_ordering_prose(plan_text),
        "C": lambda: check_c_rollback_prose(plan_text, scenario),
        "D": lambda: check_d_sql_execution(sql, db_path, legacy=check_d_legacy),
    }
    checks = {k: run() for k, run in runners.items() if k not in skip_checks}

    # Verdict: fail if any non-abstain check fails
    failed = [
        k for k, v in checks.items()
        if v.get("passed") is False  # False only (not None = abstain)
    ]
    passed = len(failed) == 0
    return passed, {
        "checks": checks,
        "failed_checks": failed,
        "sql_extracted": len(sql),
        "skipped_checks": list(skip_checks),
        "reason": "all checks passed" if passed else f"failed checks: {failed}",
    }


def evaluate_structured(
    plan: dict, scenario: dict, db_path: Path, skip_checks: tuple[str, ...] = (),
    check_d_legacy: bool = False,
) -> tuple[bool, dict]:
    """Run all checks on a structured JSON migration plan. Returns (verdict, details).

    `skip_checks` and `check_d_legacy` behave as in evaluate_prose.
    """
    sql_stmts = []
    for step in plan.get("forward_steps", []):
        sql = step.get("sql", "").strip()
        if sql and sql.upper() not in ("", "N/A", "NULL"):
            sql_stmts.append(sql.rstrip(";") + ";")
    for step in plan.get("rollback_steps", []):
        sql = step.get("sql", "").strip()
        if sql and sql.upper() not in ("", "N/A", "NULL"):
            sql_stmts.append(sql.rstrip(";") + ";")
    if plan.get("validation_sql"):
        sql_stmts.append(plan["validation_sql"].rstrip(";") + ";")

    runners = {
        "A": lambda: check_a_completeness_structured(plan, scenario),
        "B": lambda: check_b_ordering_structured(plan),
        "C": lambda: check_c_rollback_structured(plan),
        "D": lambda: check_d_sql_execution(sql_stmts, db_path, legacy=check_d_legacy),
    }
    checks = {k: run() for k, run in runners.items() if k not in skip_checks}

    failed = [
        k for k, v in checks.items()
        if v.get("passed") is False
    ]
    passed = len(failed) == 0
    return passed, {
        "checks": checks,
        "failed_checks": failed,
        "sql_extracted": len(sql_stmts),
        "skipped_checks": list(skip_checks),
        "reason": "all checks passed" if passed else f"failed checks: {failed}",
    }
