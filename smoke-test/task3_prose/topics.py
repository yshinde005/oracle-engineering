"""25 paragraph topics for Task 3 (Prose Quality).

Each topic specifies:
  id, category, prompt, factual_claim_to_check (if any)

Categories:
  product      — product description (factual + persuasive)
  argument     — policy/opinion paragraph
  technical    — technical explanation (verifiable facts)
  narrative    — story hook / opening paragraph
"""

TOPICS = [
    # ── Product descriptions ──────────────────────────────────────────────
    {
        "id": "p01",
        "category": "product",
        "prompt": "Write a compelling 3-5 sentence product description for a pair of over-ear noise-canceling headphones priced at $299.",
        "factual_check": None,
    },
    {
        "id": "p02",
        "category": "product",
        "prompt": "Write a 3-5 sentence product description for a smart home thermostat that learns your temperature preferences over time.",
        "factual_check": None,
    },
    {
        "id": "p03",
        "category": "product",
        "prompt": "Write a 3-5 sentence product description for an ergonomic mechanical keyboard with per-key RGB lighting.",
        "factual_check": None,
    },
    {
        "id": "p04",
        "category": "product",
        "prompt": "Write a 3-5 sentence product description for a portable water purifier that uses UV light to kill bacteria.",
        "factual_check": "UV light can kill bacteria and viruses",
    },
    {
        "id": "p05",
        "category": "product",
        "prompt": "Write a 3-5 sentence product description for an AI-powered writing assistant that suggests edits as you type.",
        "factual_check": None,
    },
    # ── Policy arguments ──────────────────────────────────────────────────
    {
        "id": "p06",
        "category": "argument",
        "prompt": "Write a 3-5 sentence paragraph arguing in favor of mandatory four-day work weeks for office employees.",
        "factual_check": None,
    },
    {
        "id": "p07",
        "category": "argument",
        "prompt": "Write a 3-5 sentence paragraph arguing that cities should ban single-use plastic bags.",
        "factual_check": None,
    },
    {
        "id": "p08",
        "category": "argument",
        "prompt": "Write a 3-5 sentence paragraph arguing that coding should be taught in all primary schools.",
        "factual_check": None,
    },
    {
        "id": "p09",
        "category": "argument",
        "prompt": "Write a 3-5 sentence paragraph arguing that remote work permanently improves employee productivity.",
        "factual_check": None,
    },
    {
        "id": "p10",
        "category": "argument",
        "prompt": "Write a 3-5 sentence paragraph arguing that social media companies should be held liable for misinformation spread on their platforms.",
        "factual_check": None,
    },
    # ── Technical explanations ────────────────────────────────────────────
    {
        "id": "p11",
        "category": "technical",
        "prompt": "Explain in 3-5 sentences what a database index is and why it speeds up queries.",
        "factual_check": "A database index allows the database engine to find rows without scanning the entire table",
    },
    {
        "id": "p12",
        "category": "technical",
        "prompt": "Explain in 3-5 sentences how HTTPS protects data in transit between a browser and a server.",
        "factual_check": "HTTPS uses TLS/SSL encryption",
    },
    {
        "id": "p13",
        "category": "technical",
        "prompt": "Explain in 3-5 sentences what a hash function is and why it is used in password storage.",
        "factual_check": "Hash functions are one-way; you cannot reverse a hash to get the original password",
    },
    {
        "id": "p14",
        "category": "technical",
        "prompt": "Explain in 3-5 sentences how a compiler differs from an interpreter when executing code.",
        "factual_check": "A compiler translates the entire source program to machine code before execution; an interpreter executes line by line",
    },
    {
        "id": "p15",
        "category": "technical",
        "prompt": "Explain in 3-5 sentences what garbage collection is in programming and why it prevents memory leaks.",
        "factual_check": "Garbage collection automatically reclaims memory that is no longer referenced",
    },
    {
        "id": "p16",
        "category": "technical",
        "prompt": "Explain in 3-5 sentences what a REST API is and how it differs from a traditional web page request.",
        "factual_check": "REST APIs return structured data (typically JSON or XML), not HTML pages",
    },
    {
        "id": "p17",
        "category": "technical",
        "prompt": "Explain in 3-5 sentences what a neural network is and how it learns from training data.",
        "factual_check": "Neural networks adjust weights during training to minimize a loss function",
    },
    # ── Narrative hooks ───────────────────────────────────────────────────
    {
        "id": "p18",
        "category": "narrative",
        "prompt": "Write a 3-5 sentence opening hook for a thriller novel in which a forensic accountant discovers an anomaly in a multinational corporation's books.",
        "factual_check": None,
    },
    {
        "id": "p19",
        "category": "narrative",
        "prompt": "Write a 3-5 sentence opening hook for a science fiction story set on a generation ship where the captain has just died.",
        "factual_check": None,
    },
    {
        "id": "p20",
        "category": "narrative",
        "prompt": "Write a 3-5 sentence opening hook for a mystery story that begins with a librarian finding a coded message in a returned book.",
        "factual_check": None,
    },
    {
        "id": "p21",
        "category": "narrative",
        "prompt": "Write a 3-5 sentence opening hook for a literary story about a professional chess player preparing for her final tournament.",
        "factual_check": None,
    },
    {
        "id": "p22",
        "category": "narrative",
        "prompt": "Write a 3-5 sentence opening hook for a historical fiction piece set in 1940s Vienna, following a jazz musician navigating occupied Europe.",
        "factual_check": None,
    },
    # ── Mixed / harder ────────────────────────────────────────────────────
    {
        "id": "p23",
        "category": "argument",
        "prompt": "Write a 3-5 sentence paragraph arguing that open-source software makes critical infrastructure more secure, not less.",
        "factual_check": None,
    },
    {
        "id": "p24",
        "category": "technical",
        "prompt": "Explain in 3-5 sentences what eventual consistency means in distributed databases and when it is acceptable.",
        "factual_check": "Eventual consistency means all replicas will converge to the same state given enough time without new updates",
    },
    {
        "id": "p25",
        "category": "product",
        "prompt": "Write a 3-5 sentence product description for a standing desk converter that adjusts height electronically and pairs with a companion app.",
        "factual_check": None,
    },
]
