"""Orchestrate Task 2 (Migration Plans).

Run A: prose plans → oracle parses natural language
Run B: structured JSON plans → oracle reads explicit fields

The Run A vs Run B delta on oracle quality is the experiment's core result.

Usage:
  python -m task2_migration.run           # both runs
  python -m task2_migration.run --run a   # prose only
  python -m task2_migration.run --run b   # structured only
  python -m task2_migration.run --regen   # force regeneration
  python -m task2_migration.run --run a --gt human
      # score Run A against the independent human labels in human_labels.json,
      # with Check D excluded from the oracle
"""
import argparse
import json
import sys
import os
import copy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from shared.api import compute_cost
from shared.evaluation import SampleResult, print_report, save_results
from task1_sql.database import DB_PATH, create_and_seed
from task2_migration.scenarios import SCENARIOS
from task2_migration.generator import generate_prose, generate_structured
from task2_migration.mirror import evaluate_plan
from task2_migration.oracle import evaluate_prose, evaluate_structured
from task2_migration.errors import SEEDED_ERRORS

RESULTS_DIR = Path(__file__).parent.parent / "results"
CACHE_A = RESULTS_DIR / "task2_prose_generated.json"
CACHE_B = RESULTS_DIR / "task2_structured_generated.json"
RESULTS_A = RESULTS_DIR / "task2_run_a.json"
RESULTS_A_HUMAN = RESULTS_DIR / "task2_run_a_human.json"
RESULTS_B = RESULTS_DIR / "task2_run_b.json"
HUMAN_LABELS = Path(__file__).parent / "human_labels.json"
COMPARISON = RESULTS_DIR / "task2_comparison.json"


def ensure_db():
    """(Re)build a pristine seeded database.

    Check D copies this file for every sample, so it must not carry schema
    changes from earlier runs (older versions of Check D leaked DDL into it).
    """
    conn = create_and_seed(DB_PATH)
    conn.close()


def load_human_labels() -> dict[str, bool]:
    """Load human_labels.json as {sample_id: is_valid}."""
    data = json.loads(HUMAN_LABELS.read_text())
    out = {}
    for sample_id, label in data["labels"].items():
        if label not in ("VALID", "INVALID"):
            raise ValueError(f"{HUMAN_LABELS}: bad label {label!r} for {sample_id}")
        out[sample_id] = label == "VALID"
    return out


def _run_a(scenarios: list[dict], force_regen: bool, gt: str = "oracle") -> list[SampleResult]:
    """Prose mode run.

    gt="oracle": legacy scoring. Clean samples' ground truth = the oracle's own
                 verdict (all four checks); seeded samples = invalid.
    gt="human":  ground truth for every sample comes from human_labels.json,
                 and the oracle runs Checks A/B/C only (Check D excluded).
    """
    print("\n── Run A: Prose Plans ──────────────────────────────────────────")
    human = load_human_labels() if gt == "human" else None
    skip_checks = ("D",) if gt == "human" else ()
    if human is not None:
        print(f"  Ground truth: human labels ({HUMAN_LABELS.name}); oracle checks A/B/C only.")
    cache = json.loads(CACHE_A.read_text()) if CACHE_A.exists() and not force_regen else {}

    if not cache or force_regen:
        print(f"Generating prose plans for {len(scenarios)} scenarios...")
        total_gen_cost = 0.0
        for i, sc in enumerate(scenarios, 1):
            print(f"  [{i:02d}/{len(scenarios)}] {sc['id']}: {sc['title']}")
            prose, usage = generate_prose(sc)
            cost = compute_cost(usage)
            total_gen_cost += cost
            cache[sc["id"]] = {"plan": prose, "usage": usage}
        CACHE_A.write_text(json.dumps(cache, indent=2))
        print(f"  Cost: ${total_gen_cost:.4f}")
    else:
        print(f"  Loaded {len(cache)} cached prose plans.")

    sc_by_id = {sc["id"]: sc for sc in scenarios}
    samples: list[SampleResult] = []

    # ── Clean samples ─────────────────────────────────────────────────────
    for sc in scenarios:
        plan_text = cache[sc["id"]]["plan"]
        samples.append(SampleResult(
            id=f"A-{sc['id']}",
            question=sc["title"],
            output=plan_text,
            ground_truth=True,
            is_seeded_error=False,
        ))

    # ── Seeded error samples ──────────────────────────────────────────────
    for err in SEEDED_ERRORS:
        if err["transform_prose"] is None:
            continue  # some errors only apply to structured
        sc = sc_by_id[err["scenario_id"]]
        base_plan = cache[sc["id"]]["plan"]
        try:
            injected = err["transform_prose"](base_plan)
        except Exception as e:
            print(f"  Warning: could not inject {err['id']} into prose: {e}")
            continue
        samples.append(SampleResult(
            id=f"A-{err['id']}",
            question=sc["title"],
            output=injected,
            ground_truth=False,
            is_seeded_error=True,
            error_type=err["error_class"],
        ))

    # ── Mirror ────────────────────────────────────────────────────────────
    print(f"\nRunning mirror on {len(samples)} prose samples...")
    total_mirror_cost = 0.0
    for i, s in enumerate(samples, 1):
        sc_id = s.id.split("-")[1]  # e.g. "A-s01" → "s01"
        sc = sc_by_id.get(sc_id)
        if sc is None:
            # For error samples the id is "A-me01" → need the scenario_id
            err = next((e for e in SEEDED_ERRORS if f"A-{e['id']}" == s.id), None)
            sc = sc_by_id[err["scenario_id"]] if err else None
        if sc is None:
            continue
        verdict, reasoning, usage = evaluate_plan(sc, s.output)
        s.mirror_verdict = verdict
        s.mirror_reasoning = reasoning
        s.usage_mirror = usage
        total_mirror_cost += compute_cost(usage)
        print(f"  [{i:02d}/{len(samples)}] {s.id}: mirror={'✓' if verdict else '✗'}")

    print(f"  Mirror cost: ${total_mirror_cost:.4f}")

    # ── Oracle ────────────────────────────────────────────────────────────
    print(f"\nRunning oracle on {len(samples)} prose samples...")
    for s in samples:
        sc_id = s.id.split("-")[1]
        sc = sc_by_id.get(sc_id)
        if sc is None:
            err = next((e for e in SEEDED_ERRORS if f"A-{e['id']}" == s.id), None)
            sc = sc_by_id[err["scenario_id"]] if err else None
        if sc is None:
            continue
        verdict, details = evaluate_prose(s.output, sc, DB_PATH, skip_checks=skip_checks)
        s.oracle_verdict = verdict
        s.oracle_details = details
        print(f"  {s.id}: oracle={'✓' if verdict else '✗'}  {details['reason'][:60]}")

    if human is not None:
        missing = [s.id for s in samples if s.id not in human]
        if missing:
            raise KeyError(f"No human label for sample(s): {missing}")
        for s in samples:
            s.ground_truth = human[s.id]
    else:
        # Legacy: ground truth for clean samples is the oracle's own verdict.
        # This makes oracle accuracy on clean samples 100% by construction.
        for s in samples:
            if not s.is_seeded_error:
                s.ground_truth = s.oracle_verdict

    return samples


