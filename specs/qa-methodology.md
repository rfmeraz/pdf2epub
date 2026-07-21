# QA methodology imports

Status: **#1 SHIPPED 2026-07-11 (gate 24); #3 SHIPPED 2026-07-12 (gate 25, gating)**;
#2 spec'd, blocked on toolchain (needs poppler ≥ 26.05; system has 26.01.0 as of
2026-07-21). One residual from #3 remains open: promoting the disputed-page defense
(25b) from advisory to gating. Items 1–2 are opportunistic improvements borrowed from
the strongest external practice found in the 2026-07-09 research pass; item 3 closed a
blind spot in the flagship coverage gate surfaced by the 2026-07-12 implementation
review. The aggregate layer on top of all per-book gates is `pdf2epub corpus`
(2026-07-19): byte-compare + per-rule counter deltas vs `books/corpus_baseline.json`
across every tracked config. **Baseline discipline (review #90 lesson): re-seed the
baseline in the same commit as any pipeline-code change** — a stale baseline makes the
counter deltas misattribute pre-existing drift to the change under review; the reliable
isolation method is a clean-HEAD build diffed against the patched build.

## 1. Per-page machine-checkable assertion cells (olmOCR-bench pattern) — SHIPPED

**Shipped 2026-07-11** as gate 24 (`src/pdf2epub/qa/assertions.py`, per-book
`books/<slug>/qa_assertions.yaml` fixture; pattern borrowed from olmOCR-bench,
https://github.com/allenai/olmocr/tree/main/olmocr/bench — per-page unit tests instead
of fuzzy similarity). Schema: `- {page, type: present|absent|order|block_present, text,
text2, note}`, page = printed label resolved through the page-list, matched on the
shipped per-page slice normalized through `core.textnorm.normalize`.

Divergences from the sketch the implementation forced: (a) classes the normalizer
*folds* (quote/dash shape, extra-space, soft-hyphen/BOM) are NON-expressible and
excluded — they stay with gates 9/10/11/20, and structure loss stays with gates 23/6;
(b) added `order` and `block_present` types plus boundary-aware matching
(`(?<!\w)…(?!\w)`) so a citation token like `35:8` cannot match inside `135:8`.
Acceptance held: the me-and-rumi rebuild with `restore_spaces: false` flips 10/10
lost-space cells to FAIL. The proofread fix-loop lands a cell per confirmed fix.

**Hardened 2026-07-19:** gate 24 now FAILS on a *missing* fixture — an authored `[]` is
the recorded "no print-verified fixes yet" decision; absence is a process hole. `init`
scaffolds `[]` and never clobbers.

## 2. poppler `-remove-hyphens` as a second dehyphenation witness — BLOCKED

**What it is.** poppler 26.05 (May 2026) added `pdftotext -remove-hyphens`
(https://poppler.freedesktop.org/releases.html), applying its own end-of-line
dehyphenation during extraction.

**Why we want it.** Our `dehyphenate_join` is a QA'd but *unwitnessed* operation: gate 9
polices residue (`al- Hilāl` seams), and the compound-prefix list (self-, all-, half-…)
plus per-book `keep_hyphens` guard known false joins, but nothing independently checks
each join decision. The field doesn't score dehyphenation at all (research finding); a
second engine's opinion is cheap and fits the existing witness doctrine exactly.

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
  per-site snippets in warnings.md — adjudication feeds the compound-prefix list /
  per-book `keep_hyphens` or a book-specific `qa.lost_space_allow`-style escape. NOT a
  gating check: two heuristics disagreeing is evidence, not a verdict (engines witness,
  never co-author).

**Integration points**: `src/pdf2epub/qa/groundtruth.py` (second pdftotext invocation +
version probe), `qa/runner.py` (comparison + warning emission), `warnqueue.py`
(advisory code), NOTES.md verification-baselines entry (record the poppler version).

**Acceptance**: on the tracked corpus, the witness runs and the disagreement list is
small and explicable (spot-verify 5 sites against renders); the known compound cases
('self-evident', 'all-embracing') appear as class-(a) sites — confirming the witness
sees what our prefix/keep lists guard; no gate verdict changes.

## 3. Page-aligned fidelity gate (recall + precision + order + duplication) — SHIPPED

**Shipped 2026-07-12 as gate 25** (`src/pdf2epub/qa/fidelity.py`, `test_fidelity.py`),
the top QA-integrity item and gating. Why it exists: the prior flagship coverage gate
was one-directional *recall* — a focused experiment in the 2026-07-12 review showed a
page-swapped book and a duplicated book both scoring 100% coverage. A QA harness whose
flagship gate cannot fail on a duplicated book is false assurance, and "validated
conversion" is the project's central claim. The raw material already existed: the
emitter writes an exact `epub:type="pagebreak"` anchor per printed page, so the
candidate can be sliced per source page — the same partition gates 13–17 and 24 use.

Divergences from the sketch the implementation forced: (a) per-page comparison uses a
**char-level** page slicer (`qa_pageslice.slice_page_chars`) splitting at the inline
pagebreak anchors — block-level slices mis-assign a page-spanning paragraph wholesale
to the first page, tanking recall on prose; (b) recall/precision compare each page
against a **±1-page window** because poppler's physical-page boundary and the EPUB
anchor legitimately disagree by up to a paragraph; (c) matching is **rapidfuzz LCS**;
(d) duplication is a **Rabin-Karp rolling hash** (fixed-stride shingling misses a
repeat whose copies aren't stride-aligned — which is every real duplicate). Thresholds
(recall 0.75 / precision 0.72) set from the mutation-vs-corpus separation margin (legit
floor 0.84/0.82; mutations near 0). Acceptance held: a real injected duplication and a
real anchor corruption both FAIL end-to-end; the corpus PASSes. Explicit itemized
exceptions (relocated notes, rebuilt TOC, figure pages) are derivable, not
hand-maintained.

**Open residual — 25b promotion.** Engine-disputed pages (`engine_agreement < 90`) are
excluded from the fidelity denominator (both witnesses decode a broken CMap
differently; neither is ground truth), and 25b currently reports *advisory* the
disputed pages lacking any machine-checkable defense (gate-24 cells, figure treatment,
or — once ocr-witness.md ships — an OCR witness). The sketch's end state is a **gating**
requirement: a disputed page with zero machine defense fails, turning "trust the render
review happened" into a checked invariant. Promote when the corpus's currently-open
advisory items (e.g. mystics pp.138–143) gain their defenses.

## Non-goals

- Replacing gate-level regression matrices (assertion cells complement them).
- Making the borrowed witnesses gate/fail builds — #1 assertions aside, #2 is an
  evidence generator for adjudication. **#3 is the exception: it IS a gating check** —
  an unfalsifiable coverage number is worse than none.
- Back-porting poppler: if the system poppler is old, the #2 witness just doesn't run.
