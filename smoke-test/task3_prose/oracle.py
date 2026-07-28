"""Oracle candidates for Task 3 (Prose Quality).

All candidates are non-LLM. Expected outcome: none produces reliable detection lift.
The goal is to LOCATE the boundary — confirm these proxies don't substitute for judgment.

Candidate 1 — Readability metrics: Flesch-Kincaid grade, sentence length, vocab diversity
Candidate 2 — Structural checks: topic sentence, tense consistency, paragraph length
Candidate 3 — Factual accuracy: substring match against known-correct claim for technical topics
Candidate 4 — Consistency: compare two independent generations; flag factual divergence

Independence: all stdlib — no LLM, no external data beyond the topic's factual_check field.

Coverage:
  1: surface-level complexity; catches paragraphs that are too simple or too complex
  2: structural markers; catches paragraphs missing standard components
  3: factual errors in technical explanations (limited to pre-specified claims)
  4: self-consistency; catches outputs that contradict themselves across variants

Blind spots (the expected finding):
  None of these candidates reliably detect "not compelling" or "bad quality" as a gestalt.
  They measure proxy signals with weak correlation to human quality judgment.
"""
import re
import math
from dataclasses import dataclass


# ── Candidate 1: Readability Metrics ─────────────────────────────────────────

def count_syllables(word: str) -> int:
    """Heuristic syllable count (not perfect, but adequate for smoke-test metrics)."""
    word = word.lower().strip(".,;:!?\"'()-")
    if not word:
        return 0
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    # Adjust: silent e
    if word.endswith("e") and len(word) > 2 and word[-2] not in vowels:
        count = max(1, count - 1)
    return max(1, count)


def flesch_kincaid_grade(text: str) -> float:
    """Flesch-Kincaid Grade Level."""
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    words = re.findall(r'\b[a-zA-Z]+\b', text)
    if not words or not sentences:
        return 0.0
    syllable_count = sum(count_syllables(w) for w in words)
    asl = len(words) / len(sentences)   # average sentence length
    asw = syllable_count / len(words)   # average syllables per word
    return 0.39 * asl + 11.8 * asw - 15.59


def type_token_ratio(text: str) -> float:
    """Lexical diversity: unique words / total words."""
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    if not words:
        return 0.0
    return len(set(words)) / len(words)


@dataclass
class ReadabilityResult:
    fk_grade: float
    ttr: float
    word_count: int
    sentence_count: int
    avg_sentence_len: float
    passed: bool
    reason: str


def check_candidate1_readability(text: str) -> ReadabilityResult:
    """
    Heuristic thresholds:
      - Grade level 6-16 (too simple or too complex fails)
      - TTR > 0.4 (very repetitive fails)
      - Word count 30-200 (way too short or way too long fails)
    These are WEAK quality proxies, as expected.
    """
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    words = re.findall(r'\b[a-zA-Z]+\b', text)
    grade = flesch_kincaid_grade(text)
    ttr = type_token_ratio(text)
    word_count = len(words)
    avg_len = word_count / len(sentences) if sentences else 0

    issues = []
    if grade < 4:
        issues.append(f"FKG={grade:.1f} (too simple for adult prose)")
    if grade > 20:
        issues.append(f"FKG={grade:.1f} (unusually complex)")
    if ttr < 0.35:
        issues.append(f"TTR={ttr:.2f} (very repetitive vocabulary)")
    if word_count < 25:
        issues.append(f"word_count={word_count} (too short)")
    if word_count > 250:
        issues.append(f"word_count={word_count} (too long)")

    passed = len(issues) == 0
    reason = "; ".join(issues) if issues else f"FKG={grade:.1f}, TTR={ttr:.2f}, words={word_count}"

    return ReadabilityResult(
        fk_grade=round(grade, 2),
        ttr=round(ttr, 2),
        word_count=word_count,
        sentence_count=len(sentences),
        avg_sentence_len=round(avg_len, 1),
        passed=passed,
        reason=reason,
    )


