"""2×2 evaluation table: mirror × oracle × ground truth.

Ground truth: True = output is correct, False = output contains a seeded error.
Mirror verdict: True = mirror says correct, False = mirror says incorrect.
Oracle verdict: True = oracle says correct, False = oracle says incorrect.

The 2×2:
             | Oracle correct | Oracle wrong
-------------|----------------|---------------
Mirror right | agreement      | oracle-only-error
Mirror wrong | detection-lift | correlated-failure
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SampleResult:
    id: str
    question: str
    output: str
    ground_truth: bool
    is_seeded_error: bool
    error_type: Optional[str] = None
    mirror_verdict: Optional[bool] = None
    mirror_reasoning: str = ""
    oracle_verdict: Optional[bool] = None
    oracle_details: dict = field(default_factory=dict)
    usage_generate: dict = field(default_factory=dict)
    usage_mirror: dict = field(default_factory=dict)

    def mirror_correct(self) -> Optional[bool]:
        if self.mirror_verdict is None:
            return None
        return self.mirror_verdict == self.ground_truth

    def oracle_correct(self) -> Optional[bool]:
        if self.oracle_verdict is None:
            return None
        return self.oracle_verdict == self.ground_truth


def compute_2x2(results: list[SampleResult]) -> dict:
    """Compute the 2×2 confusion matrix between mirror and oracle."""
    evaluated = [
        r for r in results
        if r.mirror_verdict is not None and r.oracle_verdict is not None
    ]
    agreement_correct = 0    # both right
    detection_lift = 0       # oracle right, mirror wrong
    oracle_only_error = 0    # mirror right, oracle wrong
    correlated_failure = 0   # both wrong

    for r in evaluated:
        mc = r.mirror_correct()
        oc = r.oracle_correct()
        if mc and oc:
            agreement_correct += 1
        elif oc and not mc:
            detection_lift += 1
        elif mc and not oc:
            oracle_only_error += 1
        else:
            correlated_failure += 1

    n = len(evaluated)
    seeded = [r for r in evaluated if r.is_seeded_error]
    ns = len(seeded)

    return {
        "total_evaluated": n,
        "seeded_errors": ns,
        "clean_samples": n - ns,
        "agreement_correct": agreement_correct,
        "detection_lift": detection_lift,
        "oracle_only_error": oracle_only_error,
        "correlated_failure": correlated_failure,
        "mirror_accuracy": sum(1 for r in evaluated if r.mirror_correct()) / n if n else 0,
        "oracle_accuracy": sum(1 for r in evaluated if r.oracle_correct()) / n if n else 0,
        "mirror_error_rate_on_seeded": (
            sum(1 for r in seeded if not r.mirror_correct()) / ns if ns else 0
        ),
        "oracle_error_rate_on_seeded": (
            sum(1 for r in seeded if not r.oracle_correct()) / ns if ns else 0
        ),
        "detection_lift_rate": detection_lift / ns if ns else 0,
        "correlated_failure_rate": correlated_failure / ns if ns else 0,
    }


def print_report(task_name: str, results: list[SampleResult], extra: dict | None = None) -> None:
    m = compute_2x2(results)
    print(f"\n{'='*60}")
    print(f"  {task_name} — Evaluation Report")
    print(f"{'='*60}")
    print(f"  Samples: {m['total_evaluated']} total "
          f"({m['clean_samples']} clean, {m['seeded_errors']} seeded errors)")
    print(f"\n  2×2 Table (oracle col, mirror row):")
    print(f"                     Oracle ✓   Oracle ✗")
    print(f"  Mirror ✓   {m['agreement_correct']:>8}   {m['oracle_only_error']:>8}")
    print(f"  Mirror ✗   {m['detection_lift']:>8}   {m['correlated_failure']:>8}")
    print(f"\n  Mirror accuracy:        {m['mirror_accuracy']:.2%}")
    print(f"  Oracle accuracy:        {m['oracle_accuracy']:.2%}")
    print(f"  Mirror miss rate on seeded errors: {m['mirror_error_rate_on_seeded']:.2%}")
    print(f"  Oracle miss rate on seeded errors: {m['oracle_error_rate_on_seeded']:.2%}")
    print(f"\n  Detection lift: {m['detection_lift']} cases "
          f"({m['detection_lift_rate']:.2%} of seeded errors)")
    print(f"  Correlated failures: {m['correlated_failure']} cases "
          f"({m['correlated_failure_rate']:.2%} of seeded errors)")

    if extra:
        print(f"\n  Additional metrics:")
        for k, v in extra.items():
            print(f"    {k}: {v}")

    # Print detection-lift examples
    lift_cases = [r for r in results if r.oracle_correct() and not r.mirror_correct()]
    if lift_cases:
        print(f"\n  Detection Lift Examples:")
        for r in lift_cases[:3]:
            print(f"    [{r.id}] error_type={r.error_type}")
            print(f"      Mirror said: {'correct' if r.mirror_verdict else 'incorrect'} — {r.mirror_reasoning[:80]}")
            print(f"      Oracle: {r.oracle_details.get('reason', '')[:80]}")

    # Print correlated failures
    fail_cases = [r for r in results if not r.oracle_correct() and not r.mirror_correct()]
    if fail_cases:
        print(f"\n  Correlated Failures:")
        for r in fail_cases[:3]:
            print(f"    [{r.id}] error_type={r.error_type}")


def save_results(path: Path, task_name: str, results: list[SampleResult],
                 total_cost_usd: float, extra: dict | None = None) -> None:
    data = {
        "task": task_name,
        "total_cost_usd": round(total_cost_usd, 4),
        "evaluation": compute_2x2(results),
        "extra": extra or {},
        "samples": [
            {
                "id": r.id,
                "question": r.question,
                "output": r.output,
                "ground_truth": r.ground_truth,
                "is_seeded_error": r.is_seeded_error,
                "error_type": r.error_type,
                "mirror_verdict": r.mirror_verdict,
                "mirror_reasoning": r.mirror_reasoning,
                "oracle_verdict": r.oracle_verdict,
                "oracle_details": r.oracle_details,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(data, indent=2))
    print(f"\n  Results saved → {path}")
