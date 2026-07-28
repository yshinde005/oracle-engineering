"""Mirror: evaluate migration plans (both prose and structured) for correctness."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import json

from shared.api import call_claude, compute_cost

SYSTEM_PROMPT = """You are a database migration reviewer. Given a schema migration scenario
and a proposed migration plan, determine whether the plan is correct and complete.

Evaluate whether the plan:
1. Addresses ALL tables and columns affected by the schema change
2. Lists forward steps in a valid dependency order (later steps don't use objects that don't exist yet)
3. Provides a rollback step for every destructive forward step
4. Preserves all existing data (no rows lost, no data corruption)
5. Uses valid SQL syntax for the target database (SQLite)

Respond ONLY with a JSON object:
{
  "verdict": "correct" | "incorrect",
  "confidence": "high" | "medium" | "low",
  "issues": ["issue 1", "issue 2"],
  "reasoning": "one to three sentences summarizing your verdict"
}
"""


def _scenario_context(scenario: dict) -> str:
    constraints = "\n".join(f"  - {c}" for c in scenario["constraints"])
    return f"""Scenario: {scenario['title']}

Current schema:
{scenario['current_schema']}

Target schema:
{scenario['target_schema']}

Constraints:
{constraints}
"""


def evaluate_plan(scenario: dict, plan_text: str) -> tuple[bool, str, dict]:
    """Works for both prose and JSON plan (pass as string). Returns (verdict, reasoning, usage)."""
    user_msg = f"{_scenario_context(scenario)}\n\nProposed migration plan:\n{plan_text}"
    content, usage = call_claude(SYSTEM_PROMPT, user_msg, max_tokens=512)

    text = content.strip()
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
    if text.endswith("```"):
        text = text[:-3]

    try:
        result = json.loads(text.strip())
        is_correct = result.get("verdict", "").lower() == "correct"
        reasoning = result.get("reasoning", "") + " Issues: " + "; ".join(result.get("issues", []))
    except (json.JSONDecodeError, KeyError):
        is_correct = "correct" in content.lower() and "incorrect" not in content.lower()
        reasoning = content[:300]

    return is_correct, reasoning.strip(". Issues: ").strip(), usage
