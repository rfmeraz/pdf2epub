# QA methodology imports

Status: spec'd, not implemented. Two independent, opportunistic improvements borrowed
from the strongest external practice found in the 2026-07-09 research pass.

## 1. Per-page machine-checkable assertion cells (olmOCR-bench pattern)

**What it is.** olmOCR-bench evaluates document extraction not by fuzzy similarity but
by per-page *unit tests*: presence assertions ("this exact string appears on page N"),
absence assertions ("this header does NOT appear"), and order assertions ("string A
precedes string B") — machine-checkable, version-controlled, accumulated over time
(https://github.com/allenai/olmocr/tree/main/olmocr/bench).

**Why we want it.** Our regression story today is *gate-level* expected-FIRE matrices
recorded in NOTES.md (gate 14 fires 42/27/68/87 on the pre-fix EPUBs, etc.) — strong,
but coarse: it pins that a gate still fires somewhere, not that a specific historical
defect stays fixed. Every print-verified proofread finding (p.46 Kaaba couplet, p.26
legend scramble, p.151 quote shatter, `Now,however` fusions…) is naturally expressible
as 2–5 assertions against the shipped EPUB.

**Design.**
- Per-book assertion file `books/<slug>/qa_assertions.yaml`, schema:
  `- {page: "138", type: present|absent|order, text: "...", text2: "...", note: "..."}`
  (page = printed label, resolved through the page-list; text matched on the
  normalized page slice from `qa_pageslice` — the same partition gates 13–17 use).
- New always-on gate "assertions": runs every entry; a failed assertion names its note.
  Stale-proof: an assertion whose page label no longer exists in the page-list fails
  loudly (flow.overrides staleness doctrine).
- The proofread skill's fix loop gains a step: every accepted finding lands an
  assertion cell alongside the fix — the same way "a misfiring heuristic becomes a code
  fix + unit test" (NOTES.md refinement loop), but for book-level defects that unit
  tests can't reach (they need the real PDF).
- Seed corpus: transcribe the known print-verified findings from NOTES.md /
  CONVERSIONS.md for all five books (~30–50 assertions) in the first pass.

**Integration points**: `qa/runner.py` (new gate), `config.py` or a standalone loader
(assertions file is per-book but NOT part of book.yaml — it's a test artifact, tracked,
but not a build input; keep build inputs and QA fixtures separate), `qa_pageslice`
(page-slice text access already exists), `.claude/skills/proofread-epub/SKILL.md`
(fix-loop step), NOTES.md.

**Acceptance**: seeded assertions pass on current builds; deliberately reverting one
historical fix (e.g. rebuild M&R with `restore_spaces: false` to a scratch dir) makes
its cells fail; runtime cost < 1s/book.

## 2. poppler `-remove-hyphens` as a second dehyphenation witness

**What it is.** poppler 26.05 (May 2026) added `pdftotext -remove-hyphens`
(https://poppler.freedesktop.org/releases.html), applying its own end-of-line
dehyphenation during extraction.

**Why we want it.** Our `dehyphenate_join` is a QA'd but *unwitnessed* operation: gate 9
polices residue (`al- Hilāl` seams), and the compound-prefix list (self-, all-, half-…)
guards known false joins, but nothing independently checks each join decision. The
field doesn't score dehyphenation at all (research finding); a second engine's opinion
is cheap and fits the existing witness doctrine exactly.

**Design.**
- At QA time (not build), run `pdftotext -remove-hyphens` alongside the existing
  ground-truth extraction (same trim-crop discipline — the witness MUST be cropped to
  the trim box, NOTES.md field note). Version-gate on `pdftotext -v` ≥ 26.05; skip
  silently below (toolchain-scoped reproducibility, as with PyMuPDF/poppler versions in
  the build log).
- Diff OUR dehyphenated flow text against poppler's per page, restricted to hyphen-join
  sites (we count and locate every join — `para_lines` provenance + join counters).
  Disagreements: (a) we joined, poppler kept the hyphen → compound-word candidate
  (their conservative side); (b) we kept, poppler joined → missed-join candidate.
- Report as a new ADVISORY warning code (`dehyphenation-witness-disagrees`) with
  per-site snippets in warnings.md — adjudication feeds the compound-prefix list or a
  book-specific `qa.lost_space_allow`-style escape. NOT a gating check: two heuristics
  disagreeing is evidence, not a verdict (engines witness, never co-author).

**Integration points**: `src/pdf2epub/qa/groundtruth.py` (second pdftotext invocation +
version probe), `qa/runner.py` (comparison + warning emission), `warnqueue.py`
(advisory code), NOTES.md verification-baselines entry (record the poppler version).

**Acceptance**: on the five current books, the witness runs and the disagreement list
is small and explicable (spot-verify 5 sites against renders); the known compound cases
('self-evident', 'all-embracing') appear as class-(a) sites — confirming the witness
sees what our prefix list guards; no gate verdict changes.

## Non-goals

- Replacing gate-level regression matrices (assertion cells complement them).
- Making either check gate/fail builds — both are evidence generators for adjudication.
- Back-porting poppler: if the system poppler is old, the witness just doesn't run.
