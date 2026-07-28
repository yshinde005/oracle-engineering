"""Generate SQL for natural-language questions using Claude Sonnet."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.api import call_claude, compute_cost
from task1_sql.database import SCHEMA_DESCRIPTION

SYSTEM_PROMPT = f"""You are a SQL expert. Given a natural-language question about a company database,
write a single, correct SQLite SQL query that answers the question exactly.

Database schema:
{SCHEMA_DESCRIPTION}

Rules:
- Output ONLY the SQL query, nothing else — no explanation, no markdown fences
- Use SQLite-compatible syntax
- Terminate with a semicolon
- Prefer explicit column names over SELECT *
- All date columns store ISO 8601 strings (YYYY-MM-DD); use string comparison for date filtering
"""


def generate_sql(question: str) -> tuple[str, dict]:
    """Returns (sql_string, usage_dict)."""
    content, usage = call_claude(SYSTEM_PROMPT, question, max_tokens=512)
    sql = content.strip()
    if not sql.endswith(";"):
        sql += ";"
    return sql, usage


if __name__ == "__main__":
    sql, usage = generate_sql("How many employees are there in total?")
    print(sql)
    print(f"Cost: ${compute_cost(usage):.4f}")
