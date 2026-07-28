# Oracle Engineering

Research into independent, non-LLM verification of LLM output using
**structural oracles** — deterministic checks derived from the same
artifacts an LLM verifier reasons over (a patch diff, a query plan, a
document structure), but computed without any model call.

The core question: can a structural oracle replace, or usefully
cross-check, an LLM verifier on **bypass-vs-rediscovery classification**
— deciding whether a security finding describes a genuine bypass of a
patch (the patch doesn't cover this code path) or a rediscovery of
something the patch already fixes (the patch does cover it)? An LLM
verifier ("the mirror") makes this call by reasoning over the diff and
the finding's citations. A structural oracle makes the same call by
mechanically checking whether the finding's cited file+line locations
fall inside the patch's modified hunks — no model, no judgment call,
just diff-hunk arithmetic.

This repo is **research code exploring a methodology, not a production
tool**. It exists to answer: does the oracle agree with the mirror when
both should be right, and — more importantly — does the oracle catch
cases where the mirror is wrong ("detection lift"), without introducing
its own correlated failures?

## Components

### `classifier/`

The structural oracle implementation, plus the evaluation harness that
compares it against real LLM-verifier output on recorded security
findings.

- **`structural-oracle.ts`** — the oracle itself. Two checks: (1)
  citation-patch overlap (does a cited file+line fall inside a patched
  diff hunk?) and (2) guard presence (derived from (1): a citation
  inside a patched hunk means the patch's guard applies there).
  Classification: overlap → `likely_rediscovery`, disjoint →
  `likely_bypass`, partial (patched file, unpatched lines) →
  `inconclusive` — the oracle's known blind spot. No imports beyond
  its own type definitions; zero dependencies.
- **`structural-oracle.test.ts`** — unit tests for the diff parser and
  classifier logic, plus integration tests that replay real recorded
  findings through the oracle.
- **`run-oracle-evaluation.ts`** — evaluation script. Loads findings
  with a `bypass_variant_type` field (the mirror's verdict) from a
  findings directory, runs the oracle on each, and reports a
  per-finding comparison table plus aggregate detection-lift /
  correlated-failure counts against a hardcoded human ground-truth
  table.

**Run the tests:**
```sh
cd classifier
npm install
npx vitest run
```

**Run the evaluation** against a findings directory (see note below):
```sh
cd classifier
npx tsx run-oracle-evaluation.ts --findings-dir <path-to-findings-dir> [--repo-root <path>]
```

> **Note on running the integration tests and evaluation script:** both
> `structural-oracle.test.ts`'s integration suite and
> `run-oracle-evaluation.ts` need a findings directory (one subdirectory
> per run, each with `audit.config.json` + `findings.jsonl`) and the
> cloned target repos each run's patch commit was taken from (for `git
> show`). That data intentionally was **not** copied into this repo —
> it's the Loci auditor's accumulated run output (1,800+ directories),
> not oracle-engineering research artifacts. `run-oracle-evaluation.ts`
> takes the findings directory as a `--findings-dir` CLI argument (with
> an optional `--repo-root` to relocate the target repo clones);
> `structural-oracle.test.ts`'s integration block still has the old
> monorepo-relative path baked in and **will fail with ENOENT if run
> here without that data present** — it was copied unchanged from the
> Loci auditor repo, since only the evaluation script was in scope for
> refactoring. Its unit tests (the `parseHunks` and `runStructuralOracle`
> describe blocks) don't touch the filesystem and will pass on their own.

### `smoke-test/`

A three-task experiment comparing the oracle-style classification
approach against LLM-verifier ("mirror") classification across three
different domains: SQL query correctness, database migration planning,
and prose generation. Each task (`task1_sql/`, `task2_migration/`,
`task3_prose/`) generates an LLM output against a seeded scenario
(some correct, some with a deliberately seeded error), then scores it
two ways — via a structural/mechanical oracle (`oracle.py`) and via an
LLM mirror call (`mirror.py`) — and compares the two verdicts against
the known ground truth.

**Run it:**
```sh
cd smoke-test
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python run_all.py
```

Results are written to `results/` (gitignored — regeneratable run
output, not source).

## Relationship between the two components

They're independent experiments testing the same underlying question
from different angles: `classifier/` evaluates the oracle approach
against real security-audit findings from a specific LLM-based auditor
(Loci); `smoke-test/` evaluates it across three synthetic, controlled
domains. Neither depends on the other or on the Loci codebase.
