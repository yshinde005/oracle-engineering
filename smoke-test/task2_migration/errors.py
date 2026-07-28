"""Seeded migration plan errors — one per error class per scenario subset.

Each error is a transform on the plan dict (structured) or string (prose).
The transforms are applied AFTER generation to create labeled wrong plans.

Error classes:
  missing_step        — remove a step that creates a required intermediate object
  wrong_ordering      — swap two steps so a dependency is violated (structured only)
  incomplete_rollback — remove a rollback step for a destructive forward step
  data_loss           — remove the INSERT...SELECT backfill query
  wrong_column_ref    — change a column name in SQL to a wrong name

Each seeded error is paired with a scenario and a check that should catch it:
  missing_step        → Check A catches
  wrong_ordering      → Check B catches
  incomplete_rollback → Check C catches
  data_loss / wrong_column_ref → Check D catches
"""
import copy
import re


# ── Structured plan transforms ────────────────────────────────────────────────

def inject_missing_step(plan: dict, step_num: int) -> dict:
    """Remove forward step N and its rollback from a structured plan."""
    plan = copy.deepcopy(plan)
    plan["forward_steps"] = [s for s in plan["forward_steps"] if s["step"] != step_num]
    plan["rollback_steps"] = [s for s in plan["rollback_steps"]
                               if s.get("reverses_forward_step") != step_num]
    # Also remove from affected_tables/columns if the step mentioned them
    return plan


def inject_wrong_ordering(plan: dict, step_a: int, step_b: int) -> dict:
    """Swap the positions of two forward steps (but preserve their step numbers)."""
    plan = copy.deepcopy(plan)
    steps = plan["forward_steps"]
    idx_a = next((i for i, s in enumerate(steps) if s["step"] == step_a), None)
    idx_b = next((i for i, s in enumerate(steps) if s["step"] == step_b), None)
    if idx_a is not None and idx_b is not None:
        steps[idx_a], steps[idx_b] = steps[idx_b], steps[idx_a]
        # Add explicit depends_on to create the ordering violation
        steps[idx_a]["depends_on"] = [step_b]  # step_a now says it depends on step_b
    return plan


def inject_incomplete_rollback(plan: dict, step_num: int) -> dict:
    """Remove the rollback step that covers forward step N."""
    plan = copy.deepcopy(plan)
    plan["rollback_steps"] = [
        s for s in plan["rollback_steps"]
        if s.get("reverses_forward_step") != step_num
    ]
    return plan


def inject_data_loss(plan: dict) -> dict:
    """Remove any INSERT...SELECT statements from forward steps (kills backfill)."""
    plan = copy.deepcopy(plan)
    for step in plan["forward_steps"]:
        sql = step.get("sql", "")
        if re.search(r'\bINSERT\b.*\bSELECT\b', sql, re.IGNORECASE | re.DOTALL):
            step["sql"] = ""
            step["description"] = step["description"] + " [NOTE: data migration omitted]"
    return plan


def inject_wrong_column_ref(plan: dict, wrong_col: str, right_col: str) -> dict:
    """Replace a column reference in all SQL statements."""
    plan = copy.deepcopy(plan)
    for step in plan["forward_steps"] + plan["rollback_steps"]:
        if "sql" in step:
            step["sql"] = re.sub(
                r'\b' + re.escape(right_col) + r'\b',
                wrong_col,
                step["sql"],
                flags=re.IGNORECASE
            )
    if plan.get("validation_sql"):
        plan["validation_sql"] = re.sub(
            r'\b' + re.escape(right_col) + r'\b',
            wrong_col,
            plan["validation_sql"],
            flags=re.IGNORECASE
        )
    return plan


# ── Prose plan transforms ─────────────────────────────────────────────────────

def inject_missing_step_prose(plan_text: str, step_marker: str) -> str:
    """Remove a paragraph/numbered step containing step_marker from prose."""
    lines = plan_text.split("\n")
    result = []
    skip = False
    for line in lines:
        if step_marker.lower() in line.lower():
            skip = True
        elif skip and (re.match(r'^\d+\.', line.strip()) or re.match(r'^#+', line.strip())):
            skip = False
        if not skip:
            result.append(line)
    return "\n".join(result)


def inject_incomplete_rollback_prose(plan_text: str) -> str:
    """Remove the rollback section from prose entirely."""
    # Find the rollback section and truncate before it
    rb_match = re.search(r'\n#+\s*(rollback|undo|revert)', plan_text, re.IGNORECASE)
    if rb_match:
        return plan_text[:rb_match.start()] + "\n\n(Rollback procedure: not provided.)"
    # Alternative: find numbered rollback steps
    rb_match = re.search(r'\n\d+\.\s+(rollback|undo|revert)', plan_text, re.IGNORECASE)
    if rb_match:
        return plan_text[:rb_match.start()]
    return plan_text  # couldn't find rollback section