def _run_b(scenarios: list[dict], force_regen: bool) -> list[SampleResult]:
    """Structured JSON mode run."""
    print("\n── Run B: Structured Plans ─────────────────────────────────────")
    cache = json.loads(CACHE_B.read_text()) if CACHE_B.exists() and not force_regen else {}

    if not cache or force_regen:
        print(f"Generating structured plans for {len(scenarios)} scenarios...")
        total_gen_cost = 0.0
        for i, sc in enumerate(scenarios, 1):
            print(f"  [{i:02d}/{len(scenarios)}] {sc['id']}: {sc['title']}")
            try:
                plan, usage = generate_structured(sc)
                cost = compute_cost(usage)
                total_gen_cost += cost
                cache[sc["id"]] = {"plan": plan, "usage": usage}
            except Exception as e:
                print(f"    Error generating structured plan: {e}")
                cache[sc["id"]] = {"plan": None, "usage": {}}
        CACHE_B.write_text(json.dumps(cache, indent=2))
        print(f"  Cost: ${total_gen_cost:.4f}")
    else:
        print(f"  Loaded {len(cache)} cached structured plans.")

    sc_by_id = {sc["id"]: sc for sc in scenarios}
    samples: list[SampleResult] = []

    # ── Clean samples ─────────────────────────────────────────────────────
    for sc in scenarios:
        entry = cache.get(sc["id"], {})
        plan = entry.get("plan")
        if plan is None:
            continue
        samples.append(SampleResult(
            id=f"B-{sc['id']}",
            question=sc["title"],
            output=json.dumps(plan),
            ground_truth=True,
            is_seeded_error=False,
        ))

    # ── Seeded error samples ──────────────────────────────────────────────
    for err in SEEDED_ERRORS:
        sc = sc_by_id[err["scenario_id"]]
        entry = cache.get(sc["id"], {})
        plan = entry.get("plan")
        if plan is None:
            continue
        try:
            injected = err["transform_structured"](plan)
        except Exception as e:
            print(f"  Warning: could not inject {err['id']}: {e}")
            continue
        samples.append(SampleResult(
            id=f"B-{err['id']}",
            question=sc["title"],
            output=json.dumps(injected),
            ground_truth=False,
            is_seeded_error=True,
            error_type=err["error_class"],
        ))

    # ── Mirror ────────────────────────────────────────────────────────────
    print(f"\nRunning mirror on {len(samples)} structured samples...")
    total_mirror_cost = 0.0
    for i, s in enumerate(samples, 1):
        sc_id = s.id.split("-")[1]
        sc = sc_by_id.get(sc_id)
        if sc is None:
            err = next((e for e in SEEDED_ERRORS if f"B-{e['id']}" == s.id), None)
            sc = sc_by_id[err["scenario_id"]] if err else None
        if sc is None:
            continue
        verdict, reasoning, usage = evaluate_plan(sc, s.output)
        s.mirror_verdict = verdict
        s.mirror_reasoning = reasoning
        s.usage_mirror = usage
        total_mirror_cost += compute_cost(usage)
        print(f"  [{i:02d}/{len(samples)}] {s.id}: mirror={'✓' if verdict else '✗'}")

    print(f"  Mirror cost: ${total_mirror_cost:.4f}")

    # ── Oracle ────────────────────────────────────────────────────────────
    print(f"\nRunning oracle on {len(samples)} structured samples...")
    for s in samples:
        sc_id = s.id.split("-")[1]
        sc = sc_by_id.get(sc_id)
        if sc is None:
            err = next((e for e in SEEDED_ERRORS if f"B-{e['id']}" == s.id), None)
            sc = sc_by_id[err["scenario_id"]] if err else None
        if sc is None:
            continue
        try:
            plan = json.loads(s.output)
        except json.JSONDecodeError:
            s.oracle_verdict = False
            s.oracle_details = {"reason": "JSON parse error"}
            continue
        verdict, details = evaluate_structured(plan, sc, DB_PATH)
        s.oracle_verdict = verdict
        s.oracle_details = details
        print(f"  {s.id}: oracle={'✓' if verdict else '✗'}  {details['reason'][:60]}")

    for s in samples:
        if not s.is_seeded_error:
            s.ground_truth = s.oracle_verdict

    return samples


