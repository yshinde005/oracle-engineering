"""Offline re-scoring of saved Task 2 runs. Makes no API calls.

Reads a frozen snapshot of a previous run (default: smoke-test/data/original_run/):
  task2_run_a.json, task2_run_b.json             saved samples, incl. plan text
                                                  and the mirror's verdicts
  task2_prose_generated.json,
  task2_structured_generated.json                 the generator's clean plans

The plans and mirror verdicts are taken from the snapshot as-is; only the
oracle is re-run. Two subcommands:

  score   Re-score one run with the current oracle.
            --gt human   ground truth from human_labels.json (Run A only),
                         Check D excluded by default
            --gt oracle  legacy ground truth (clean = oracle verdict)

  replay  Run A then Run B through all four checks on ONE shared database,
          the way the original pipeline did, and compare each sample's verdict
          with its verdict on a pristine database. Shows which labels flip
          because of state leaking between samples.
            --check-d legacy  original Check D (no splitting, runs on the
                              shared DB, rollback doesn't undo DDL)
            --check-d fresh   current Check D (split + fresh copy per sample)

Usage:
  python -m task2_migration.offline score --run a --gt human
  python -m task2_migration.offline replay --check-d legacy
  python -m task2_migration.offline --snapshot <dir> verify
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.evaluation import SampleResult, compute_2x2, print_report
from task1_sql.database import create_and_seed
from task2_migration.errors import SEEDED_ERRORS
from task2_migration.oracle import evaluate_prose, evaluate_structured
from task2_migration.scenarios import SCENARIOS

DEFAULT_SNAPSHOT = Path(__file__).parent.parent / "data" / "original_run"
HUMAN_LABELS = Path(__file__).parent / "human_labels.json"
RUN_FILES = {"a": "task2_run_a.json", "b": "task2_run_b.json"}
CACHE_FILES = {"a": "task2_prose_generated.json", "b": "task2_structured_generated.json"}

_SC_BY_ID = {sc["id"]: sc for sc in SCENARIOS}
_ERR_BY_ID = {e["id"]: e for e in SEEDED_ERRORS}


# ── Loading ───────────────────────────────────────────────────────────────────

def _read_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Snapshot file missing: {path}")
    return json.loads(path.read_text())


def scenario_for(sample_id: str) -> dict:
    """'A-s01' → scenario s01; 'B-me03' → the scenario seeded error me03 targets."""
    key = sample_id.split("-", 1)[1]
    if key in _SC_BY_ID:
        return _SC_BY_ID[key]
    if key in _ERR_BY_ID:
        return _SC_BY_ID[_ERR_BY_ID[key]["scenario_id"]]
    raise KeyError(f"Cannot map sample {sample_id!r} to a scenario")


def load_samples(snapshot: Path, run: str) -> list[SampleResult]:
    """Rebuild SampleResults (plan text + saved mirror verdict) from a saved run file."""
    data = _read_json(snapshot / RUN_FILES[run])
    samples = []
    for d in data["samples"]:
        samples.append(SampleResult(
            id=d["id"],
            question=d.get("question", ""),
            output=d["output"],
            ground_truth=d["ground_truth"],
            is_seeded_error=d["is_seeded_error"],
            error_type=d.get("error_type"),
            mirror_verdict=d.get("mirror_verdict"),
            mirror_reasoning=d.get("mirror_reasoning", ""),
            oracle_verdict=d.get("oracle_verdict"),
            oracle_details=d.get("oracle_details") or {},
        ))
    return samples


def load_human_labels(path: Path = HUMAN_LABELS) -> dict[str, bool]:
    data = json.loads(path.read_text())
    return {k: v == "VALID" for k, v in data["labels"].items()}


# ── Oracle ────────────────────────────────────────────────────────────────────

def run_oracle(sample: SampleResult, db_path: Path, skip_checks=(), check_d_legacy=False):
    sc = scenario_for(sample.id)
    if sample.id.startswith("A-"):
        return evaluate_prose(sample.output, sc, db_path, skip_checks=skip_checks,
                              check_d_legacy=check_d_legacy)
    try:
        plan = json.loads(sample.output)
    except json.JSONDecodeError:
        return False, {"reason": "JSON parse error", "checks": {}}
    return evaluate_structured(plan, sc, db_path, skip_checks=skip_checks,
                               check_d_legacy=check_d_legacy)


def _seed_db(directory: Path, name: str = "company.db") -> Path:
    path = directory / name
    create_and_seed(path).close()
    return path


# ── score ─────────────────────────────────────────────────────────────────────

def score(snapshot: Path, run: str, gt: str, include_check_d: bool) -> tuple[list[SampleResult], dict]:
    samples = load_samples(snapshot, run)
    if any(s.mirror_verdict is None for s in samples):
        missing = [s.id for s in samples if s.mirror_verdict is None]
        raise ValueError(f"Snapshot has no mirror verdict for: {missing}")
    skip = () if include_check_d else ("D",)

    with tempfile.TemporaryDirectory() as tmp:
        db = _seed_db(Path(tmp))
        for s in samples:
            s.oracle_verdict, s.oracle_details = run_oracle(s, db, skip_checks=skip)

    if gt == "human":
        if run != "a":
            raise ValueError("Human labels exist for Run A only")
        labels = load_human_labels()
        missing = [s.id for s in samples if s.id not in labels]
        if missing:
            raise KeyError(f"No human label for: {missing}")
        for s in samples:
            s.ground_truth = labels[s.id]
    else:
        for s in samples:
            if not s.is_seeded_error:
                s.ground_truth = s.oracle_verdict

    m = compute_2x2(samples)
    invalid = [s for s in samples if s.ground_truth is False]
    caught = [s for s in invalid if s.oracle_verdict is False]
    mirror_caught = [s for s in invalid if s.mirror_verdict is False]
    summary = {
        "n": m["total_evaluated"],
        "mirror_accuracy": m["mirror_accuracy"],
        "oracle_accuracy": m["oracle_accuracy"],
        "real_errors": [s.id for s in invalid],
        "oracle_caught": [s.id for s in caught],
        "mirror_caught": [s.id for s in mirror_caught],
        "oracle_caught_not_mirror": sorted({s.id for s in caught} - {s.id for s in mirror_caught}),
        "detection_lift": m["detection_lift"],
        "oracle_only_error": m["oracle_only_error"],
        "correlated_failure": m["correlated_failure"],
        "oracle_false_alarms": [s.id for s in samples if s.ground_truth and s.oracle_verdict is False],
        "mirror_false_alarms": [s.id for s in samples if s.ground_truth and s.mirror_verdict is False],
    }
    return samples, summary


# ── replay ────────────────────────────────────────────────────────────────────

def replay(snapshot: Path, legacy: bool) -> list[dict]:
    """Run A then B on one shared DB; compare with each sample on a pristine DB."""
    samples = load_samples(snapshot, "a") + load_samples(snapshot, "b")
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shared_db = _seed_db(tmp, "shared.db")
        for s in samples:
            iso_db = _seed_db(tmp, "isolated.db")  # pristine for every sample
            iso_v, iso_d = run_oracle(s, iso_db, check_d_legacy=legacy)
            sh_v, sh_d = run_oracle(s, shared_db, check_d_legacy=legacy)
            rows.append({
                "id": s.id,
                "isolated": iso_v,
                "shared": sh_v,
                "original": s.oracle_verdict,
                "flipped": iso_v != sh_v,
                "isolated_d_errors": [e["error"] for e in iso_d.get("checks", {}).get("D", {}).get("errors", [])],
                "shared_d_errors": [e["error"] for e in sh_d.get("checks", {}).get("D", {}).get("errors", [])],
                "shared_failed_checks": sh_d.get("failed_checks", []),
            })
    return rows


# ── verify ────────────────────────────────────────────────────────────────────

def verify(snapshot: Path) -> list[str]:
    """Check the snapshot's seeded samples against the clean-plan caches.

    Reports seeded samples whose text is identical to the clean plan (the
    injection silently did nothing) and samples that differ from what the
    current transforms produce.
    """
    notes = []
    for run, transform_key in (("a", "transform_prose"), ("b", "transform_structured")):
        cache = _read_json(snapshot / CACHE_FILES[run])
        prefix = run.upper() + "-"
        for s in load_samples(snapshot, run):
            if not s.is_seeded_error:
                continue
            err = _ERR_BY_ID[s.id.removeprefix(prefix)]
            clean = cache[err["scenario_id"]]["plan"]
            clean_text = clean if run == "a" else json.dumps(clean)
            if s.output == clean_text:
                notes.append(f"{s.id}: identical to clean plan {err['scenario_id']} (injection had no effect)")
            transform = err.get(transform_key)
            if transform is not None:
                redo = transform(clean)
                redo_text = redo if run == "a" else json.dumps(redo)
                if redo_text != s.output:
                    notes.append(f"{s.id}: saved text differs from what the current transform produces")
    return notes


# ── CLI ───────────────────────────────────────────────────────────────────────

def _lab(v) -> str:
    return "VALID" if v else ("INVALID" if v is False else "—")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("score")
    p.add_argument("--run", choices=["a", "b"], default="a")
    p.add_argument("--gt", choices=["human", "oracle"], default="human")
    p.add_argument("--include-check-d", action="store_true",
                   help="also run Check D (excluded by default)")
    p = sub.add_parser("replay")
    p.add_argument("--check-d", choices=["legacy", "fresh"], required=True)
    sub.add_parser("verify")
    args = ap.parse_args(argv)

    if args.cmd == "score":
        samples, summary = score(args.snapshot, args.run, args.gt, args.include_check_d)
        checks = "A/B/C/D" if args.include_check_d else "A/B/C"
        print_report(f"Task 2 Run {args.run.upper()} offline — gt={args.gt}, checks {checks}", samples)
        print("\n  Summary:")
        for k, v in summary.items():
            print(f"    {k}: {v:.1%}" if isinstance(v, float) else f"    {k}: {v}")
    elif args.cmd == "replay":
        rows = replay(args.snapshot, legacy=args.check_d == "legacy")
        print(f"Replay A→B on one shared DB, Check D = {args.check_d}")
        print(f"{'sample':9} {'pristine':9} {'shared':9} {'original':9} shared-DB Check D errors")
        for r in rows:
            mark = "  <-- FLIP" if r["flipped"] else ""
            err = "; ".join(r["shared_d_errors"])[:90]
            print(f"{r['id']:9} {_lab(r['isolated']):9} {_lab(r['shared']):9} {_lab(r['original']):9} {err}{mark}")
        flips = [r["id"] for r in rows if r["flipped"]]
        print(f"\nFlipped (pristine vs shared DB): {len(flips)}/{len(rows)} {flips}")
    else:
        notes = verify(args.snapshot)
        print("\n".join(notes) if notes else "No issues found.")


if __name__ == "__main__":
    main()
