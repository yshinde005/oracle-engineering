import { describe, it, expect } from 'vitest';
import { execFileSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import {
  parseHunks,
  runStructuralOracle,
  type OracleInput,
  type PatchInput,
} from './structural-oracle.js';

// ---------------------------------------------------------------------------
// Unit: parseHunks
// ---------------------------------------------------------------------------

describe('parseHunks', () => {
  it('parses a simple single-file, single-hunk diff', () => {
    const diff = [
      'diff --git a/foo.ts b/foo.ts',
      'index abc..def 100644',
      '--- a/foo.ts',
      '+++ b/foo.ts',
      '@@ -10,5 +10,7 @@',
      ' context',
      '-removed',
      '+added line 1',
      '+added line 2',
      ' context',
      ' context',
    ].join('\n');

    const hunks = parseHunks(diff);
    expect(hunks).toHaveLength(1);
    expect(hunks[0].file).toBe('foo.ts');
    expect(hunks[0].oldStart).toBe(10);
    expect(hunks[0].oldEnd).toBe(14); // 10 + 5 - 1
    expect(hunks[0].addedLines).toEqual(['added line 1', 'added line 2']);
  });

  it('parses multiple hunks in the same file', () => {
    const diff = [
      'diff --git a/route-rules.ts b/route-rules.ts',
      '--- a/route-rules.ts',
      '+++ b/route-rules.ts',
      '@@ -33,6 +33,8 @@',
      ' ctx',
      '+} else if (x) {',
      '+  y = z;',
      ' ctx',
      '@@ -56,6 +58,8 @@',
      ' ctx',
      '+} else if (a) {',
      '+  b = c;',
      ' ctx',
    ].join('\n');

    const hunks = parseHunks(diff);
    expect(hunks).toHaveLength(2);
    expect(hunks[0].file).toBe('route-rules.ts');
    expect(hunks[0].oldStart).toBe(33);
    expect(hunks[0].oldEnd).toBe(38);
    expect(hunks[1].oldStart).toBe(56);
    expect(hunks[1].oldEnd).toBe(61);
  });

  it('parses multi-file diffs and tracks current file per hunk', () => {
    const diff = [
      'diff --git a/a.go b/a.go',
      '--- a/a.go',
      '+++ b/a.go',
      '@@ -5,3 +5,4 @@',
      '+new line',
      ' ctx',
      'diff --git a/b.go b/b.go',
      '--- a/b.go',
      '+++ b/b.go',
      '@@ -20,2 +21,3 @@',
      '+another',
      ' ctx',
    ].join('\n');

    const hunks = parseHunks(diff);
    expect(hunks).toHaveLength(2);
    expect(hunks[0].file).toBe('a.go');
    expect(hunks[1].file).toBe('b.go');
  });

  it('handles omitted count (defaults to 1) in hunk header', () => {
    const diff = [
      'diff --git a/x.ts b/x.ts',
      '@@ -7 +7,2 @@',
      '+inserted',
      ' ctx',
    ].join('\n');

    const hunks = parseHunks(diff);
    expect(hunks).toHaveLength(1);
    expect(hunks[0].oldStart).toBe(7);
    expect(hunks[0].oldEnd).toBe(7); // count=1
  });

  it('returns empty array for diff with no hunks', () => {
    expect(parseHunks('')).toHaveLength(0);
    expect(parseHunks('diff --git a/x b/x\n--- a/x\n+++ b/x')).toHaveLength(0);
  });

  it('parses new-file coordinates alongside old-file coordinates', () => {
    // Pure insertion: @@ -35,0 +36,2 @@ — oldStart=35,oldEnd=35, newStart=36,newEnd=37
    const diff = [
      'diff --git a/route-rules.ts b/route-rules.ts',
      '@@ -35,0 +36,2 @@',
      '+} else if (targetPath.startsWith("//")) {',
      '+  targetPath = targetPath.replace(/^\\/+/, "/");',
    ].join('\n');
    const hunks = parseHunks(diff);
    expect(hunks).toHaveLength(1);
    expect(hunks[0].oldStart).toBe(35);
    expect(hunks[0].oldEnd).toBe(35);   // oldCount=0 → oldEnd=35+max(-1,0)=35
    expect(hunks[0].newStart).toBe(36);
    expect(hunks[0].newEnd).toBe(37);   // newCount=2 → newEnd=36+1=37
  });

  it('parses new-file coordinates for a replacement hunk', () => {
    // @@ -93,2 +93,2 @@ — old lines 93-94 replaced by 2 new lines 93-94
    const diff = [
      'diff --git a/claims.go b/claims.go',
      '@@ -93,2 +93,2 @@',
      '-func verifyAud(aud string, cmp string, required bool) bool {',
      '-\tif aud == "" {',
      '+func verifyAud(aud []string, cmp string, required bool) bool {',
      '+\tif len(aud) == 0 {',
    ].join('\n');
    const hunks = parseHunks(diff);
    expect(hunks).toHaveLength(1);
    expect(hunks[0].oldStart).toBe(93);
    expect(hunks[0].oldEnd).toBe(94);
    expect(hunks[0].newStart).toBe(93);
    expect(hunks[0].newEnd).toBe(94);
  });
});

// ---------------------------------------------------------------------------
// Unit: runStructuralOracle — Check 1 (citation overlap)
// ---------------------------------------------------------------------------

describe('runStructuralOracle — citationOverlap', () => {
  const simplePatch: PatchInput = {
    files: ['map_claims.go', 'claims.go'],
    diffText: [
      'diff --git a/map_claims.go b/map_claims.go',
      '@@ -10,10 +10,24 @@',
      '-	aud, _ := m["aud"].(string)',
      '+	var aud []string',
      '+	switch v := m["aud"].(type) {',
      '+	case string:',
      '+		aud = append(aud, v)',
      '+	case []string:',
      '+		aud = v',
      '+	}',
      ' ctx',
    ].join('\n'),
  };

  it('returns overlap when citation falls within a patched hunk', () => {
    const finding: OracleInput = { id: 'f1', citations: [{ file: 'map_claims.go', line: 16 }] };
    const verdict = runStructuralOracle(finding, simplePatch);
    expect(verdict.citationOverlap).toBe('overlap');
    expect(verdict.guardPresence).toEqual(['guard_present']);
    expect(verdict.structuralClassification).toBe('likely_rediscovery');
  });

  it('returns disjoint when citation is in a file not touched by the patch', () => {
    const finding: OracleInput = {
      id: 'f2',
      citations: [{ file: 'promises.js', line: 1798 }],
    };
    const verdict = runStructuralOracle(finding, simplePatch);
    expect(verdict.citationOverlap).toBe('disjoint');
    expect(verdict.guardPresence).toEqual(['guard_absent']);
    expect(verdict.structuralClassification).toBe('likely_bypass');
  });

  it('returns partial when citation is in a patched file but outside all hunks', () => {
    const finding: OracleInput = {
      id: 'f3',
      citations: [{ file: 'map_claims.go', line: 5 }], // line 5 is before hunk (10-19)
    };
    const verdict = runStructuralOracle(finding, simplePatch);
    expect(verdict.citationOverlap).toBe('partial');
    expect(verdict.guardPresence).toEqual(['guard_absent']);
    expect(verdict.structuralClassification).toBe('inconclusive');
  });

  it('returns overlap when ANY citation is in a patched hunk (mixed citations)', () => {
    const finding: OracleInput = {
      id: 'f4',
      citations: [
        { file: 'other.go', line: 100 },  // not in patch
        { file: 'map_claims.go', line: 16 }, // in hunk
      ],
    };
    const verdict = runStructuralOracle(finding, simplePatch);
    expect(verdict.citationOverlap).toBe('overlap');
    expect(verdict.structuralClassification).toBe('likely_rediscovery');
  });

  it('matches files by basename when full paths differ', () => {
    // Finding cites bare 'map_claims.go', patch has full path
    const patchWithPath: PatchInput = {
      files: ['pkg/jwt/map_claims.go'],
      diffText: [
        'diff --git a/pkg/jwt/map_claims.go b/pkg/jwt/map_claims.go',
        '@@ -10,5 +10,8 @@',
        '+case []string:',
        ' ctx',
      ].join('\n'),
    };
    const finding: OracleInput = {
      id: 'f5',
      citations: [{ file: 'map_claims.go', line: 12 }],
    };
    const verdict = runStructuralOracle(finding, patchWithPath);
    expect(verdict.citationOverlap).toBe('overlap');
    expect(verdict.structuralClassification).toBe('likely_rediscovery');
  });

  it('sanitizer-bypass citations in patched hunks do NOT trigger overlap', () => {
    // The finding's attack path (sink) is in an unpatched file.
    // A sanitizer-bypass citation points to the patched area (showing contrast).
    // Oracle must exclude sanitizer-bypass from overlap check → likely_bypass.
    const finding: OracleInput = {
      id: 'oq8-like',
      citations: [
        { file: 'promises.js', line: 180, role: 'source' },  // not in patch
        { file: 'promises.js', line: 452, role: 'flow' },    // not in patch
        { file: 'promises.js', line: 1068, role: 'sink' },   // not in patch
        { file: 'map_claims.go', line: 15, role: 'sanitizer-bypass' }, // in patch hunk (10-19)
      ],
    };
    const verdict = runStructuralOracle(finding, simplePatch);
    // Primary citations all outside patch → disjoint → likely_bypass
    expect(verdict.citationOverlap).toBe('disjoint');
    expect(verdict.structuralClassification).toBe('likely_bypass');
  });

  it('returns inconclusive with empty citations', () => {
    const finding: OracleInput = { id: 'f6', citations: [] };
    const verdict = runStructuralOracle(finding, simplePatch);
    expect(verdict.structuralClassification).toBe('inconclusive');
  });

  it('matches citation in new-file range when old-file range misses (post-patch target)', () => {
    // Pure insertion: @@ -35,0 +36,2 @@ — old range [35,35], new range [36,37]
    // Citation at post-patch line 36: NOT in [35,35] but IN [36,37] → in_hunk.
    const pureInsertionPatch: PatchInput = {
      files: ['route-rules.ts'],
      diffText: [
        'diff --git a/route-rules.ts b/route-rules.ts',
        '@@ -35,0 +36,2 @@',
        '+} else if (targetPath.startsWith("//")) {',
        '+  targetPath = targetPath.replace(/^\\/+/, "/");',
      ].join('\n'),
    };
    const finding: OracleInput = {
      id: 'post-patch',
      citations: [{ file: 'route-rules.ts', line: 36 }],
    };
    const verdict = runStructuralOracle(finding, pureInsertionPatch);
    expect(verdict.citationOverlap).toBe('overlap');
    expect(verdict.structuralClassification).toBe('likely_rediscovery');
  });

  it('old-file range miss + new-file range miss → in_patched_file (partial)', () => {
    // Citation at line 5 is outside both old [35,35] and new [36,37] ranges
    // but route-rules.ts IS patched → in_patched_file → inconclusive.
    const pureInsertionPatch: PatchInput = {
      files: ['route-rules.ts'],
      diffText: [
        'diff --git a/route-rules.ts b/route-rules.ts',
        '@@ -35,0 +36,2 @@',
        '+inserted',
      ].join('\n'),
    };
    const finding: OracleInput = {
      id: 'outside-both',
      citations: [{ file: 'route-rules.ts', line: 5 }],
    };
    const verdict = runStructuralOracle(finding, pureInsertionPatch);
    expect(verdict.citationOverlap).toBe('partial');
    expect(verdict.structuralClassification).toBe('inconclusive');
  });
});

// ---------------------------------------------------------------------------
// Unit: verdict logic
// ---------------------------------------------------------------------------

describe('runStructuralOracle — verdict logic', () => {
  const nitroLikePatch: PatchInput = {
    files: ['src/runtime/internal/route-rules.ts'],
    diffText: [
      'diff --git a/src/runtime/internal/route-rules.ts b/src/runtime/internal/route-rules.ts',
      '@@ -33,6 +33,8 @@',
      ' ctx1',
      ' ctx2',
      '+} else if (targetPath.startsWith("//")) {',
      '+  targetPath = targetPath.replace(/^\\/+/, "/");',
      ' ctx3',
      '@@ -56,6 +58,8 @@',
      ' ctx4',
      '+} else if (targetPath.startsWith("//")) {',
      '+  targetPath = targetPath.replace(/^\\/+/, "/");',
      ' ctx5',
    ].join('\n'),
  };

  it('overlap + guard_present → likely_rediscovery', () => {
    // Simulates nitro-patch-diff-001-finding-1 (lines 35,36 in hunk @@ -33,6 @@)
    const finding: OracleInput = {
      id: 'nitro-1',
      citations: [
        { file: 'src/runtime/internal/route-rules.ts', line: 35 },
        { file: 'src/runtime/internal/route-rules.ts', line: 36 },
      ],
    };
    const verdict = runStructuralOracle(finding, nitroLikePatch);
    expect(verdict.structuralClassification).toBe('likely_rediscovery');
  });

  it('disjoint + guard_absent → likely_bypass', () => {
    // Simulates b-run finding citing only promises.js (not in b-run patch)
    const finding: OracleInput = {
      id: 'brun-1',
      citations: [
        { file: 'lib/internal/fs/promises.js', line: 1798 },
        { file: 'lib/internal/fs/promises.js', line: 249 },
      ],
    };
    const verdict = runStructuralOracle(finding, nitroLikePatch);
    expect(verdict.structuralClassification).toBe('likely_bypass');
  });

  it('partial (patched file, unpatched line) → inconclusive', () => {
    // Line 100 is outside both hunks (33-38 and 56-61)
    const finding: OracleInput = {
      id: 'partial-1',
      citations: [{ file: 'src/runtime/internal/route-rules.ts', line: 100 }],
    };
    const verdict = runStructuralOracle(finding, nitroLikePatch);
    expect(verdict.structuralClassification).toBe('inconclusive');
    expect(verdict.citationOverlap).toBe('partial');
  });
});

// ---------------------------------------------------------------------------
// Integration: 3 known error cases (oracle must produce likely_rediscovery)
// ---------------------------------------------------------------------------
//
// These tests replay real recorded findings through the oracle. They need a
// findings directory (one subdirectory per run, each with audit.config.json +
// findings.jsonl) and the cloned target repos each run's patch commit came
// from (for `git show`). Point ORACLE_FINDINGS_DIR at that directory to run
// them; they skip cleanly if it's unset or doesn't exist.

const FINDINGS_DIR = process.env.ORACLE_FINDINGS_DIR ?? '';
const HAS_FINDINGS_DIR = FINDINGS_DIR !== '' && existsSync(FINDINGS_DIR);

if (!HAS_FINDINGS_DIR) {
  console.warn(
    '[structural-oracle.test.ts] Skipping integration tests: set ORACLE_FINDINGS_DIR ' +
    'to a findings directory (with the cloned target repos available for `git show`) to run them.',
  );
}

function loadFindingsJsonl(runId: string): Array<{ id: string; citations: Array<{ file: string; line: number }>; bypass_variant_type?: string }> {
  const path = join(FINDINGS_DIR, runId, 'findings.jsonl');
  const lines = readFileSync(path, 'utf-8').trim().split('\n').filter(Boolean);
  return lines.map((l) => JSON.parse(l));
}

function getRepoPath(runId: string): string {
  const cfg = JSON.parse(readFileSync(join(FINDINGS_DIR, runId, 'audit.config.json'), 'utf-8'));
  return cfg.target.repo as string;
}

function getPatchCommit(runId: string): string {
  const cfg = JSON.parse(readFileSync(join(FINDINGS_DIR, runId, 'audit.config.json'), 'utf-8'));
  return cfg.patchDiff.patch_commit as string;
}

function fetchPatch(patchCommit: string, repoPath: string): PatchInput {
  const files = execFileSync('git', ['show', patchCommit, '--name-only', '--format='], {
    cwd: repoPath, encoding: 'utf-8',
  }).split('\n').map((l) => l.trim()).filter(Boolean);

  const diffText = execFileSync('git', ['show', patchCommit, '--unified=5', '--format='], {
    cwd: repoPath, encoding: 'utf-8',
  });

  return { files, diffText };
}

describe.skipIf(!HAS_FINDINGS_DIR)('integration: 3 known error cases → likely_rediscovery', () => {
  it('nitro-patch-diff-001-finding-1: bypass→rediscovery (else-if guard reachability claim)', () => {
    const runId = 'run-2026-05-28-nitro-patch-diff-001';
    const findings = loadFindingsJsonl(runId);
    const finding = findings.find((f) => f.id.endsWith('-finding-1'))!;
    const patch = fetchPatch(getPatchCommit(runId), getRepoPath(runId));

    const verdict = runStructuralOracle(finding, patch);
    expect(verdict.structuralClassification).toBe('likely_rediscovery');
    expect(verdict.citationOverlap).toBe('overlap');
  });

  it('nitro-patch-diff-001-finding-2: bypass→rediscovery (proxy else-if guard reachability claim)', () => {
    const runId = 'run-2026-05-28-nitro-patch-diff-001';
    const findings = loadFindingsJsonl(runId);
    const finding = findings.find((f) => f.id.endsWith('-finding-2'))!;
    const patch = fetchPatch(getPatchCommit(runId), getRepoPath(runId));

    const verdict = runStructuralOracle(finding, patch);
    expect(verdict.structuralClassification).toBe('likely_rediscovery');
    expect(verdict.citationOverlap).toBe('overlap');
  });

  it('jwt-go-patch-diff-002-finding-2: bypass→rediscovery (patch handles []string case)', () => {
    const runId = 'run-2026-06-02-jwt-go-patch-diff-002';
    const findings = loadFindingsJsonl(runId);
    const finding = findings.find((f) => f.id.endsWith('-finding-2'))!;
    const patch = fetchPatch(getPatchCommit(runId), getRepoPath(runId));

    const verdict = runStructuralOracle(finding, patch);
    expect(verdict.structuralClassification).toBe('likely_rediscovery');
    expect(verdict.citationOverlap).toBe('overlap');
  });
});

// ---------------------------------------------------------------------------
// Integration: confirmed bypasses (oracle must NOT produce likely_rediscovery)
// ---------------------------------------------------------------------------

describe.skipIf(!HAS_FINDINGS_DIR)('integration: confirmed bypasses → likely_bypass or inconclusive', () => {
  it('b-run-001-finding-1: futimes in promises.js → likely_bypass', () => {
    const runId = 'run-2026-05-29-nodejs-b-run-001';
    const findings = loadFindingsJsonl(runId);
    const finding = findings.find((f) => f.id.endsWith('-finding-1'))!;
    const patch = fetchPatch(getPatchCommit(runId), getRepoPath(runId));

    const verdict = runStructuralOracle(finding, patch);
    expect(verdict.structuralClassification).not.toBe('likely_rediscovery');
  });

  it('b-run-001-finding-3: ftruncate promise in promises.js → likely_bypass', () => {
    const runId = 'run-2026-05-29-nodejs-b-run-001';
    const findings = loadFindingsJsonl(runId);
    const finding = findings.find((f) => f.id.endsWith('-finding-3'))!;
    const patch = fetchPatch(getPatchCommit(runId), getRepoPath(runId));

    const verdict = runStructuralOracle(finding, patch);
    expect(verdict.structuralClassification).not.toBe('likely_rediscovery');
  });

  it('oq8-v2-001-finding-1: FileHandle.chmod in promises.js → not likely_rediscovery', () => {
    // The only patched-file citation is lib/fs.js:1884 with role=sanitizer-bypass.
    // Oracle must exclude sanitizer-bypass citations from overlap — all primary
    // (non-sanitizer-bypass) citations are in promises.js (not in patch) → likely_bypass.
    const runId = 'run-2026-05-28-nodejs-oq8-v2-001';
    const findings = loadFindingsJsonl(runId);
    const finding = findings.find((f) => f.id.endsWith('-finding-1'))!;
    const patch = fetchPatch(getPatchCommit(runId), getRepoPath(runId));

    const verdict = runStructuralOracle(finding, patch);
    expect(verdict.structuralClassification).not.toBe('likely_rediscovery');
    expect(verdict.structuralClassification).toBe('likely_bypass');
  });
});