def compare_runs(samples_a: list[SampleResult], samples_b: list[SampleResult]) -> dict:
    """Compute the Run A vs Run B delta on oracle quality for seeded errors."""
    from shared.evaluation import compute_2x2

    m_a = compute_2x2(samples_a)
    m_b = compute_2x2(samples_b)

    return {
        "run_a_detection_lift": m_a["detection_lift"],
        "run_b_detection_lift": m_b["detection_lift"],
        "run_a_oracle_accuracy": m_a["oracle_accuracy"],
        "run_b_oracle_accuracy": m_b["oracle_accuracy"],
        "run_a_correlated_failures": m_a["correlated_failure"],
        "run_b_correlated_failures": m_b["correlated_failure"],
        "delta_detection_lift": m_b["detection_lift"] - m_a["detection_lift"],
        "delta_oracle_accuracy": m_b["oracle_accuracy"] - m_a["oracle_accuracy"],
        "interpretation": (
            "Structured output (Run B) outperforms prose (Run A) — reshaping lever WORKS"
            if m_b["detection_lift"] > m_a["detection_lift"]
            else "No meaningful delta — reshaping lever did NOT create additional checkability"
        ),
    }


def run(runs: str = "ab", force_regen: bool = False, gt: str = "oracle"):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Task 2 — Database Migration Plans")
    ensure_db()

    samples_a = samples_b = None

    if gt == "human" and "b" in runs:
        print("  Note: human labels exist for Run A only; Run B still uses oracle-derived")
        print("  ground truth with all four checks, and the A-vs-B comparison is skipped.")

    if "a" in runs:
        samples_a = _run_a(SCENARIOS, force_regen, gt=gt)
        if gt == "human":
            print_report("Task 2 Run A (Prose) — human labels, Checks A/B/C", samples_a)
            save_results(RESULTS_A_HUMAN, "task2_prose_human_gt", samples_a, 0.0)
        else:
            print_report("Task 2 Run A (Prose)", samples_a)
            save_results(RESULTS_A, "task2_prose", samples_a, 0.0)

    if "b" in runs:
        samples_b = _run_b(SCENARIOS, force_regen)
        print_report("Task 2 Run B (Structured)", samples_b)
        save_results(RESULTS_B, "task2_structured", samples_b, 0.0)

    if samples_a and samples_b and gt == "oracle":
        comparison = compare_runs(samples_a, samples_b)
        COMPARISON.write_text(json.dumps(comparison, indent=2))
        print("\n── Run A vs Run B Comparison (Core Result) ─────────────────────")
        for k, v in comparison.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="ab", choices=["a", "b", "ab"])
    parser.add_argument("--regen", action="store_true")
    parser.add_argument("--gt", default="oracle", choices=["oracle", "human"],
                        help="Run A ground truth: oracle-derived (legacy) or human_labels.json")
    args = parser.parse_args()
    run(runs=args.run, force_regen=args.regen, gt=args.gt)
