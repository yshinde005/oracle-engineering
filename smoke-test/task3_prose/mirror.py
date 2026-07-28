"""Mirror: judge prose paragraph quality using Claude Sonnet."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import json

from shared.api import call_claude, compute_cost

SYSTEM_PROMPT = """You are a writing quality judge. Given a paragraph written in response to a prompt,
evaluate its quality on a 1-5 scale and determine whether it is well-written.

Quality rubric:
  5 — Excellent: clear topic sentence, logical flow, strong conclusion, vivid/precise language
  4 — Good: mostly clear structure and language, minor weaknesses
  3 — Adequate: conveys the information but weak structure or generic phrasing
  2 — Poor: missing structure (no topic sentence or conclusion), repetitive, or illogical
  1 — Very poor: incoherent, off-topic, contradictory, or drastically degraded

A paragraph is "correct" (well-written) if it scores 3 or higher.

Respond ONLY with a JSON object:
{
  "score": <1-5>,
  "verdict": "correct" | "incorrect",
  "confidence": "high" | "medium" | "low",
  "reasoning": "one to two sentences explaining the score"
}
"""


def evaluate_paragraph(prompt: str, paragraph: str) -> tuple[bool, str, int, dict]:
    """Returns (is_well_written, reasoning, score, usage_dict)."""
    user_msg = f"Prompt: {prompt}\n\nParagraph:\n{paragraph}"
    content, usage = call_claude(SYSTEM_PROMPT, user_msg, max_tokens=256)

    text = content.strip()
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
    if text.endswith("```"):
        text = text[:-3]

    try:
        result = json.loads(text.strip())
        is_correct = result.get("verdict", "").lower() == "correct"
        reasoning = result.get("reasoning", "")
        score = int(result.get("score", 3))
    except (json.JSONDecodeError, KeyError, ValueError):
        is_correct = True
        reasoning = content[:200]
        score = 3

    return is_correct, reasoning, score, usage


if __name__ == "__main__":
    from task3_prose.topics import TOPICS
    ok, reason, score, usage = evaluate_paragraph(
        TOPICS[0]["prompt"],
        "This is a placeholder paragraph. It is bad on purpose for testing."
    )
    print(f"Score: {score}/5, verdict: {'correct' if ok else 'incorrect'}")
    print(f"Reason: {reason}")
    print(f"Cost: ${compute_cost(usage):.4f}")