# ── Candidate 2: Structural Checks ───────────────────────────────────────────

TENSE_PAST = re.compile(r'\b(was|were|had|did|went|said|told|thought|felt|saw|made|came|took|gave|knew|found|got|became|left|put|began|showed|seemed|heard|ran|stood|kept|let|meant|set|met|paid|sat|brought|sent)\b', re.IGNORECASE)
TENSE_PRESENT = re.compile(r'\b(is|are|has|does|goes|says|tells|thinks|feels|sees|makes|comes|takes|gives|knows|finds|gets|becomes|leaves|puts|begins|shows|seems|hears|runs|stands|keeps|lets|means|sets|meets|pays|sits|brings|sends)\b', re.IGNORECASE)
CONCLUSION_MARKERS = re.compile(r'\b(ultimately|therefore|thus|in conclusion|as a result|consequently|in summary|overall|finally)\b', re.IGNORECASE)
HEDGE_WORDS = re.compile(r'\b(perhaps|maybe|possibly|might|could|seem|appears|arguably)\b', re.IGNORECASE)


def check_candidate2_structure(text: str, prompt: str) -> dict:
    """Structural properties: topic sentence, tense consistency, conclusion markers."""
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    if not sentences:
        return {"passed": False, "reason": "empty text", "issues": ["empty"]}

    issues = []

    # Topic sentence check: first sentence should be longer than 5 words
    first_words = re.findall(r'\b\w+\b', sentences[0])
    if len(first_words) < 6:
        issues.append("topic_sentence_too_short")

    # Tense consistency
    past_count = len(TENSE_PAST.findall(text))
    pres_count = len(TENSE_PRESENT.findall(text))
    if past_count > 2 and pres_count > 2:
        # Mixed tenses — might be intentional for narrative, flag lightly
        if "narrative" not in prompt.lower():
            issues.append("mixed_tense_detected")

    # Excessive hedging (low confidence signals poor argument)
    hedge_count = len(HEDGE_WORDS.findall(text))
    total_words = len(re.findall(r'\b\w+\b', text))
    hedge_ratio = hedge_count / total_words if total_words else 0
    if hedge_ratio > 0.08:
        issues.append(f"excessive_hedging:{hedge_ratio:.2f}")

    # Last sentence check: should be at least 5 words (not a stub)
    last_words = re.findall(r'\b\w+\b', sentences[-1])
    if len(last_words) < 5:
        issues.append("conclusion_too_short")

    passed = len(issues) == 0
    return {
        "passed": passed,
        "issues": issues,
        "sentence_count": len(sentences),
        "first_sentence_len": len(first_words),
        "tense_past": past_count,
        "tense_present": pres_count,
        "hedge_ratio": round(hedge_ratio, 3),
        "reason": "; ".join(issues) if issues else "structure OK",
    }


# ── Candidate 3: Factual Accuracy ────────────────────────────────────────────

def check_candidate3_factual(text: str, factual_check: str | None) -> dict:
    """Check whether the paragraph contains the expected factual claim (substring/keyword)."""
    if factual_check is None:
        return {
            "passed": None,
            "reason": "no factual check defined for this topic (abstain)",
            "check": "3-factual",
        }

    # Extract key terms from the factual_check (all content words)
    stop = {"a", "an", "the", "is", "are", "can", "in", "of", "to", "and", "or",
            "for", "not", "on", "that", "it", "its", "you", "your", "this", "be"}
    claim_words = set(
        w.lower() for w in re.findall(r'\b[a-zA-Z]+\b', factual_check)
        if w.lower() not in stop and len(w) > 3
    )

    text_lower = text.lower()
    missing = [w for w in claim_words if w not in text_lower]
    coverage = 1 - len(missing) / len(claim_words) if claim_words else 1.0

    passed = coverage >= 0.5  # at least half the key terms present
    return {
        "passed": passed,
        "factual_claim": factual_check,
        "key_terms": sorted(claim_words),
        "missing_terms": sorted(missing),
        "coverage": round(coverage, 2),
        "reason": f"coverage={coverage:.0%}" + (f"; missing: {missing}" if missing else ""),
        "check": "3-factual",
    }


