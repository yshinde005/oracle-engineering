"""Tests for Task 2's Check D and offline re-scoring. No API calls.

Run from smoke-test/:  python -m unittest discover -s tests -v
"""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from task1_sql.database import create_and_seed  # noqa: E402
from task2_migration import offline  # noqa: E402
from task2_migration.oracle import (  # noqa: E402
    check_d_sql_execution,
    evaluate_prose,
    split_sql_statements,
)
from task2_migration.scenarios import SCENARIOS  # noqa: E402


def _schema(db: Path) -> str:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    finally:
        conn.close()
    return hashlib.sha256("\n".join(r[0] or "" for r in rows).encode()).hexdigest()


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "company.db"
        create_and_seed(self.db).close()

    def tearDown(self):
        self._tmp.cleanup()


class SplitSqlStatementsTest(unittest.TestCase):
    def test_splits_statements_on_one_line(self):
        self.assertEqual(
            split_sql_statements("ALTER TABLE t ADD COLUMN a TEXT; UPDATE t SET a = 'x';"),
            ["ALTER TABLE t ADD COLUMN a TEXT;", "UPDATE t SET a = 'x';"],
        )

    def test_does_not_split_inside_string_literal(self):
        self.assertEqual(
            split_sql_statements("UPDATE t SET a = 'x; y'; SELECT 1;"),
            ["UPDATE t SET a = 'x; y';", "SELECT 1;"],
        )

    def test_keeps_trigger_body_together(self):
        sql = ("CREATE TRIGGER trg AFTER INSERT ON t BEGIN UPDATE t SET a = 1; END; "
               "SELECT 1;")
        stmts = split_sql_statements(sql)
        self.assertEqual(len(stmts), 2)
        self.assertTrue(stmts[0].endswith("END;"))

    def test_keeps_unterminated_tail_and_drops_empty_statements(self):
        self.assertEqual(split_sql_statements("SELECT 1;;  ; SELECT 2"), ["SELECT 1;", "SELECT 2"])


class CheckDTest(DbTestCase):
    def test_multi_statement_entry_executes(self):
        result = check_d_sql_execution(
            ["ALTER TABLE employees ADD COLUMN a TEXT; UPDATE employees SET a = name;"], self.db)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["sql_count"], 2)

    def test_reports_each_failing_statement(self):
        result = check_d_sql_execution(
            ["SELECT nope FROM employees; SELECT 1; SELECT * FROM missing_table;"], self.db)
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["errors"]), 2)

    def test_later_statements_see_earlier_ones(self):
        result = check_d_sql_execution(
            ["ALTER TABLE employees ADD COLUMN email TEXT;",
             "UPDATE employees SET email = name || '@example.com';"], self.db)
        self.assertTrue(result["passed"], result)

    def test_fresh_copy_leaves_database_untouched(self):
        before = _schema(self.db)
        for _ in range(2):  # same plan twice: must pass both times
            result = check_d_sql_execution(
                ["ALTER TABLE employees ADD COLUMN email TEXT;",
                 "UPDATE employees SET email = name;",
                 "CREATE TABLE salary_history (id INTEGER PRIMARY KEY);"], self.db)
            self.assertTrue(result["passed"], result)
        self.assertEqual(_schema(self.db), before)

    def test_legacy_mode_reproduces_original_bugs(self):
        # Multi-statement entries fail outright.
        r = check_d_sql_execution(["SELECT 1; SELECT 2;"], self.db, legacy=True)
        self.assertIn("one statement at a time", r["errors"][0]["error"])
        # DDL leaks: an ADD COLUMN followed by DML is not undone by the rollback,
        # so the same plan fails the second time.
        plan = ["ALTER TABLE projects ADD COLUMN end_date TEXT;",
                "UPDATE projects SET end_date = start_date;"]
        self.assertTrue(check_d_sql_execution(plan, self.db, legacy=True)["passed"])
        second = check_d_sql_execution(plan, self.db, legacy=True)
        self.assertFalse(second["passed"])
        self.assertIn("duplicate column", second["errors"][0]["error"])

    def test_evaluate_prose_skip_check_d(self):
        plan = "Plan.\n```sql\nSELECT * FROM missing_table;\n```"
        _, with_d = evaluate_prose(plan, SCENARIOS[0], self.db)
        _, without_d = evaluate_prose(plan, SCENARIOS[0], self.db, skip_checks=("D",))
        self.assertIn("D", with_d["checks"])
        self.assertNotIn("D", without_d["checks"])


class OfflineTest(DbTestCase):
    """Offline scoring on a tiny synthetic snapshot."""

    def _write_snapshot(self):
        snap = self.tmp / "snap"
        snap.mkdir()
        good = ("Add the column.\n```sql\nALTER TABLE employees ADD COLUMN email TEXT;\n```\n"
                "Rollback:\n```sql\nALTER TABLE employees DROP COLUMN email;\n```")
        bad = "Do nothing.\n```sql\nSELECT * FROM missing_table;\n```"

        def sample(sid, output, seeded, mirror):
            return {"id": sid, "question": "", "output": output, "ground_truth": not seeded,
                    "is_seeded_error": seeded, "error_type": None,
                    "mirror_verdict": mirror, "mirror_reasoning": "", "oracle_verdict": None,
                    "oracle_details": {}}

        run_a = {"samples": [sample("A-s01", good, False, True),
                             sample("A-me01", bad, True, False)]}
        (snap / "task2_run_a.json").write_text(json.dumps(run_a))
        return snap

    def test_scenario_mapping(self):
        self.assertEqual(offline.scenario_for("A-s07")["id"], "s07")
        self.assertEqual(offline.scenario_for("B-me03")["id"],
                         next(e for e in offline.SEEDED_ERRORS if e["id"] == "me03")["scenario_id"])

    def test_score_uses_saved_mirror_verdicts(self):
        snap = self._write_snapshot()
        samples, summary = offline.score(snap, "a", gt="oracle", include_check_d=True)
        by_id = {s.id: s for s in samples}
        self.assertTrue(by_id["A-s01"].mirror_verdict)
        self.assertFalse(by_id["A-me01"].mirror_verdict)
        self.assertFalse(by_id["A-me01"].oracle_verdict)  # Check D catches the bad SQL
        self.assertEqual(summary["oracle_caught"], ["A-me01"])

    def test_human_gt_requires_label_for_every_sample(self):
        snap = self._write_snapshot()
        data = json.loads((snap / "task2_run_a.json").read_text())
        # Map to scenario s01 but use an id that human_labels.json doesn't contain.
        data["samples"].append(dict(data["samples"][0], id="A-s01x"))
        (snap / "task2_run_a.json").write_text(json.dumps(data))
        offline._SC_BY_ID["s01x"] = offline._SC_BY_ID["s01"]
        self.addCleanup(offline._SC_BY_ID.pop, "s01x")
        with self.assertRaises(KeyError):
            offline.score(snap, "a", gt="human", include_check_d=False)

    def test_missing_snapshot_is_a_clear_error(self):
        with self.assertRaises(FileNotFoundError):
            offline.score(self.tmp / "nope", "a", gt="human", include_check_d=False)


if __name__ == "__main__":
    unittest.main()
