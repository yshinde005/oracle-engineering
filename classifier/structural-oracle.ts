/**
 * Structural oracle for bypass-vs-rediscovery classification.
 *
 * An independent (non-LLM) check that verifies the factual premises
 * that bypass/rediscovery classification depends on, using only the
 * patch diff and citation metadata as inputs. No model calls.
 *
 * Two checks:
 *
 * Check 1 — Citation-patch overlap:
 *   Determines whether each cited file+line falls within a modified
 *   hunk in the patch diff. A citation that overlaps with a patched
 *   hunk describes code the patch already addresses → rediscovery
 *   signal. A citation in a file the patch never touches → bypass
 *   signal.
 *
 * Check 2 — Guard presence:
 *   Derived from Check 1: a citation that falls within a patched
 *   hunk means the hunk's added code (the guard/fix) applies to that
 *   location → guard_present. A citation outside any patched hunk →
 *   guard_absent.
 *
 * Classification:
 *   overlap  → likely_rediscovery
 *   disjoint → likely_bypass
 *   partial  → inconclusive  (patched file, unpatched lines — oracle's blind spot)
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OracleInput {
  id: string;
  citations: ReadonlyArray<{ file: string; line: number; role?: string }>;
}

export interface PatchInput {
  /** Relative paths (relative to repo root) of files changed by the commit. */
  files: ReadonlyArray<string>;
  /** Raw unified diff text from `git show --unified=5`. */
  diffText: string;
}

export type CitationOverlap = 'overlap' | 'disjoint' | 'partial';
export type GuardPresence = 'guard_present' | 'guard_absent';
export type StructuralClassification = 'likely_rediscovery' | 'likely_bypass' | 'inconclusive';

export interface OracleVerdict {
  findingId: string;
  citationOverlap: CitationOverlap;
  /** Per-citation guard presence, in the same order as finding.citations. */
  guardPresence: GuardPresence[];
  structuralClassification: StructuralClassification;
  /** Human-readable explanation of the classification decision. */
  reasoning: string;
}

// ---------------------------------------------------------------------------
// Internal: diff parsing
// ---------------------------------------------------------------------------

interface ParsedHunk {
  /** Relative path of the file this hunk belongs to. */
  file: string;
  /** First line of the OLD (pre-patch) file covered by this hunk (inclusive). */
  oldStart: number;
  /** Last line of the OLD (pre-patch) file covered by this hunk (inclusive). */
  oldEnd: number;
  /** First line of the NEW (post-patch) file covered by this hunk (inclusive). */
  newStart: number;
  /** Last line of the NEW (post-patch) file covered by this hunk (inclusive). */
  newEnd: number;
  /** Lines added by this hunk (the `+` lines, stripped of the leading `+`). */
  addedLines: string[];
}

/**
 * Parse a unified diff into structured hunks.
 * Handles `diff --git a/path b/path` file headers and
 * `@@ -oldStart[,oldCount] +newStart[,newCount] @@` hunk headers.
 */
export function parseHunks(diffText: string): ParsedHunk[] {
  const hunks: ParsedHunk[] = [];
  const lines = diffText.split('\n');
  let currentFile = '';
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // File header: "diff --git a/path b/path"
    // Extract the b/ path as the canonical file path.
    if (line.startsWith('diff --git ')) {
      const m = /^diff --git a\/.+ b\/(.+)$/.exec(line);
      if (m) currentFile = m[1].trim();
      i++;
      continue;
    }

    // Hunk header: "@@ -oldStart[,oldCount] +newStart[,newCount] @@"
    if (line.startsWith('@@ ') && currentFile) {
      const m = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(line);
      if (m) {
        const oldStart = parseInt(m[1], 10);
        const oldCount = m[2] !== undefined ? parseInt(m[2], 10) : 1;
        const oldEnd = oldStart + Math.max(oldCount - 1, 0);

        const newStart = parseInt(m[3], 10);
        const newCount = m[4] !== undefined ? parseInt(m[4], 10) : 1;
        const newEnd = newStart + Math.max(newCount - 1, 0);

        // Collect + lines until the next hunk or file header.
        const addedLines: string[] = [];
        i++;
        while (
          i < lines.length &&
          !lines[i].startsWith('@@ ') &&
          !lines[i].startsWith('diff --git ')
        ) {
          const l = lines[i];
          if (l.startsWith('+') && !l.startsWith('+++')) {
            addedLines.push(l.slice(1));
          }
          i++;
        }

        hunks.push({ file: currentFile, oldStart, oldEnd, newStart, newEnd, addedLines });
        continue;
      }
    }

    i++;
  }

  return hunks;
}

