# QA methodology imports

Status: item 1 SHIPPED 2026-07-11; item 2 spec'd, blocked on toolchain; **item 3 (page-aligned
fidelity gate) SHIPPED 2026-07-12 as gate 25 — the top QA-integrity item, gating**. Items 1-2
are opportunistic improvements borrowed from the strongest external practice found in the
2026-07-09 research pass; item 3 closes a blind spot in the flagship coverage gate surfaced by
the 2026-07-12 implementation review.

## 1. Per-page machine-checkable assertion cells (olmOCR-bench pattern) — SHIPPED 2026-07-11

**Shipped** as gate 24 (`src/pdf2epub/qa/assertions.py`, per-book
`books/<slug>/qa_assertions.yaml` fixture). Diverged from the sketch below in two ways the
implementation forced: (a) matching is on the shipped per-page slice normalized through
`core.textnorm.normalize`, so classes that normalizer *folds* (quote/dash shape, extra-space,
soft-hyphen/BOM) are NON-expressible and excluded — they stay with gates 9/10/11/20, and
structure loss stays with gates 23/6; (b) added `order` and `block_present` types plus
boundary-aware matching (`(?<!\w)…(?!\w)`) so a citation token like `35:8` cannot match inside
`135:8`. Seeded ~26 render-verified cells across the five books; the acceptance test
(me-and-rumi rebuilt `restore_spaces: false`) flips 10/10 lost-space cells to FAIL. The
proofread fix-loop now lands a cell per confirmed fix. Original sketch retained for provenance.

## 1 (original sketch). Per-page machine-checkable assertion cells (olmOCR-bench pattern)

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

## 3. Page-aligned fidelity gate (recall + precision + order + duplication) — TOP QA-integrity item

**SHIPPED 2026-07-12 as gate 25** (`src/pdf2epub/qa/fidelity.py`, `test_fidelity.py`). Diverged
from the sketch where the implementation forced it: (a) per-page comparison uses a NEW
**char-level** page slicer (`qa_pageslice.slice_page_chars`) that splits at the inline
pagebreak anchors — block-level slices mis-assign a page-spanning paragraph wholesale to the
first page, tanking recall on prose; (b) recall/precision compare each page against a **±1-page
window** because poppler's physical-page boundary and the EPUB anchor legitimately disagree by
up to a paragraph (chapter-opener drop caps, page-spanning paragraphs); (c) matching is
**rapidfuzz LCS** (fast enough to window a 360-page book); (d) duplication is a **Rabin-Karp
rolling hash** (fixed-stride shingling misses a repeat whose copies aren't stride-aligned —
which is every real duplicate). Thresholds (recall 0.75 / precision 0.72) set from the
mutation-vs-corpus separation margin (legit floor 0.84/0.82; mutations near 0). All six shipped
books PASS; a real injected duplication and a real anchor corruption both FAIL end-to-end. The
disputed-page defense (25b) ships advisory as planned. Original sketch retained below.

**What it is / why we want it.** Gate 2 (`qa/groundtruth.py:212 paged_coverage`) is
one-directional *recall*: for each source page it searches the WHOLE candidate
(`candidate.find(snippet)`, lines 241-244) and keeps whichever window matches best regardless
of position (line 251); its own comment (235) delegates order to gate 6. But gate 6
(`runner.py:229-249`) only checks that TOC/source **headings** land on their printed page —
not general body order. Consequences, confirmed by a focused experiment in the 2026-07-12
review:

```
correct text     100% coverage
swapped pages     100% coverage      <- reordered body passes
duplicated book   100% coverage      <- excess/duplicated text is invisible (recall-only)
```

The deterministic build makes gross reorder/duplication a *regression-bug* class, not a
routine event — but a QA harness whose flagship gate cannot fail on a duplicated book is a
false assurance, and "validated conversion" is the project's central claim. This is the
highest-value QA finding in the review. The raw material already exists: the emitter writes an
exact `epub:type="pagebreak"` anchor per printed page (used by the page-list nav and index
locators), so the candidate can be sliced per source page — the same partition gates 13-17 and
gate 24 already use.

**Design.**
- **Precision (new):** for each source-page slice of the candidate, what fraction is justified
  by *that* source page's ground truth? Recall + precision together catch both dropped and
  *duplicated/injected* text that recall alone misses.
- **Monotonicity (new, cheap):** run a SECOND coverage pass that is strictly cursor-monotonic
  (no whole-candidate `find` fallback) and flag any page whose monotonic match falls far below
  its best-window match — that delta is the reordering signal the current best-window search
  hides.
- **Duplicate-span detection:** hash shingles of the candidate; report any long span (e.g.
  ≥ a paragraph) that appears more than once and isn't a legitimate repeat (running head text
  is already stripped; footnote-marker text is short).
- **Explicit, itemized exceptions** (not blanket exclusions): relocated footnotes/endnotes
  (moved to the notes file by design), the rebuilt hyperlinked TOC (replaces printed TOC
  pages), and figure/figure-region pages — each already tracked, so the exception list is
  derivable, not hand-maintained.

**Disputed-page defense (the review's finding #2, folded in here).** `runner.py:162-172`
blanks engine-disputed pages (`engine_agreement < 90`) out of the coverage denominator —
66612 chars in islam-and-buddhism (pp.138-145), 27661 in book-of-knowledge (322-329), 13604 in
sufism (206-213). That exclusion is *reasonable* (both witnesses decode the broken CMap
differently; neither is ground truth), but a prose adjudication note is too weak for ~8k
chars/page, and gate-24 assertions currently cover those 24 pages with **one** heading-string
cell. Require, per disputed page, at least one machine-checkable defense: a page-level
alternate witness (OCR witness once [ocr-witness.md](ocr-witness.md) ships), figure treatment,
gate-24 assertion cells, or a reviewed block/order signature. Gate fails on a disputed page
with zero machine defense — turning "trust the render review happened" into a checked
invariant.

**Integration points**: `qa/groundtruth.py` (precision + monotonic passes, dup detection),
`qa/runner.py` (new gate 25, exception itemization, disputed-page defense check),
`qa_pageslice`/pagebreak-anchor partition (exists), gate-24 `assertions.py` (disputed-page
coverage requirement), NOTES.md expected-FIRE matrix (record the swapped/duplicated fixtures).

**Acceptance**: a scratch build with two pages swapped FAILS (monotonicity); a scratch build
with a chapter duplicated FAILS (precision + dup-span); the five current books PASS; every
disputed page in I&B/BoK/sufism either gains machine defense or the gate names it.

## Non-goals

- Replacing gate-level regression matrices (assertion cells complement them).
- Making the borrowed witnesses (§1 assertions aside) gate/fail builds — §1/§2 are evidence
  generators for adjudication. **§3 is the exception: it IS a gating check** — an unfalsifiable
  coverage number is worse than none.
- Back-porting poppler: if the system poppler is old, the witness just doesn't run.
