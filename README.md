# Oracle Engineering

Research code on checking LLM output with **structural oracles**:
deterministic checks that make no model calls. This repo is **research
code exploring a methodology, not a production tool**.

## Summary

The question: when an LLM verifier checks another LLM's output, can a
cheap deterministic check catch the verifier's mistakes without making
the same mistakes itself? The main test case is deciding whether a
security finding is a real *bypass* of a patch or a *rediscovery* of
what the patch already fixed. On 17 findings (15 human-labeled, 2
unlabeled), an oracle that only does diff-hunk arithmetic caught all 3
errors the LLM verifier made. But it abstained on about 41% of findings, and
adversarial testing found two bugs that cause false rediscoveries. A
synthetic three-domain smoke test gave the expected gradient: some
value on SQL, none on migration plans once ground truth was fixed, and
none on prose. The conclusion is that a structural oracle is a useful
**cross-check, not a replacement**. It catches some errors the LLM
verifier misses and has blind spots of its own. Every sample here is
small, and several headline metrics turned out to be fixed by
properties of the corpus rather than measured (see
[Lessons](#lessons--methodology-notes)).

## Background

- **Bypass vs. rediscovery.** An auditor is shown a security patch and
  reports a finding. The finding is a *bypass* if the vulnerable code
  path it cites is outside what the patch covers. It is a
  *rediscovery* if the patch already addresses that path.
- **The mirror.** An LLM verifier that classifies each finding as
  bypass or rediscovery by reasoning over the patch diff and the
  finding.
- **Structural oracle.** A deterministic check computed from the same
  artifacts (diff, query, plan, text) with no model calls. The
  classifier's oracle asks one question: do the finding's cited
  file:line locations fall inside the patch's hunks?
- **Why independence matters.** A second checker only adds value where
  its errors don't line up with the first one's. If the oracle fails on
  the same cases as the mirror (*correlated failure*), it adds cost and
  no coverage. The quantity of interest is *detection lift*: cases
  where the mirror is wrong and the oracle is right.

## Components

The two components are independent experiments on the same question.
Neither depends on the other or on the Loci codebase.

### `classifier/`: bypass-vs-rediscovery oracle (TypeScript, no runtime dependencies)

- **`structural-oracle.ts`** is the oracle. `parseHunks` reads a
  unified diff. `classifyCitation` labels each citation `in_hunk`,
  `in_patched_file`, or `not_in_patch`:
  - `in_hunk` means the cited line falls within a hunk's **full
    header range** (`@@ -a,b +c,d @@`). That range includes the
    unified-diff context lines, not only added or removed lines.
  - The line is checked against **both** the old-file range and the
    new-file range, so citations work whether the audited commit was
    before or after the patch.
  - Files match exactly, by path suffix, or by basename as a fallback.

  Citations with role `sanitizer-bypass` are left out of the vote
  because they point at the patched guard on purpose. If *every*
  citation has that role, the oracle **falls back to all citations**
  instead of returning inconclusive. Verdict: any `in_hunk` →
  `likely_rediscovery`. Otherwise, any `in_patched_file` →
  `inconclusive` (the blind spot). Otherwise → `likely_bypass`.
- **`run-oracle-evaluation.ts`** loads every finding that has a mirror
  verdict (`bypass_variant_type`) from patch-diff runs. It fetches each
  patch with `git show --unified=5`, runs the oracle, and prints a
  per-finding table plus a full mirror × oracle matrix (right, wrong,
  or abstain) against a hardcoded `HUMAN_GT` table. It reports failure
  correlation only when *both* checkers have at least one error.
  Otherwise it says correlation is undefined on the corpus.
- **`structural-oracle.test.ts`** has unit tests for the parser and
  verdict logic, plus integration tests that replay the 3 known mirror
  errors and 3 confirmed bypasses from recorded runs.

```sh
cd classifier
npm install
npx vitest run                     # unit tests always run; integration tests need ORACLE_FINDINGS_DIR
npx tsx run-oracle-evaluation.ts --findings-dir <path> [--repo-root <path>]
```

> **Findings data is not included.** The integration tests and the
> evaluation script need a findings directory (one subdirectory per
> run, each with `audit.config.json` + `findings.jsonl`) and clones of
> the target repos so `git show` can fetch each patch commit. That data
> is the Loci auditor's run output (1,800+ directories), not research
> artifacts, so it was left out of this repo. The evaluation script
> takes it as `--findings-dir`, with an optional `--repo-root` to
> relocate the repo clones. The test suite reads `ORACLE_FINDINGS_DIR`
> and **skips the integration tests with a warning** when it is unset
> or missing. The unit tests (`parseHunks`, `runStructuralOracle`)
> don't touch the filesystem and always run.

### `smoke-test/`: three synthetic domains (Python)

Each task generates LLM outputs for seeded scenarios, some clean and
some with an injected error. It then scores every sample with a
non-LLM oracle (`oracle.py`) and an LLM mirror (`mirror.py`) and fills
in a 2×2 table of mirror vs. oracle correctness (`shared/evaluation.py`).

| Task | Domain | Expected answer | Oracle |
|---|---|---|---|
| 1 | Text-to-SQL | Obvious yes | Execute the query on a seeded SQLite DB and compare against the golden result |
| 2 | Migration plans | Deceptive no | A: completeness, B: step ordering, C: rollback coverage, D: run the plan's SQL on a fresh copy of the DB |
| 3 | Short prose | True no | Readability, structure, factual substring, and two-generation consistency checks |

Task 2 has two modes: Run A (prose plans) and Run B (structured JSON
plans). It can score Run A two ways:

- **`--gt oracle`** (default, legacy). Clean plans are labeled with the
  oracle's own verdict, and all four checks run.
- **`--gt human`**. Every Run A sample is labeled from
  `task2_migration/human_labels.json`, and the oracle runs Checks A/B/C
  only. Results go to `results/task2_run_a_human.json`.

```sh
cd smoke-test
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python run_all.py [--tasks 123] [--run ab] [--regen] [--gt oracle|human]
python -m task2_migration.run --run a --gt human    # Task 2 Run A against human labels
```

Results, generation caches, and the SQLite DB are written to
`results/`, which is gitignored.

**Offline re-scoring (no API key needed).** `data/original_run/` holds
the original Task 2 run: plans, mirror verdicts, and oracle verdicts.

```sh
cd smoke-test
python -m task2_migration.offline verify                       # seeded samples identical to their clean plan
python -m task2_migration.offline score --run a --gt human     # human labels, Checks A/B/C
python -m task2_migration.offline replay --check-d legacy      # Run A→B on one shared DB, original Check D
python -m task2_migration.offline replay --check-d fresh       # same, fixed Check D
python -m unittest discover -s tests                           # Check D and offline-mode tests
```

## Results

Numbers marked † are **from experiment notes, not reproducible from
this repo alone**: the classifier's findings data is excluded, and
Tasks 1 and 3 have no saved snapshot.
Everything else was checked against the code or the test fixtures.

### Classifier

| | |
|---|---|
| Corpus | 17 findings with mirror verdicts: 15 human-labeled, 2 unlabeled (`unknown`) in `HUMAN_GT`. 2 more were excluded for contamination. |
| Confirmed mirror errors | 3, all rated "bypass" that were really rediscoveries (named in the integration tests) |
| Oracle catches | 3 of 3, with no LLM calls (asserted by the integration tests; needs `ORACLE_FINDINGS_DIR`) |
| Oracle errors | 1 false rediscovery (finding-5)† |
| Oracle inconclusive | ~41% of findings† (cite the patched file, but outside the patched hunks) |
| Correlated failures (both wrong) | 0 on a very small n. Complementary, not evidence of independence (see below). |

- **The mirror was one-sided.** Before the corpus was enriched, it
  rated 17/17 patch-diff findings "bypass".†
- **How the mirror failed.** It reasoned soundly from false premises
  about what the patch covered, even with the patch in its context.†
- **The first "0 correlated failures" figure was degenerate.** With
  finding-5 of run `oq8-v1-002` labeled `unknown`, the oracle made no
  errors on the labeled set, so failure correlation had nothing to
  measure. `HUMAN_GT` now labels finding-5 `bypass`. On that finding
  the oracle gives a false rediscovery and the mirror is right.† No
  case has both checkers wrong. That's complementary failures on a
  very small n, not a measured independence. Run against the findings
  data, the evaluation script now reports it that way. Before the fix
  it printed "decorrelation confirmed."
- **The independence was mostly architectural.** The mirror never
  reads citation metadata, because citations are its output. The oracle
  reads only citations and the diff. The two checkers have different
  inputs by construction, so the independence was found, not
  engineered.† (The mirror's code is not in this repo.)
- **Adversarial testing found two bugs.** Both are **still present**
  and reproduce against the current code:
  1. **Context-line expansion.** `--unified=5` hunk ranges include
     unmodified context lines, which the oracle counts as patched. This
     caused the finding-5 false rediscovery.†
  2. **Fallback clause.** If every citation is labeled
     `sanitizer-bypass`, the fallback brings the patched-guard citation
     back into the vote and yields a false rediscovery.

  Citation-displacement attacks mostly couldn't be constructed,
  because guard-insertion patches put the function signature inside
  the hunk.†

### Smoke test

**Task 1: SQL (obvious yes).** 42 samples (30 questions + 12
hand-written wrong queries).

| Result | Notes |
|---|---|
| Real detection lift: 1 case† | The mirror assumed `LIKE` is case-sensitive. SQLite's `LIKE` is case-insensitive for ASCII. |
| Spurious lift: 1 case† | Artifact of over-strict output matching |
| Oracle accuracy | Partly tautological. For clean samples, ground truth *is* the oracle's verdict (`task1_sql/run.py`). |

**Task 2: migration plans (deceptive no).** The original run's plans
and mirror verdicts are frozen in `smoke-test/data/original_run/`. Every
number in this block is re-derived from that snapshot offline, with no
API calls (`python -m task2_migration.offline …`).

| Run | Samples | Composition |
|---|---|---|
| A (prose) | 21 | 12 clean + 9 seeded. 3 of the 12 seeded errors only apply to structured plans. |
| B (structured) | 21 | 11 clean + 10 seeded. The generator failed on scenario `s07`, so `B-s07` and its seeded errors `me04` and `me06` were dropped. The code produces 24 only when all 12 plans generate. |

| Run A scoring | Mirror | Oracle | Status |
|---|---|---|---|
| First run: oracle-derived ground truth, Checks A–D | 47.6% | 95.2% | **Artifact** (see below) |
| Independent human labels, Checks A/B/C only | 95.2% | 85.7% | Corrected result |

- **The corrected result** (`offline score --run a --gt human`):
  - **Which seeded errors are real.** `offline verify` shows `A-me08`
    and `A-me09` are byte-identical to their clean plans: the
    injection did nothing. That leaves 7 real errors.
  - **What the oracle caught: 5 of 7** (`me01`, `me02`, `me06`, `me07`,
    `me10`). `me10` is a wrong-reference error. Check A caught it only
    because the correct column name never appears in the plan.
  - **What it missed:** `me11` (wrong type: `CAST(hours AS REAL)`) and
    `me05`, a missing rollback. Check C splits the plan at the first
    occurrence of the word "rollback", which falls mid-plan. It then
    counts forward-step SQL as inverse operations, even though the plan
    ends with "(Rollback procedure: not provided.)".
  - **Detection lift on real errors: zero.** The mirror caught all 7,
    and every error the oracle caught, the mirror also caught.
  - **The full 2×2 has one lift case:** `A-s07`, a valid plan the mirror
    falsely flagged and the oracle passed. The oracle's own errors are
    the two misses plus one false alarm, `A-s11`: Check C doesn't
    recognize an `INSERT … FROM backup` rollback. No sample has both
    checkers wrong.
- **Why the first run was an artifact:**
  - **Ground truth came from the oracle.** Clean-sample ground truth
    was set to the oracle's own verdict, so any spurious oracle failure
    became a ground-truth label.
  - **Check D was itself unreliable.** Even on a fresh database it
    rejects 10 of 12 clean Run A plans, on errors such as foreign-key
    failures, name collisions, and nested `BEGIN`.
  - **Check D leaked DDL between samples (reproduced on the original
    plans).** Its "always rolled back" transaction doesn't undo DDL,
    because Python's `sqlite3` autocommits it. Replaying Run A then
    Run B on one shared database with the original Check D reproduces
    the original run's oracle verdicts on 42 of 42 samples. Three of
    those verdicts differ when each sample gets a fresh database:

    | Flipped sample | Leaked from | Error | Effect |
    |---|---|---|---|
    | `A-me05` | `A-s01` | `email` column already added | Accidental catch of a seeded error |
    | `B-s08` | `A-s09`, `A-me02`, or `A-me08` | `assignments` table already changed | Valid clean plan's ground-truth label flipped to INVALID |
    | `B-me11` | the same, or `B-s08` | `assignments_new` already exists | Accidental catch of a seeded error |

    With the fixed Check D, 0 of 42 flip. Only `B-s08` is a clean plan,
    so it is the only place where the leak changed a ground-truth label.
  - **Check D rejected multi-statement SQL.** The original Check D
    passed each structured `sql` field to `execute()` unsplit. That
    rejected 6 Run B samples with "You can only execute one statement
    at a time" (`s01`, `s02`, `s03`, `s06`, `s12`, `me05`). For
    `B-s01`, this was the only failure recorded. Fixing the split
    changes none of the 6 verdicts, because the fixed Check D still
    fails all 6 on other errors.
  - **The same scenarios got opposite ground truth in the two formats.**
    Scenarios `s01` and `s10` were rendered once as prose (Run A) and
    once as structured JSON (Run B). Each format was scored by a
    different oracle (the prose and structured variants of Checks
    A–D). In the snapshot, `A-s01` and `A-s10` have ground truth VALID,
    while `B-s01` and `B-s10` have ground truth INVALID. Every failure
    behind the INVALID labels is an oracle artifact:
    - **`B-s01`:** only Check D failed, and only with the
      multi-statement rejection.
    - **`B-s10`, Check A:** the structured Check A reads the plan's
      self-declared `affected_tables` field, not its SQL. The plan
      lists `salary_history` but not `employees`, which it only reads
      from.
    - **`B-s10`, Check D:** "no such table: salary_history" happens
      because the validation query runs *after* the rollback steps
      that drop the table. "no such column: hire_date" was leaked from
      `A-s04`'s rename.

    These are different plans, not one plan flipping. The point is that
    the labels tracked the oracle, not the plan. The mirror rated all
    four plans valid.

**Task 3: prose (true no).** 144 samples (25 clean paragraphs + 119
degraded variants).

| Result | Notes |
|---|---|
| Best candidate oracle: 12 of 119 seeded errors caught† | No candidate came close to useful |
| Correlated failure with the mirror: ~71%† | The oracle mostly missed the same samples the mirror missed |
| Ground truth | "Was this text perturbed?", a proxy for quality. In the code, clean samples are relabeled bad when the mirror scores them below 3. |

## Limitations

- **Small samples.** 15 labeled findings with 3 mirror errors and 1
  oracle error; 21–144
  samples per smoke-test task. No result has a confidence interval
  worth reporting.
- **One domain for the classifier.** All findings are patch-bypass
  findings from one auditor on a few patches.
- **The inconclusive blind spot.** About 41% of findings† cite the
  patched file outside the patched hunks, and the oracle abstains on
  them. Telling whether those lines are guarded would take line-level
  guard detection, which is not implemented.
- **Unfixed classifier issues:**
  - Context-line expansion (`--unified=5`, full hunk ranges).
  - The all-`sanitizer-bypass` fallback.
  - Basename-only file matching, which can confuse two files with the
    same name.
- **Unfixed smoke-test issues:**
  - By default (`--gt oracle`), Task 2 still sets clean-sample ground
    truth from the oracle and includes Check D. Use `--gt human` for the
    corrected scoring. Human labels exist for Run A only; Run B still
    uses oracle-derived ground truth.
  - Task 1 sets clean-sample ground truth from the oracle, and Task 3
    sets it from the mirror.
- **Fixed:**
  - Finding-5 is labeled `bypass` in `HUMAN_GT`.
  - The evaluation summary's "oracle abstain" row now counts
    abstentions; oracle errors get their own row. The script no longer
    claims decorrelation when either checker has zero errors.
  - Check D runs each sample on a fresh temp copy of `company.db`, and
    Task 2 rebuilds `company.db` from the seed at the start of every
    run. Schema changes no longer leak between samples or runs.
  - Check D splits multi-statement SQL (using
    `sqlite3.complete_statement`) instead of rejecting it.
    `check_d_sql_execution(..., legacy=True)` keeps the original
    behavior for replays.
  - Independent human labels for Task 2 Run A are stored in
    `task2_migration/human_labels.json`.
- **Tasks 1 and 3 must be regenerated.** `results/` is gitignored and
  no snapshot of those runs is included. A rerun makes new LLM outputs
  and won't match the † numbers exactly. Task 2's original run is
  frozen in `smoke-test/data/original_run/` and re-scores offline.
- **Check D is still not a usable check.** Even fixed, it rejects most
  valid plans (10 of 12 clean Run A plans), so the corrected Task 2
  scoring excludes it. One known cause is unfixed: for structured plans,
  `evaluate_structured` runs `validation_sql` after the rollback steps,
  so the validation query checks a database that has already been
  rolled back.

## Lessons / methodology notes

- **Ground truth must be independent of the oracle under test.** Task
  2's 95.2% came from defining correctness as "what the oracle says."
  The same scenarios got opposite ground truth depending on which
  oracle labeled them.
- **Corpus conditions can fix headline metrics:**
  - An oracle that never errs on the labeled set leaves failure
    correlation undefined, so "0 correlated failures" means nothing.
  - A mirror near its ceiling leaves detection lift no room to be
    positive (Task 2 after re-labeling).
- **Structural checks drift toward lexical ones.** Task 2's prose
  rollback check keys on words like "rollback" and "drop table", not
  on whether the operations are actually inverses. It passed `me05`, a
  plan ending in "(Rollback procedure: not provided.)".
- **Verify seeded-error injection.** Some injections silently fail and
  produce a correct sample labeled as an error.

## Status and next steps

Both experiments are done. The evaluation-script, labeling, and
Check D issues have been fixed. The two classifier bugs and the Task
1/Task 3 ground-truth dependencies are documented but not fixed. The
next planned experiment
moves from synthetic tasks to real AI-agent pull requests. It will
measure how much of those PRs is already covered by existing non-LLM
checks, with a kill threshold preregistered before any data is
collected.
