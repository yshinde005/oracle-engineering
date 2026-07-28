"""Generate short paragraphs for Task 3 topics."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.api import call_claude, compute_cost

SYSTEM_PROMPT = """You are a professional writer. Write clear, engaging, well-structured prose.
Follow the prompt exactly: write the requested number of sentences (3-5) on the specified topic.
Output ONLY the paragraph — no title, no preamble, no explanation.
"""


def generate_paragraph(prompt: str) -> tuple[str, dict]:
    """Returns (paragraph_text, usage_dict)."""
    content, usage = call_claude(SYSTEM_PROMPT, prompt, max_tokens=512)
    return content.strip(), usage


def generate_paragraph_variant(prompt: str, seed: int = 1) -> tuple[str, dict]:
    """Generate a second independent sample for consistency oracle (Candidate 4)."""
    system = SYSTEM_PROMPT + f"\nWrite a completely fresh paragraph — do not repeat phrasing from any previous attempt."
    content, usage = call_claude(system, prompt, max_tokens=512)
    return content.strip(), usage


if __name__ == "__main__":
    from task3_prose.topics import TOPICS
    para, usage = generate_paragraph(TOPICS[0]["prompt"])
    print(para)
    print(f"\nCost: ${compute_cost(usage):.4f}")