// ---------------------------------------------------------------------------
// Internal: file path matching
// ---------------------------------------------------------------------------

/**
 * Returns true if `citationFile` and `hunkFile` refer to the same file.
 *
 * Handles three scenarios:
 *   1. Exact match (both paths identical)
 *   2. Suffix match (one path is a suffix of the other — handles relative vs
 *      root-relative differences, e.g. "map_claims.go" vs "map_claims.go")
 *   3. Basename match (same filename, different directories — fallback only)
 */
function matchesFile(citationFile: string, hunkFile: string): boolean {
  if (citationFile === hunkFile) return true;
  if (hunkFile.endsWith('/' + citationFile) || citationFile.endsWith('/' + hunkFile)) return true;
  const cBase = citationFile.split('/').at(-1) ?? citationFile;
  const hBase = hunkFile.split('/').at(-1) ?? hunkFile;
  return cBase === hBase && cBase.length > 0;
}

// ---------------------------------------------------------------------------
// Internal: per-citation check
// ---------------------------------------------------------------------------

type CitationStatus = 'in_hunk' | 'in_patched_file' | 'not_in_patch';

function classifyCitation(
  citation: { file: string; line: number },
  hunks: ParsedHunk[],
  patchedFiles: ReadonlyArray<string>,
): CitationStatus {
  // Check if any hunk covers this file+line in either coordinate frame.
  // Citations come from the finding, which was produced from the target commit.
  // If the target is pre-patch, citation lines are in old-file coordinates.
  // If the target is post-patch, citation lines are in new-file coordinates.
  // Checking both frames catches either case without requiring a git ancestry query.
  for (const hunk of hunks) {
    if (matchesFile(citation.file, hunk.file)) {
      if (
        (citation.line >= hunk.oldStart && citation.line <= hunk.oldEnd) ||
        (citation.line >= hunk.newStart && citation.line <= hunk.newEnd)
      ) {
        return 'in_hunk';
      }
    }
  }

  // Check if the file is at least patched (even if this line isn't in a hunk).
  for (const pf of patchedFiles) {
    if (matchesFile(citation.file, pf)) {
      return 'in_patched_file';
    }
  }

  return 'not_in_patch';
}

// ---------------------------------------------------------------------------
// Public: runStructuralOracle
// ---------------------------------------------------------------------------

/**
 * Run the structural oracle on a single finding.
 *
 * @param finding - The finding to classify (id + citations).
 * @param patch   - The patch diff (files list + raw diff text).
 * @returns Oracle verdict with citation overlap, guard presence,
 *          structural classification, and human-readable reasoning.
 */
