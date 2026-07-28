"""Top-level runner: Task 1 → Task 2 → Task 3 → final summary.

Usage:
  python run_all.py                        # all three tasks
  python run_all.py --tasks 1              # Task 1 only
  python run_all.py --tasks 12             # Tasks 1 and 2
  python run_all.py --regen                # force regeneration for all tasks
  python run_all.py --tasks 2 --run b      # Task 2, structured mode only
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def print_banner(text: str) -> None:
    width = 64
    print(f"\n{'#'*width}")
    print(f"#  {text:<{width-4}}#")
    print(f"{'#'*width}\n")


def run_task1(regen: bool):
    print_banner("Task 1 — SQL Generation (Obvious Yes)")
    from task1_sql.run import run
    return run(force_regen=regen)


def run_task2(regen: bool, run_mode: str):
    print_banner("Task 2 — Migration Plans (Deceptive No)")
    from task2_migration.run import run
    return run(runs=run_mode, force_regen=regen)


def run_task3(regen: bool):
    print_banner("Task 3 — Prose Quality (True No)")
    from task3_prose.run import run
    return run(force_regen=regen)


def print_final_summary():
    print_banner("Final Summary — Discipline vs Taxonomy")

    summary = {}

    # Task 1
    t1_path = RESULTS_DIR / "task1_results.json"
    if t1_path.exists():
        t1 = json.loads(t1_path.read_text())
        ev = t1["evaluation"]
        print("Task 1 (SQL — Obvious Yes):")
        print(f"  Detection lift: {ev['detection_lift']} / {ev['seeded_errors']} seeded errors "
              f"({ev['detection_lift_rate']:.0%})")
        print(f"  Correlated failures: {ev['correlated_failure']}")
        print(f"  Expected outcome: A (clean pass). Validates method.\n")
        summary["task1"] = ev

    # Task 2
    t2_comp = RESULTS_DIR / "task2_comparison.json"
    if t2_comp.exists():
        t2 = json.loads(t2_comp.read_text())
        print("Task 2 (Migration Plans — Deceptive No):")
        print(f"  Run A detection lift: {t2['run_a_detection_lift']}")
        print(f"  Run B detection lift: {t2['run_b_detection_lift']}")
        print(f"  Delta (B - A): {t2['delta_detection_lift']}")
        print(f"  Interpretation: {t2['interpretation']}\n")
        summary["task2_comparison"] = t2

    # Task 3
    t3_path = RESULTS_DIR / "task3_results.json"
    if t3_path.exists():
        t3 = json.loads(t3_path.read_text())
        ev = t3["evaluation"]
        print("Task 3 (Prose — True No):")
        print(f"  Detection lift: {ev['detection_lift']} / {ev['seeded_errors']} seeded errors "
              f"({ev['detection_lift_rate']:.0%})")
        print(f"  Correlated failures: {ev['correlated_failure']}")
        print(f"  Expected outcome: D (oracle fails to add value over mirror).\n")
        summary["task3"] = ev

    # Verdict
    print("─" * 64)
    print("VERDICT:")
    if "task2_comparison" in summary:
        delta = summary["task2_comparison"]["delta_detection_lift"]
        if delta >= 2:
            print(f"  Oracle engineering is a DISCIPLINE (not merely cartography).")
            print(f"  Task 2 Run B outperformed Run A by {delta} detection lifts.")
            print(f"  The output-reshaping lever (structured JSON) created checkability")
            print(f"  where the prose oracle was noisy. Engineering choices matter.")
        elif delta > 0:
            print(f"  WEAK evidence for discipline: delta={delta} detection lifts.")
            print(f"  Signal is directional but small — more data needed.")
        else:
            print(f"  TAXONOMY hypothesis survives: no delta (Run B - Run A = {delta}).")
            print(f"  Checkability appears to be a property of the task structure,")
            print(f"  not of the engineering choices applied to it.")
    else:
        print("  Run both Task 2 modes (--run ab) to see the core comparison.")

    # Save summary
    summary_path = RESULTS_DIR / "final_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\n  Full results in: {RESULTS_DIR}/")


def main():
    parser = argparse.ArgumentParser(description="Oracle Engineering Smoke Test")
    parser.add_argument("--tasks", default="123", help="Which tasks to run: e.g. '1', '12', '123'")
    parser.add_argument("--regen", action="store_true", help="Force regeneration (ignore cache)")
    parser.add_argument("--run", default="ab", choices=["a", "b", "ab"],
                        help="Task 2 run mode (a=prose, b=structured, ab=both)")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        print("       export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    if "1" in args.tasks:
        run_task1(args.regen)

    if "2" in args.tasks:
        run_task2(args.regen, args.run)

    if "3" in args.tasks:
        run_task3(args.regen)

    print_final_summary()


if __name__ == "__main__":
    main()
