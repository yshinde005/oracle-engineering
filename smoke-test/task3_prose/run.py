"""Orchestrate Task 3 (Prose Quality).

Usage:
  python -m task3_prose.run           # full run (generates if not cached)
  python -m task3_prose.run --regen   # force regeneration
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from shared.api import compute_cost
from shared.evaluation import SampleResult, print_report, save_results
from task3_prose.topics import TOPICS
from task3_prose.generator import generate_paragraph, generate_paragraph_variant
from task3_prose.mirror import evaluate_paragraph
from task3_prose.oracle import evaluate
from task3_prose.errors import DEGRADATIONS

RESULTS_DIR = Path(__file__).parent.parent / "results"
CACHE_FILE = RESULTS_DIR / "task3_generated.json"
RESULTS_FILE = RESULTS_DIR / "task3_results.json"
ORACLE_ANALYSIS_FILE = RESULTS_DIR / "task3_oracle_analysis.json"


def run(force_regen: bool = False) -> list[SampleResult]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Task 3 — Prose Quality")

    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() and not force_regen else {}
    total_gen_cost = 0.0

    if not cache or force_regen:
        print(f"\nGenerating paragraphs for {len(TOPICS)} topics (+ variants for consistency oracle)...")
        for i, topic in enumerate(TOPICS, 1):
            print(f"  [{i:02d}/{len(TOPICS)}] {topic['id']}: {topic['prompt'][:60]}...")
            para, usage = generate_paragraph(topic["prompt"])
            cost = compute_cost(usage)
            total_gen_cost += cost

            variant, u2 = generate_paragraph_variant(topic["prompt"])
            total_gen_cost += compute_cost(u2)

            cache[topic["id"]] = {
                "para": para,
                "variant": variant,
                "usage": usage,
                "usage_variant": u2,
            }

        CACHE_FILE.write_text(json.dumps(cache, indent=2))
        print(f"  Generation complete. Cost: ${total_gen_cost:.4f}")
    else:
        print(f"  Loaded {len(cache)} cached paragraphs.")

    topic_by_id = {t["id"]: t for t in TOPICS}
    samples: list[SampleResult] = []

    # ── Clean samples ─────────────────────────────────────────────────────
    for topic in TOPICS:
        entry = cache[topic["id"]]
        samples.append(SampleResult(
            id=topic["id"],
            question=topic["prompt"],
            output=entry["para"],
            ground_truth=True,
            is_seeded_error=False,
        ))

    # ── Seeded quality-degradation samples ────────────────────────────────
    for topic in TOPICS:
        entry = cache[topic["id"]]
        para = entry["para"]
        cat = topic["category"]

        for deg in DEGRADATIONS:
            if cat not in deg["applies_to"]:
                continue
            try:
                degraded = deg["transform"](para)
            except Exception as e:
                print(f"  Warning: {deg['id']} on {topic['id']}: {e}")
                continue

            sample_id = f"{topic['id']}-{deg['id']}"
            samples.append(SampleResult(
                id=sample_id,
                question=topic["prompt"],
                output=degraded,
                ground_truth=False,
                is_seeded_error=True,
                error_type=deg["degradation_type"],
            ))

    print(f"\n  Total samples: {len(samples)} ({len(TOPICS)} clean + {len(samples)-len(TOPICS)} degraded)")

    # ── Mirror evaluation ─────────────────────────────────────────────────
    print(f"\nRunning mirror on {len(samples)} samples...")
    total_mirror_cost = 0.0
    mirror_scores: dict[str, int] = {}

    for i, s in enumerate(samples, 1):
        verdict, reasoning, score, usage = evaluate_paragraph(s.question, s.output)
        s.mirror_verdict = verdict
        s.mirror_reasoning = f"score={score}: {reasoning}"
        s.usage_mirror = usage
        total_mirror_cost += compute_cost(usage)
        mirror_scores[s.id] = score
        print(f"  [{i:03d}/{len(samples)}] {s.id}: mirror={'✓' if verdict else '✗'} score={score}")

    print(f"  Mirror cost: ${total_mirror_cost:.4f}")

    # ── Oracle evaluation ─────────────────────────────────────────────────
    print(f"\nRunning oracle on {len(samples)} samples...")
    for s in samples:
        # Determine topic_id for this sample
        topic_id = s.id.split("-")[0] if "-" in s.id else s.id
        topic = topic_by_id.get(topic_id)
        if topic is None:
            continue

        entry = cache.get(topic_id, {})
        variant = entry.get("variant") if not s.is_seeded_error else None

        verdict, details = evaluate(s.output, variant, topic)
        s.oracle_verdict = verdict
        s.oracle_details = details
        print(f"  {s.id}: oracle={'✓' if verdict else '✗'}  {details['reason'][:60]}")

    # For clean samples, treat oracle verdict as ground truth
    # (we expect oracle to pass most things; ground truth IS our quality labeling)
    # For seeded errors, ground_truth = False (we know they're degraded)
    # For clean samples, mirror score < 3 means the generated output was actually bad
    for s in samples:
        if not s.is_seeded_error:
            score = mirror_scores.get(s.id, 3)
            s.ground_truth = score >= 3  # mirror is our reference for clean samples

    # ── Report ────────────────────────────────────────────────────────────
    total_cost = total_gen_cost + total_mirror_cost
    print_report("Task 3 — Prose Quality", samples)
    print(f"\n  Total API cost: ${total_cost:.4f}")

    # ── Oracle analysis: per-candidate breakdown ──────────────────────────
    candidate_stats = {f"C{i}": {"caught": 0, "total_seeded": 0, "missed": 0}
                       for i in range(1, 5)}
    for s in samples:
        if not s.is_seeded_error:
            continue
        checks = s.oracle_details.get("checks", {})
        for k, v in checks.items():
            for cname, cstats in candidate_stats.items():
                if k.startswith(cname):
                    cstats["total_seeded"] += 1
                    if v.get("passed") is False:
                        cstats["caught"] += 1
                    elif v.get("passed") is True:
                        cstats["missed"] += 1

    print("\n  Oracle Candidate Analysis (on seeded errors):")
    for cname, stats in candidate_stats.items():
        caught = stats["caught"]
        total = stats["total_seeded"]
        rate = f"{caught/total:.0%}" if total > 0 else "N/A"
        print(f"    {cname}: caught {caught}/{total} seeded errors ({rate})")

    oracle_analysis = {
        "candidate_stats": candidate_stats,
        "interpretation": (
            "No candidate shows reliable detection lift — confirms Task 3 is True No territory"
            if all(s["caught"] / s["total_seeded"] < 0.3
                   for s in candidate_stats.values() if s["total_seeded"] > 0)
            else "Some candidate shows detection lift — re-examine True No assumption"
        ),
    }
    ORACLE_ANALYSIS_FILE.write_text(json.dumps(oracle_analysis, indent=2))
    save_results(RESULTS_FILE, "task3_prose", samples, total_cost, extra=oracle_analysis)
    return samples


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--regen", action="store_true")
    args = parser.parse_args()
    run(force_regen=args.regen)
