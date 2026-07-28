"""Orchestrate Task 1 (SQL generation): generate → mirror → oracle → evaluate.

Usage:
  python -m task1_sql.run              # full run (generates if not cached)
  python -m task1_sql.run --regen      # force regeneration
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from shared.api import compute_cost
from shared.evaluation import SampleResult, print_report, save_results
from task1_sql.database import create_and_seed, DB_PATH
from task1_sql.questions import QUESTIONS
from task1_sql.errors import SEEDED_ERRORS
from task1_sql.generator import generate_sql
from task1_sql.mirror import evaluate_sql as mirror_eval
from task1_sql.oracle import compute_expected, evaluate_sql as oracle_eval

RESULTS_DIR = Path(__file__).parent.parent / "results"
CACHE_FILE = RESULTS_DIR / "task1_generated.json"
RESULTS_FILE = RESULTS_DIR / "task1_results.json"


def load_cache() -> dict | None:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return None


def save_cache(data: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, indent=2))


def run(force_regen: bool = False) -> list[SampleResult]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Task 1 — SQL Generation")
    print("Setting up database...")
    conn = create_and_seed(DB_PATH)

    # ── Compute expected results from golden SQL ──────────────────────────
    print("Computing expected results from golden SQL...")
    expected: dict[str, list[tuple]] = {}
    for q in QUESTIONS:
        expected[q["id"]] = compute_expected(q["golden_sql"], conn)

    conn.close()

    # ── Load or generate SQL outputs ──────────────────────────────────────
    cache = load_cache() if not force_regen else None
    generated: dict = cache or {}
    total_gen_cost = 0.0

    if not cache or force_regen:
        print(f"\nGenerating SQL for {len(QUESTIONS)} questions...")
        for i, q in enumerate(QUESTIONS, 1):
            print(f"  [{i:02d}/{len(QUESTIONS)}] {q['id']}: {q['question'][:60]}...")
            sql, usage = generate_sql(q["question"])
            cost = compute_cost(usage)
            total_gen_cost += cost
            generated[q["id"]] = {"sql": sql, "usage": usage}

        save_cache(generated)
        print(f"  Generation complete. Cost: ${total_gen_cost:.4f}")
    else:
        print(f"  Loaded {len(generated)} cached generated SQL outputs.")

    # ── Build sample list: clean + seeded errors ──────────────────────────
    # Map question_id → question text for error samples
    q_by_id = {q["id"]: q for q in QUESTIONS}

    samples: list[SampleResult] = []

    # Clean samples (generated SQL from model)
    for q in QUESTIONS:
        qid = q["id"]
        gen = generated.get(qid, {})
        samples.append(SampleResult(
            id=qid,
            question=q["question"],
            output=gen.get("sql", ""),
            ground_truth=True,   # model output may be correct or wrong; oracle/mirror determine
            is_seeded_error=False,
            usage_generate=gen.get("usage", {}),
        ))

    # Seeded error samples (pre-written wrong SQL, ground_truth = False)
    for e in SEEDED_ERRORS:
        q = q_by_id[e["question_id"]]
        samples.append(SampleResult(
            id=e["id"],
            question=q["question"],
            output=e["sql"],
            ground_truth=False,
            is_seeded_error=True,
            error_type=e["error_type"],
        ))

    # ── Run mirror evaluation ─────────────────────────────────────────────
    print(f"\nRunning mirror on {len(samples)} samples...")
    total_mirror_cost = 0.0
    for i, s in enumerate(samples, 1):
        verdict, reasoning, usage = mirror_eval(s.question, s.output)
        s.mirror_verdict = verdict
        s.mirror_reasoning = reasoning
        s.usage_mirror = usage
        total_mirror_cost += compute_cost(usage)
        status = "✓" if verdict else "✗"
        print(f"  [{i:02d}/{len(samples)}] {s.id}: mirror={status}")

    print(f"  Mirror cost: ${total_mirror_cost:.4f}")

    # ── Run oracle evaluation ─────────────────────────────────────────────
    print(f"\nRunning oracle on {len(samples)} samples...")
    for s in samples:
        # For clean samples, ground truth expected result comes from golden SQL
        # For seeded errors, same: the oracle compares against the golden expected result
        qid = s.id if not s.is_seeded_error else s.id.replace("e", "q")
        # Actually, seeded errors have a question_id pointing to the QUESTIONS entry
        if s.is_seeded_error:
            err = next(e for e in SEEDED_ERRORS if e["id"] == s.id)
            exp = expected[err["question_id"]]
        else:
            exp = expected[s.id]

        is_correct, details = oracle_eval(s.output, exp)
        s.oracle_verdict = is_correct
        s.oracle_details = details
        status = "✓" if is_correct else "✗"
        print(f"  {s.id}: oracle={status}  {details['reason'][:60]}")

    # For clean samples, update ground_truth based on oracle verdict
    # (the model might have generated wrong SQL — that's also ground truth = False)
    # Actually, we need to be careful: "ground_truth" for clean samples should reflect
    # whether the generated SQL is actually correct. We use oracle as ground truth for clean samples.
    for s in samples:
        if not s.is_seeded_error:
            s.ground_truth = s.oracle_verdict  # oracle IS ground truth for clean samples

    # ── Report ────────────────────────────────────────────────────────────
    total_cost = total_gen_cost + total_mirror_cost
    print_report("Task 1 — SQL Generation", samples)
    print(f"\n  Total API cost: ${total_cost:.4f}")

    save_results(RESULTS_FILE, "task1_sql", samples, total_cost)
    return samples


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--regen", action="store_true", help="Force regeneration")
    args = parser.parse_args()
    run(force_regen=args.regen)
