"""Quality-degradation transforms for Task 3.

Each transform takes a good paragraph and degrades it in a specific way.
The degradation should produce paragraphs the mirror RATES HIGHLY (it's biased toward
accepting plausible prose) while a human would notice the defect.

Degradation types:
  no_topic_sentence       — move topic sentence to end, opening is abrupt
  circular_argument       — conclusion restates the premise verbatim
  non_sequitur            — insert an off-topic sentence in the middle
  tense_switch            — flip mid-paragraph from present to past tense
  excessive_hedging       — prefix every claim with 'perhaps' / 'maybe'
  remove_conclusion       — delete the final sentence
  reverse_paragraph       — reverse sentence order (conclusion comes first)
  factual_error           — for technical topics, replace a key term with a wrong one
"""
import re


def no_topic_sentence(text: str) -> str:
    """Move first sentence to the end."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) < 2:
        return text
    return " ".join(sentences[1:] + [sentences[0]])


def circular_argument(text: str) -> str:
    """Replace final sentence with a restatement of the first sentence."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) < 2:
        return text
    # Restate first sentence in slightly different words by inserting "In other words, "
    restated = "In other words, " + sentences[0][0].lower() + sentences[0][1:]
    return " ".join(sentences[:-1] + [restated])


def non_sequitur(text: str) -> str:
    """Insert an off-topic sentence in the middle."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    mid = max(1, len(sentences) // 2)
    filler = "Interestingly, the weather in coastal regions tends to be moderated by the thermal mass of the ocean."
    return " ".join(sentences[:mid] + [filler] + sentences[mid:])


def tense_switch(text: str) -> str:
    """Crudely flip present-tense verbs to past tense mid-paragraph."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) < 3:
        return text
    # Apply substitution only to the second half
    mid = len(sentences) // 2
    first_half = " ".join(sentences[:mid])
    second_half = " ".join(sentences[mid:])

    # Simple present → simple past substitutions
    second_half = re.sub(r'\bprovides\b', 'provided', second_half)
    second_half = re.sub(r'\benables\b', 'enabled', second_half)
    second_half = re.sub(r'\ballows\b', 'allowed', second_half)
    second_half = re.sub(r'\bcreates\b', 'created', second_half)
    second_half = re.sub(r'\boffers\b', 'offered', second_half)
    second_half = re.sub(r'\brequires\b', 'required', second_half)
    second_half = re.sub(r'\bensures\b', 'ensured', second_half)
    second_half = re.sub(r'\bmakes\b', 'made', second_half)
    second_half = re.sub(r'\bhelps\b', 'helped', second_half)
    second_half = re.sub(r'\bis\b', 'was', second_half)
    second_half = re.sub(r'\bare\b', 'were', second_half)
    second_half = re.sub(r'\bhas\b', 'had', second_half)

    return first_half + " " + second_half


def excessive_hedging(text: str) -> str:
    """Prepend 'Perhaps' or 'It might be argued that' to every sentence."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    hedges = ["Perhaps ", "It might be argued that ", "One could suggest that ",
              "Arguably, ", "It seems possible that "]
    result = []
    for i, s in enumerate(sentences):
        hedge = hedges[i % len(hedges)]
        s_hedged = hedge + s[0].lower() + s[1:]
        result.append(s_hedged)
    return " ".join(result)


def remove_conclusion(text: str) -> str:
    """Remove the final sentence."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) < 2:
        return text
    return " ".join(sentences[:-1])


def reverse_paragraph(text: str) -> str:
    """Reverse sentence order: conclusion first, topic sentence last."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return " ".join(reversed(sentences))


def factual_error_technical(text: str) -> str:
    """Introduce a factual error for technical topics by replacing a key term."""
    replacements = [
        (r'\bencrypts\b', 'compresses'),
        (r'\bencryption\b', 'compression'),
        (r'\bTLS\b', 'TCP'),
        (r'\bSSL\b', 'HTTP'),
        (r'\bone-way\b', 'two-way'),
        (r'\birreversibl\w+\b', 'reversible'),
        (r'\bcompiler\b', 'interpreter'),
        (r'\binterpreter\b', 'compiler'),
        (r'\bautomatic(ally)?\b', 'manually'),
        (r'\bweights\b', 'biases'),
        (r'\bloss function\b', 'activation function'),
        (r'\bJSON\b', 'XML'),
        (r'\bindex\b', 'cache'),
        (r'\bscan\b', 'index'),
    ]
    for pattern, replacement in replacements:
        new_text = re.sub(pattern, replacement, text, flags=re.IGNORECASE, count=1)
        if new_text != text:
            return new_text
    # No match: insert a wrong claim
    return text + " This process is identical to how lossless compression works."


# ── Error catalog ─────────────────────────────────────────────────────────────

DEGRADATIONS = [
    {
        "id": "d01",
        "degradation_type": "no_topic_sentence",
        "applies_to": ["product", "argument", "technical", "narrative"],
        "transform": no_topic_sentence,
        "description": "Topic sentence moved to end — reader has no orientation",
        "expected_oracle_catcher": "C2_structure",
    },
    {
        "id": "d02",
        "degradation_type": "circular_argument",
        "applies_to": ["argument"],
        "transform": circular_argument,
        "description": "Conclusion restates the premise verbatim — circular reasoning",
        "expected_oracle_catcher": None,  # no oracle catches this
    },
    {
        "id": "d03",
        "degradation_type": "non_sequitur",
        "applies_to": ["product", "argument", "technical"],
        "transform": non_sequitur,
        "description": "Off-topic sentence inserted mid-paragraph",
        "expected_oracle_catcher": None,  # C1 might catch via TTR change
    },
    {
        "id": "d04",
        "degradation_type": "tense_switch",
        "applies_to": ["technical", "argument"],
        "transform": tense_switch,
        "description": "Abrupt tense switch mid-paragraph",
        "expected_oracle_catcher": "C2_structure",
    },
    {
        "id": "d05",
        "degradation_type": "excessive_hedging",
        "applies_to": ["argument", "product"],
        "transform": excessive_hedging,
        "description": "Every sentence prefixed with a hedge — destroys confidence",
        "expected_oracle_catcher": "C2_structure",
    },
    {
        "id": "d06",
        "degradation_type": "remove_conclusion",
        "applies_to": ["product", "argument", "technical"],
        "transform": remove_conclusion,
        "description": "Final sentence removed — paragraph ends abruptly",
        "expected_oracle_catcher": "C2_structure",
    },
    {
        "id": "d07",
        "degradation_type": "reverse_paragraph",
        "applies_to": ["argument", "technical"],
        "transform": reverse_paragraph,
        "description": "Sentence order reversed — conclusion first, topic last",
        "expected_oracle_catcher": "C2_structure",
    },
    {
        "id": "d08",
        "degradation_type": "factual_error_technical",
        "applies_to": ["technical"],
        "transform": factual_error_technical,
        "description": "Key technical term replaced with a wrong one",
        "expected_oracle_catcher": "C3_factual",
    },
]
