"""Mirror (LLM judge): evaluate generated SQL for correctness."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import json

from shared.api import call_claude, compute_cost
from task1_sql.database import SCHEMA_DESCRIPTION

SYSTEM_PROMPT = f"""You are a SQL correctness reviewer. Given a natural-language question
and a SQL query written to answer it, determine whether the SQL is correct.

Database schema:
{SCHEMA_DESCRIPTION}

Evaluate whether the SQL:
1. Selects from the right tables
2. Applies the correct filters and conditions
3. Uses the correct aggregation function(s)
4. Returns the right columns in the right order
5. Handles NULL values and empty results appropriately

Respond ONLY with a JSON object in this exact format:
{{
  "verdict": "correct" | "incorrect",
  "confidence": "high" | "medium" | "low",
  "reasoning": "one or two sentences explaining your verdict"
}}
"""


def evaluate_sql(question: str, generated_sql: str) -> tuple[bool, str, dict]:
    """Returns (is_correct, reasoning, usage_dict)."""
    user_msg = f"Question: {question}\n\nSQL:\n{generated_sql}"
    content, usage = call_claude(SYSTEM_PROMPT, user_msg, max_tokens=256)

    text = content.strip()
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
    if text.endswith("```"):
        text = text[:-3]

    try:
        result = json.loads(text.strip())
        is_correct = result.get("verdict", "").lower() == "correct"
        reasoning = result.get("reasoning", "")
    except (json.JSONDecodeError, KeyError):
        is_correct = "correct" in content.lower() and "incorrect" not in content.lower()
        reasoning = content[:200]

    return is_correct, reasoning, usage


if __name__ == "__main__":
    verdict, reason, usage = evaluate_sql(
        "How many employees earn more than $100,000?",
        "SELECT COUNT(*) FROM employees WHERE salary > 90000;"
    )
    print(f"Verdict: {'correct' if verdict else 'incorrect'}")
    print(f"Reasoning: {reason}")
    print(f"Cost: ${compute_cost(usage):.4f}")
