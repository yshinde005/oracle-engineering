"""Claude API wrapper: generator + mirror calls with caching support."""
import json
import os
import time

# `anthropic` is imported lazily so offline re-scoring (no API calls) works
# without the package installed.

MODEL = "claude-sonnet-4-6"
COST_PER_INPUT_TOKEN = 3.0 / 1_000_000
COST_PER_OUTPUT_TOKEN = 15.0 / 1_000_000

_client = None  # anthropic.Anthropic, created on first use


def get_client():
    import anthropic

    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY environment variable not set.\n"
                "Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
            )
        _client = anthropic.Anthropic(api_key=key)
    return _client


def call_claude(system: str, user: str, max_tokens: int = 2048) -> tuple[str, dict]:
    """Returns (content_text, usage_dict). Retries once on transient errors."""
    import anthropic

    client = get_client()
    for attempt in range(2):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
            return response.content[0].text, usage
        except anthropic.RateLimitError:
            if attempt == 0:
                time.sleep(30)
            else:
                raise
        except anthropic.APIStatusError as e:
            if attempt == 0 and e.status_code >= 500:
                time.sleep(5)
            else:
                raise
    raise RuntimeError("Unreachable")


def call_json(system: str, user: str, max_tokens: int = 2048) -> tuple[dict, dict]:
    """Call Claude expecting a JSON response (handles ```json ... ``` fences)."""
    content, usage = call_claude(system, user, max_tokens)
    text = content.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip()), usage


def compute_cost(usage: dict) -> float:
    return (
        usage["input_tokens"] * COST_PER_INPUT_TOKEN
        + usage["output_tokens"] * COST_PER_OUTPUT_TOKEN
    )


def total_cost(usages: list[dict]) -> float:
    return sum(compute_cost(u) for u in usages)
