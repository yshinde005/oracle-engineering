/**
 * Oracle evaluation script.
 *
 * Loads all findings with `bypass_variant_type` from patch-diff runs,
 * runs the structural oracle on each, and outputs:
 *   1. Per-finding comparison table (mirror vs oracle vs human GT)
 *   2. Detection lift and failure correlation counts
 *   3. Oracle blind spot characterisation
 *
 * Usage:
 *   tsx run-oracle-evaluation.ts --findings-dir <path> [--repo-root <path>]
 *
 *   --findings-dir  Directory containing one subdirectory per run, each
 *                    with audit.config.json + findings.jsonl (required).
 *   --repo-root     If set, resolve each run's target repo as
 *                    <repo-root>/<basename of config.target.repo> instead
 *                    of the absolute path recorded in audit.config.json.
 *                    Use this when the cloned target repos live somewhere
 *                    other than where the findings were originally recorded.
 *
 * No LLM calls. Pure structural analysis.
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, basename } from 'node:path';
import { execFileSync } from 'node:child_process';
import { runStructuralOracle } from './structural-oracle.js';

// ---------------------------------------------------------------------------
// CLI args
// ---------------------------------------------------------------------------

function parseArgs(argv: string[]): { findingsDir: string; repoRoot: string | null } {
  let findingsDir: string | null = null;
  let repoRoot: string | null = null;

  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--findings-dir') findingsDir = argv[++i];
    else if (argv[i] === '--repo-root') repoRoot = argv[++i];
  }

  if (!findingsDir) {
    console.error(
      'Usage: tsx run-oracle-evaluation.ts --findings-dir <path> [--repo-root <path>]',
    );
    process.exit(1);
  }

  return { findingsDir, repoRoot };
}

// ---------------------------------------------------------------------------
// Human ground truth — based on source inspection (not LLM output)
// ---------------------------------------------------------------------------

// GT tiers:
//   rediscovery: the patch addresses the cited code path
//   bypass:      the patch does not address the cited code path
//   excluded:    T4 contamination artifact, not usable for measurement
//   unknown:     not enough info to determine without further source inspection

const HUMAN_GT: Record<string, 'rediscovery' | 'bypass' | 'excluded' | 'unknown'> = {
  // Nitro patch-diff: LLM claimed else-if guard is unreachable in strpBase path.
  // ufo's withoutBase already normalises //evil.com→/evil.com in that path;
  // the guard correctly protects the strpBase='' case. Patch works → rediscovery.
  'run-2026-05-28-nitro-patch-diff-001-finding-1': 'rediscovery',
  'run-2026-05-28-nitro-patch-diff-001-finding-2': 'rediscovery',

  // OQ8 v1-002: T4 contaminated (promises.js:1 citation from truth.json leakage).
  'run-2026-05-28-nodejs-oq8-v1-002-finding-3': 'excluded',
  'run-2026-05-28-nodejs-oq8-v1-002-finding-4': 'excluded',

  // OQ8 v1-002: specific lib/fs.js lines in fchmod/fchown area.
  // These likely cite the exact functions the patch addresses (fchmod callback/sync).
  // Human judgment: unknown without detailed line-by-line comparison.
  'run-2026-05-28-nodejs-oq8-v1-002-finding-1': 'unknown',
  'run-2026-05-28-nodejs-oq8-v1-002-finding-2': 'unknown',
  'run-2026-05-28-nodejs-oq8-v1-002-finding-5': 'unknown',

  // OQ8 v1-003: lib/fs.js lines in ftruncate and lchown area — distinct functions
  // from what the oq8 patch modified (fchmod/fchown). Genuine bypasses.
  'run-2026-05-28-nodejs-oq8-v1-003-finding-1': 'bypass',
  'run-2026-05-28-nodejs-oq8-v1-003-finding-2': 'bypass',

  // OQ8 v2-001: FileHandle.chmod/chown in promises.js — not in oq8 patch. Bypass.
  'run-2026-05-28-nodejs-oq8-v2-001-finding-1': 'bypass',
  'run-2026-05-28-nodejs-oq8-v2-001-finding-2': 'bypass',
  // ftruncate in lib/fs.js — different function from patched fchmod/fchown. Bypass.
  'run-2026-05-28-nodejs-oq8-v2-001-finding-3': 'bypass',
  // Chain finding with bypass_variant_type set. Same reasoning. Bypass.
  'run-2026-05-28-nodejs-oq8-v2-001-finding-4': 'bypass',

  // B-RUN: all findings in promises.js or in lib/fs.js ftruncate area (not in
  // b-run patch which targets fdatasync/fsync/futimes in lib/fs.js callback API).
  'run-2026-05-29-nodejs-b-run-001-finding-1': 'bypass', // futimes in promises.js
  'run-2026-05-29-nodejs-b-run-001-finding-2': 'bypass', // ftruncate in lib/fs.js (not patched)
  'run-2026-05-29-nodejs-b-run-001-finding-3': 'bypass', // ftruncate in promises.js
  'run-2026-05-29-nodejs-b-run-001-finding-4': 'bypass', // fdatasync/fsync in promises.js

  // jwt-go patch-diff: finding-1 is the exact CVE-2020-26160 ([]interface{} case).
  // finding-2 claims patch misses []string — patch explicitly adds case []string:. Rediscovery.
  'run-2026-06-02-jwt-go-patch-diff-002-finding-1': 'rediscovery',
  'run-2026-06-02-jwt-go-patch-diff-002-finding-2': 'rediscovery',
};

// ---------------------------------------------------------------------------
// Loading utilities
// ---------------------------------------------------------------------------

interface RunConfig {
  target: { repo: string };
  patchDiff?: { patch_commit: string; cve_id?: string };
}

interface StoredFinding {
  id: string;
  bypass_variant_type?: string;
  citations: Array<{ file: string; line: number; role?: string }>;
  phase: string;
  attack_class: string;
}

function loadRunConfig(findingsDir: string, runDir: string): RunConfig | null {
  const p = join(findingsDir, runDir, 'audit.config.json');
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, 'utf-8')) as RunConfig;
}

function loadFindings(findingsDir: string, runDir: string): StoredFinding[] {
  const p = join(findingsDir, runDir, 'findings.jsonl');
  if (!existsSync(p)) return [];
  return readFileSync(p, 'utf-8')
    .trim()
    .split('\n')
    .filter(Boolean)
    .map((l) => JSON.parse(l) as StoredFinding);
}

function fetchPatchDiff(patchCommit: string, repoPath: string): { files: string[]; diffText: string } {
  const files = execFileSync('git', ['show', patchCommit, '--name-only', '--format='], {
    cwd: repoPath, encoding: 'utf-8',
  }).split('\n').map((l) => l.trim()).filter(Boolean);

  const diffText = execFileSync('git', ['show', patchCommit, '--unified=5', '--format='], {
    cwd: repoPath, encoding: 'utf-8',
  });

  return { files, diffText };
}

function resolveRepoPath(configRepo: string, repoRoot: string | null): string {
  return repoRoot ? join(repoRoot, basename(configRepo)) : configRepo;
}

// ---------------------------------------------------------------------------
// Main evaluation
// ---------------------------------------------------------------------------

interface EvalRow {
  findingId: string;
  runId: string;
  attackClass: string;
  phase: string;
  mirror: string;     // bypass_variant_type from LLM verifier
  oracle: string;     // oracle structural classification
  humanGt: string;   // human ground truth
  mirrorCorrect: boolean | null;  // null = unknown GT
  oracleCorrect: boolean | null;
  agreement: boolean | null;      // mirror and oracle agree?
  oracleReasoning: string;
}

function main() {
  const { findingsDir, repoRoot } = parseArgs(process.argv.slice(2));

  if (!existsSync(findingsDir)) {
    console.error(`Findings directory not found: ${findingsDir}`);
    process.exit(1);
  }

  const runDirs = readdirSync(findingsDir).sort();
  const rows: EvalRow[] = [];

  for (const runDir of runDirs) {
    const config = loadRunConfig(findingsDir, runDir);
    if (!config?.patchDiff) continue;

    const findings = loadFindings(findingsDir, runDir);
    const withBypassType = findings.filter((f) => f.bypass_variant_type !== undefined);
    if (withBypassType.length === 0) continue;

    let patchData: { files: string[]; diffText: string };
    try {
      const repoPath = resolveRepoPath(config.target.repo, repoRoot);
      patchData = fetchPatchDiff(config.patchDiff.patch_commit, repoPath);
    } catch (e) {
      console.error(`  [SKIP] ${runDir}: failed to fetch patch diff — ${e instanceof Error ? e.message : String(e)}`);
      continue;
    }

    for (const finding of withBypassType) {
      const gt = HUMAN_GT[finding.id] ?? 'unknown';
      if (gt === 'excluded') continue; // T4 contamination

      const verdict = runStructuralOracle(finding, patchData);
      const mirror = finding.bypass_variant_type!;
      const oracle = verdict.structuralClassification;

      const mirrorCorrect = gt === 'unknown' ? null
        : (mirror === 'bypass' && gt === 'bypass') || (mirror === 'rediscovery' && gt === 'rediscovery');
      const oracleCorrect = gt === 'unknown' ? null
        : oracle === 'inconclusive' ? null  // oracle abstains — not right or wrong
        : (oracle === 'likely_bypass' && gt === 'bypass') ||
          (oracle === 'likely_rediscovery' && gt === 'rediscovery');
      const agreement =
        (mirror === 'bypass' && oracle === 'likely_bypass') ||
        (mirror === 'rediscovery' && oracle === 'likely_rediscovery') ||
        (mirror === 'unclear' && oracle === 'inconclusive')
          ? true
          : oracle === 'inconclusive' ? null  // oracle abstains, no agreement possible
          : false;

      rows.push({
        findingId: finding.id,
        runId: runDir,
        attackClass: finding.attack_class.slice(0, 35),
        phase: finding.phase,
        mirror,
        oracle,
        humanGt: gt,
        mirrorCorrect,
        oracleCorrect,
        agreement,
        oracleReasoning: verdict.reasoning,
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Output: comparison table
  // ---------------------------------------------------------------------------
  console.log('\n══════════════════════════════════════════════════════════════════════════════');
  console.log('  STRUCTURAL ORACLE EVALUATION');
  console.log('══════════════════════════════════════════════════════════════════════════════\n');

  console.log('─── Per-finding comparison ────────────────────────────────────────────────\n');
  const colW = { id: 52, mirror: 12, oracle: 20, gt: 12, mirCorr: 10, oraCorr: 10, agree: 9 };
  const header = [
    'Finding ID'.padEnd(colW.id),
    'Mirror'.padEnd(colW.mirror),
    'Oracle'.padEnd(colW.oracle),
    'Human GT'.padEnd(colW.gt),
    'Mirror✓'.padEnd(colW.mirCorr),
    'Oracle✓'.padEnd(colW.oraCorr),
    'Agree'.padEnd(colW.agree),
  ].join(' | ');
  console.log(header);
  console.log('─'.repeat(header.length));

  for (const r of rows) {
    const shortId = r.findingId.replace(/^run-\d{4}-\d{2}-\d{2}-/, '').slice(0, colW.id - 1);
    const oracleShort =
      r.oracle === 'likely_rediscovery' ? 'likely_rediscovery'
      : r.oracle === 'likely_bypass' ? 'likely_bypass'
      : 'inconclusive';
    const fmt = (v: boolean | null) => v === null ? '—' : v ? '✓' : '✗';
    const agreeStr = r.agreement === null ? '— (abstain)' : r.agreement ? 'yes' : 'NO ◄';
    console.log([
      shortId.padEnd(colW.id),
      r.mirror.padEnd(colW.mirror),
      oracleShort.padEnd(colW.oracle),
      r.humanGt.padEnd(colW.gt),
      fmt(r.mirrorCorrect).padEnd(colW.mirCorr),
      fmt(r.oracleCorrect).padEnd(colW.oraCorr),
      agreeStr.padEnd(colW.agree),
    ].join(' | '));
  }

  // ---------------------------------------------------------------------------
  // Output: aggregate metrics
  // ---------------------------------------------------------------------------
  const definedGt = rows.filter((r) => r.humanGt !== 'unknown');
  const detectionLift = definedGt.filter((r) => r.mirrorCorrect === false && r.oracleCorrect === true);
  const bothCorrect = definedGt.filter((r) => r.mirrorCorrect === true && r.oracleCorrect === true);
  const mirrorOnlyCorrect = definedGt.filter((r) => r.mirrorCorrect === true && r.oracleCorrect === false);
  const bothWrong = definedGt.filter((r) => r.mirrorCorrect === false && r.oracleCorrect === false);
  const oracleInconclusive = rows.filter((r) => r.oracle === 'inconclusive');
  const unknownGt = rows.filter((r) => r.humanGt === 'unknown');

  console.log('\n─── Summary metrics ───────────────────────────────────────────────────────\n');
  console.log(`Total findings evaluated (excluding T4):    ${rows.length}`);
  console.log(`  With defined human GT:                    ${definedGt.length}`);
  console.log(`  With unknown human GT:                    ${unknownGt.length}`);
  console.log(`  Oracle inconclusive (blind spot):         ${oracleInconclusive.length}`);
  console.log('');
  console.log('Failure correlation matrix (defined GT only):');
  console.log(`  Both correct:             ${bothCorrect.length}`);
  console.log(`  Mirror ✓, oracle abstain: ${mirrorOnlyCorrect.length}`);
  console.log(`  Mirror ✗, oracle ✓ (DETECTION LIFT): ${detectionLift.length}`);
  console.log(`  Both wrong (CORR. FAIL):  ${bothWrong.length}`);

  if (detectionLift.length > 0) {
    console.log('\n─── Detection lift cases ──────────────────────────────────────────────────\n');
    for (const r of detectionLift) {
      console.log(`  ${r.findingId}`);
      console.log(`    Mirror: ${r.mirror}  Oracle: ${r.oracle}  GT: ${r.humanGt}`);
      console.log(`    ${r.oracleReasoning.slice(0, 200)}`);
      console.log('');
    }
  }

  if (oracleInconclusive.length > 0) {
    console.log('─── Oracle blind spot (inconclusive findings) ─────────────────────────────\n');
    for (const r of oracleInconclusive) {
      const primary = r.oracleReasoning.split('.')[0];
      console.log(`  ${r.findingId.replace(/^run-\d{4}-\d{2}-\d{2}-/, '').slice(0, 55)}`);
      console.log(`    ${primary}`);
    }
    console.log(`\n  Pattern: ${oracleInconclusive.length} finding(s) cite code in a patched file but outside`);
    console.log('  the exact modified hunks (e.g., lib/fs.js has patched fchmod/fchown,');
    console.log('  but the finding cites ftruncate or lchown at different line offsets).');
    console.log('  The oracle cannot determine whether these locations are guarded without');
    console.log('  running line-level guard detection (Check 3, not implemented).');
  }

  // ---------------------------------------------------------------------------
  // Outcome classification
  // ---------------------------------------------------------------------------
  console.log('\n─── Outcome classification ────────────────────────────────────────────────\n');
  if (detectionLift.length >= 1 && bothWrong.length === 0 && mirrorOnlyCorrect.length === 0) {
    console.log('  Outcome A: oracle catches error cases, no false flags, zero correlated failures.');
    console.log('  The structural oracle is genuinely independent of the mirror on this corpus.');
  } else if (detectionLift.length >= 1 && bothWrong.length === 0) {
    console.log('  Outcome C: oracle catches some error cases, oracle abstains on others (blind spot).');
    console.log('  Partial detection with zero correlated failures — decorrelation confirmed.');
  } else if (detectionLift.length === 0) {
    console.log('  Outcome B or D: oracle adds no lift. Either same errors as mirror (B) or all');
    console.log('  inconclusive (D). Review the blind spot findings for oracle redesign.');
  }

  console.log('\n══════════════════════════════════════════════════════════════════════════════\n');
}

main();
