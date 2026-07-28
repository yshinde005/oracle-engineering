"""Generate migration plans in two modes: prose (Run A) and structured JSON (Run B).

Run A: free-form prose steps — oracle must parse natural language
Run B: structured JSON — oracle reads explicit fields, no parsing needed

The Run A vs Run B comparison is the experiment's core measurement.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.api import call_claude, call_json, compute_cost

PROSE_SYSTEM = """You are a database migration expert. Given a schema migration scenario,
write a clear step-by-step migration plan.

Your plan MUST include:
1. Forward steps: numbered steps to transform the schema from current to target
2. Rollback steps: numbered steps to undo the migration if needed
3. SQL statements for each step (use SQLite syntax, inside code blocks)
4. Any data migration needed (use INSERT...SELECT, UPDATE, etc.)
5. Validation queries to verify success

Be thorough. If a step modifies or creates a table/column, name it explicitly.
"""

STRUCTURED_SYSTEM = """You are a database migration expert. Given a schema migration scenario,
produce a migration plan as a JSON object with this EXACT structure:

{
  "scenario_id": "<id from input>",
  "title": "<brief title>",
  "affected_tables": ["table1", "table2"],
  "affected_columns": {"table1": ["col1", "col2"], "table2": ["col3"]},
  "forward_steps": [
    {
      "step": 1,
      "description": "<what this step does>",
      "sql": "<SQLite SQL statement or empty string if no SQL>",
      "depends_on": [],
      "affects_table": "<table name or null>",
      "operation": "<ADD_COLUMN|DROP_COLUMN|CREATE_TABLE|DROP_TABLE|ALTER_TABLE|INSERT|UPDATE|DELETE|OTHER>"
    }
  ],
  "rollback_steps": [
    {
      "step": 1,
      "description": "<what the rollback does>",
      "sql": "<SQLite SQL>",
      "reverses_forward_step": <forward step number this undoes>
    }
  ],
  "validation_sql": "<SQL query to verify migration succeeded>"
}

Rules:
- List ALL tables and columns affected (both added and removed)
- Each forward step must have a corresponding rollback step
- SQL must be valid SQLite
- depends_on is a list of forward step numbers that must complete first
- Respond ONLY with the JSON object, no markdown fences
"""


def _build_prompt(scenario: dict) -> str:
    constraints = "\n".join(f"  - {c}" for c in scenario["constraints"])
    return f"""Scenario ID: {scenario['id']}
Title: {scenario['title']}

Current schema:
{scenario['current_schema']}

Target schema:
{scenario['target_schema']}

Constraints:
{constraints}

Notes: {scenario.get('notes', '')}
"""


def generate_prose(scenario: dict) -> tuple[str, dict]:
    """Run A: free-form prose migration plan."""
    prompt = _build_prompt(scenario)
    content, usage = call_claude(PROSE_SYSTEM, prompt, max_tokens=2048)
    return content.strip(), usage


def generate_structured(scenario: dict) -> tuple[dict, dict]:
    """Run B: structured JSON migration plan."""
    prompt = _build_prompt(scenario)
    plan, usage = call_json(STRUCTURED_SYSTEM, prompt, max_tokens=2048)
    return plan, usage


if __name__ == "__main__":
    import json
    from task2_migration.scenarios import SCENARIOS
    scenario = SCENARIOS[0]
    print("=== Run A (prose) ===")
    prose, u1 = generate_prose(scenario)
    print(prose[:500])
    print(f"\nCost: ${compute_cost(u1):.4f}")

    print("\n=== Run B (structured) ===")
    plan, u2 = generate_structured(scenario)
    print(json.dumps(plan, indent=2)[:500])
    print(f"\nCost: ${compute_cost(u2):.4f}")