export function runStructuralOracle(finding: OracleInput, patch: PatchInput): OracleVerdict {
  if (finding.citations.length === 0) {
    return {
      findingId: finding.id,
      citationOverlap: 'disjoint',
      guardPresence: [],
      structuralClassification: 'inconclusive',
      reasoning: 'No citations to check.',
    };
  }

  const hunks = parseHunks(patch.diffText);

  // Primary citations: source/sink/flow/intermediate that form the attack path.
  // Sanitizer-bypass citations point to PATCHED guards being contrasted with
  // an unguarded path — they indicate bypass intent, not rediscovery of the
  // patched code, so they are excluded from the overlap classification signal.
  const primaryCitations = finding.citations.filter((c) => c.role !== 'sanitizer-bypass');
  // Fall back to all citations if every citation has a sanitizer-bypass role.
  const activeCitations = primaryCitations.length > 0 ? primaryCitations : finding.citations;

  const statuses: CitationStatus[] = activeCitations.map((c) =>
    classifyCitation(c, hunks, patch.files),
  );

  const inHunkCount = statuses.filter((s) => s === 'in_hunk').length;
  const inPatchedFileCount = statuses.filter((s) => s === 'in_patched_file').length;

  // Check 1: citation-patch overlap
  let citationOverlap: CitationOverlap;
  if (inHunkCount > 0) {
    citationOverlap = 'overlap';
  } else if (inPatchedFileCount > 0) {
    citationOverlap = 'partial';
  } else {
    citationOverlap = 'disjoint';
  }

  // Check 2: guard presence — per-citation, derived from hunk membership.
  // A citation that falls within a patched hunk means the patch's added code
  // (the guard/fix) applies to that exact location.
  const guardPresence: GuardPresence[] = statuses.map((s) =>
    s === 'in_hunk' ? 'guard_present' : 'guard_absent',
  );

  // Classification: overlap → rediscovery, disjoint → bypass, partial → inconclusive.
  let structuralClassification: StructuralClassification;
  if (citationOverlap === 'overlap') {
    structuralClassification = 'likely_rediscovery';
  } else if (citationOverlap === 'disjoint') {
    structuralClassification = 'likely_bypass';
  } else {
    structuralClassification = 'inconclusive';
  }

  // Reasoning: summarise which citations drove the verdict.
  const sanitizerBypassCount = finding.citations.length - activeCitations.length;
  const reasoning = buildReasoning(activeCitations, statuses, structuralClassification, sanitizerBypassCount);

  return { findingId: finding.id, citationOverlap, guardPresence, structuralClassification, reasoning };
}

function buildReasoning(
  citations: ReadonlyArray<{ file: string; line: number; role?: string }>,
  statuses: CitationStatus[],
  verdict: StructuralClassification,
  sanitizerBypassCount = 0,
): string {
  const parts: string[] = [];

  const inHunk = citations.filter((_, i) => statuses[i] === 'in_hunk');
  const inFile = citations.filter((_, i) => statuses[i] === 'in_patched_file');
  const notIn = citations.filter((_, i) => statuses[i] === 'not_in_patch');

  if (inHunk.length > 0) {
    parts.push(
      `${inHunk.length} citation(s) fall within patched hunk(s): ` +
      inHunk.map((c) => `${c.file}:${c.line}`).join(', '),
    );
  }
  if (inFile.length > 0) {
    parts.push(
      `${inFile.length} citation(s) in a patched file but outside patched hunks: ` +
      inFile.map((c) => `${c.file}:${c.line}`).join(', '),
    );
  }
  if (notIn.length > 0) {
    parts.push(
      `${notIn.length} citation(s) in files not touched by the patch: ` +
      notIn.map((c) => `${c.file}:${c.line}`).join(', '),
    );
  }

  if (sanitizerBypassCount > 0) {
    parts.push(
      `${sanitizerBypassCount} sanitizer-bypass citation(s) excluded from overlap check ` +
      `(these point to patched guards, indicating bypass intent not rediscovery)`,
    );
  }

  const verdictLabel =
    verdict === 'likely_rediscovery'
      ? 'LIKELY_REDISCOVERY (cited code is in the patched area — the patch addresses this location)'
      : verdict === 'likely_bypass'
      ? 'LIKELY_BYPASS (all cited code is outside patched files — the patch does not touch these locations)'
      : 'INCONCLUSIVE (cited code is in patched file(s) but outside the modified hunks — oracle blind spot)';

  return `${parts.join('; ')}. Verdict: ${verdictLabel}.`;
}