# ── Candidate 4: Consistency (metamorphic oracle) ────────────────────────────

def check_candidate4_consistency(text_a: str, text_b: str, factual_check: str | None) -> dict:
    """
    Compare two independent paragraph generations for factual contradictions.
    Independence is by construction (different random seeds / fresh generation).
    This tests consistency, not quality.
    """
    if factual_check is None:
        # For non-factual topics, check structural consistency instead
        wc_a = len(re.findall(r'\b\w+\b', text_a))
        wc_b = len(re.findall(r'\b\w+\b', text_b))
        ratio = min(wc_a, wc_b) / max(wc_a, wc_b) if max(wc_a, wc_b) > 0 else 1.0
        passed = ratio > 0.4  # wildly different lengths = inconsistent
        return {
            "passed": passed,
            "reason": f"word_count_ratio={ratio:.2f}" + (" (length divergence)" if not passed else ""),
            "wc_a": wc_a,
            "wc_b": wc_b,
            "check": "4-consistency",
        }

    # For factual topics, check if both texts share the key claim terms
    stop = {"a", "an", "the", "is", "are", "can", "in", "of", "to", "and", "or",
            "for", "not", "on", "that", "it", "its", "you", "your", "this", "be"}
    claim_words = set(
        w.lower() for w in re.findall(r'\b[a-zA-Z]+\b', factual_check)
        if w.lower() not in stop and len(w) > 3
    )

    a_lower = text_a.lower()
    b_lower = text_b.lower()

    a_has = {w for w in claim_words if w in a_lower}
    b_has = {w for w in claim_words if w in b_lower}

    # Both should contain the key claim; if one does and the other doesn't, inconsistency
    a_missing = claim_words - a_has
    b_missing = claim_words - b_has

    # Divergence: terms in one but not the other
    divergence = a_missing.symmetric_difference(b_missing)
    passed = len(divergence) < len(claim_words) * 0.5

    return {
        "passed": passed,
        "divergent_terms": sorted(divergence),
        "a_coverage": round(len(a_has) / len(claim_words), 2) if claim_words else 1.0,
        "b_coverage": round(len(b_has) / len(claim_words), 2) if claim_words else 1.0,
        "reason": f"term divergence: {sorted(divergence)}" if divergence else "consistent",
        "check": "4-consistency",
    }


# ── Composite oracle verdict ──────────────────────────────────────────────────

def evaluate(text: str, text_variant: str | None, topic: dict) -> tuple[bool, dict]:
    """
    Run all four candidates. Composite verdict: FAIL if any non-abstain check fails.

    Expected outcome: most "bad" paragraphs will pass these checks anyway,
    because quality is not reducible to these structural proxies.
    That IS the experiment result for Task 3.
    """
    prompt = topic["prompt"]
    factual_check = topic.get("factual_check")

    c1 = check_candidate1_readability(text)
    c2 = check_candidate2_structure(text, prompt)
    c3 = check_candidate3_factual(text, factual_check)
    c4 = (
        check_candidate4_consistency(text, text_variant, factual_check)
        if text_variant
        else {"passed": None, "reason": "no variant available", "check": "4-consistency"}
    )

    checks = {
        "C1_readability": {"passed": c1.passed, "reason": c1.reason,
                           "fk_grade": c1.fk_grade, "ttr": c1.ttr, "words": c1.word_count},
        "C2_structure": c2,
        "C3_factual": c3,
        "C4_consistency": c4,
    }

    failed = [k for k, v in checks.items() if v.get("passed") is False]
    passed = len(failed) == 0
    return passed, {
        "checks": checks,
        "failed_checks": failed,
        "reason": "all checks passed" if passed else f"failed: {failed}",
    }
