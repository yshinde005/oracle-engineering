"""Execution oracle: run SQL against the database, compare to golden expected result.

Independence: uses SQLite, not an LLM. Errors are decorrelated from the generator.
Coverage: catches any error that changes the result set.
Blind spot: cannot catch SQL that returns the correct result via a wrong intermediate
  computation (e.g., double-negation of errors). In practice this is vanishingly rare.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from task1_sql.database import run_query_safe, get_connection, DB_PATH


def results_equivalent(a: list[tuple], b: list[tuple]) -> bool:
    """Compare two result sets. Order-insensitive (sorted) comparison.

    Rationale: we care about semantic correctness (right rows) not presentation
    order. ORDER BY in golden SQL sets the expectation, but generators may
    produce correct results with different orderings. Sorted comparison reduces
    oracle false positives on correct-but-differently-ordered output.
    """
    if a is None or b is None:
        return False
    if len(a) != len(b):
        return False

    def normalize(rows: list[tuple]) -> list[tuple]:
        return [
            tuple(round(v, 2) if isinstance(v, float) else v for v in row)
            for row in rows
        ]

    na = sorted(normalize(a), key=lambda r: [str(x) for x in r])
    nb = sorted(normalize(b), key=lambda r: [str(x) for x in r])
    return na == nb


def evaluate_sql(generated_sql: str, expected_result: list[tuple]) -> tuple[bool, dict]:
    """
    Execute generated_sql and compare to expected_result.
    Returns (is_correct, details_dict).
    """
    rows, error = run_query_safe(generated_sql)

    if error is not None:
        return False, {
            "reason": f"SQL execution error: {error}",
            "got": None,
            "expected": expected_result,
        }

    correct = results_equivalent(rows, expected_result)
    return correct, {
        "reason": "result matches" if correct else f"result mismatch: got {rows!r}, expected {expected_result!r}",
        "got": rows,
        "expected": expected_result,
        "row_count_got": len(rows),
        "row_count_expected": len(expected_result),
    }


def compute_expected(golden_sql: str, conn=None) -> list[tuple]:
    """Run golden SQL to get the expected result (called once at setup)."""
    rows, error = run_query_safe(golden_sql, conn)
    if error:
        raise ValueError(f"Golden SQL failed: {error}\nSQL: {golden_sql}")
    return rows