def inject_data_loss_prose(plan_text: str) -> str:
    """Remove INSERT...SELECT lines from prose code blocks."""
    def remove_insert_select(match):
        block = match.group(0)
        lines = block.split("\n")
        filtered = [
            l for l in lines
            if not re.search(r'\bINSERT\b.*\bSELECT\b', l, re.IGNORECASE)
        ]
        return "\n".join(filtered)
    return re.sub(r'```(?:sql)?\s*.*?```', remove_insert_select, plan_text,
                  flags=re.DOTALL | re.IGNORECASE)


# ── Error catalog (applied in run.py) ────────────────────────────────────────

# Each entry describes what error to inject on which scenario.
# run.py applies these transforms to generated plans.
SEEDED_ERRORS = [
    # Check A — completeness (missing step removes the key schema change)
    {
        "id": "me01",
        "scenario_id": "s01",
        "error_class": "missing_step",
        "expected_catcher": "A",
        "description": "Remove the ADD COLUMN step for email",
        "transform_structured": lambda p: inject_missing_step(p, 1),
        "transform_prose": lambda t: inject_missing_step_prose(t, "email"),
    },
    {
        "id": "me02",
        "scenario_id": "s09",
        "error_class": "missing_step",
        "expected_catcher": "A",
        "description": "Remove the CREATE TABLE roles step",
        "transform_structured": lambda p: inject_missing_step(p, 1),
        "transform_prose": lambda t: inject_missing_step_prose(t, "roles"),
    },
    # Check B — ordering (swap steps that have a dependency)
    {
        "id": "me03",
        "scenario_id": "s09",
        "error_class": "wrong_ordering",
        "expected_catcher": "B",
        "description": "Swap step 1 (CREATE roles) and step 2 (INSERT INTO roles): FK violation",
        "transform_structured": lambda p: inject_wrong_ordering(p, 1, 2),
        "transform_prose": None,  # B abstains on prose
    },
    {
        "id": "me04",
        "scenario_id": "s07",
        "error_class": "wrong_ordering",
        "expected_catcher": "B",
        "description": "Swap steps so employee_contacts is populated before it exists",
        "transform_structured": lambda p: inject_wrong_ordering(p, 1, 2),
        "transform_prose": None,
    },
    # Check C — incomplete rollback
    {
        "id": "me05",
        "scenario_id": "s01",
        "error_class": "incomplete_rollback",
        "expected_catcher": "C",
        "description": "Remove the rollback step for ADD COLUMN email",
        "transform_structured": lambda p: inject_incomplete_rollback(p, 1),
        "transform_prose": inject_incomplete_rollback_prose,
    },
    {
        "id": "me06",
        "scenario_id": "s07",
        "error_class": "incomplete_rollback",
        "expected_catcher": "C",
        "description": "Remove rollback for employee_contacts creation",
        "transform_structured": lambda p: inject_incomplete_rollback(p, 1),
        "transform_prose": inject_incomplete_rollback_prose,
    },
    {
        "id": "me07",
        "scenario_id": "s11",
        "error_class": "incomplete_rollback",
        "expected_catcher": "C",
        "description": "No rollback provided for DELETE operations on cancelled projects",
        "transform_structured": lambda p: inject_incomplete_rollback(p, 1),
        "transform_prose": inject_incomplete_rollback_prose,
    },
    # Check D — data loss (INSERT...SELECT removed)
    {
        "id": "me08",
        "scenario_id": "s09",
        "error_class": "data_loss",
        "expected_catcher": "D",
        "description": "INSERT...SELECT to populate roles removed (assignments.role_id stays NULL)",
        "transform_structured": inject_data_loss,
        "transform_prose": inject_data_loss_prose,
    },
    {
        "id": "me09",
        "scenario_id": "s10",
        "error_class": "data_loss",
        "expected_catcher": "D",
        "description": "INSERT...SELECT to backfill salary_history removed",
        "transform_structured": inject_data_loss,
        "transform_prose": inject_data_loss_prose,
    },
    # Check D — wrong column reference
    {
        "id": "me10",
        "scenario_id": "s04",
        "error_class": "wrong_column_ref",
        "expected_catcher": "D",
        "description": "Rename SQL references: start_date → hire_date in the new schema SQL",
        "transform_structured": lambda p: inject_wrong_column_ref(p, "hire_date", "start_date"),
        "transform_prose": lambda t: t.replace("start_date", "original_date"),
    },
    {
        "id": "me11",
        "scenario_id": "s08",
        "error_class": "wrong_column_ref",
        "expected_catcher": "D",
        "description": "Cast to REAL instead of INTEGER in the type conversion SQL",
        "transform_structured": lambda p: inject_wrong_column_ref(p, "REAL", "INTEGER"),
        "transform_prose": lambda t: re.sub(r'\bINTEGER\b', 'REAL',
                                             t, flags=re.IGNORECASE),
    },
    # Subtle semantic: missing FK cascade awareness
    {
        "id": "me12",
        "scenario_id": "s11",
        "error_class": "wrong_ordering",
        "expected_catcher": "B",
        "description": "Delete projects before deleting assignments (FK violation order)",
        "transform_structured": lambda p: inject_wrong_ordering(p, 1, 2),
        "transform_prose": None,
    },
]
