# Semantic-EPUB polish package

Status: **#1 SHIPPED 2026-07-11; #2 automated readiness SHIPPED 2026-07-12 (gate 26)**;
open: #2's manual-certification workflow (required before any `conformsTo` claim) and
#3 typogrify-lite. Shared goal: close the gap between "passes epubcheck" and "excellent
semantic EPUB" using machinery the pipeline already has (page anchors, endnote
apparatus, textfix counting).

## 1. Linked index locators — SHIPPED

**Shipped 2026-07-11** (`src/pdf2epub/index_locators.py`; opt-in via
`flow.columns[].index: true` or the `index` role; DAISY `<section epub:type="index"
role="doc-index">` container per https://kb.daisy.org/publishing/docs/html/indexes.html;
guarded page-anchor linking through the existing `pg-<label>` registry + advisory
`index-locator-unlinked` for locators outside the page-list). BoK ships 3770 linked
locators; epubcheck clean, gates 4/19/Overall PASS. Numbers remain the printed text —
linking wraps, never rewrites. The IDPF EPUB Indexes package machinery was deliberately
NOT implemented (dead spec; DAISY KB concurs). See NOTES.md "Linked index locators +
Kindle output (2026-07-11)".

**Deferred residuals:** aria-label on ranges (`49–51` → "49 to 51"), roman-numeral
front-matter locators (kept unlinked, counted), and Me & Rumi's currently-excluded 62
index pages (375–436) — a separate conversion effort that now inherits the linking for
free.

## 2. EAA / accessibility conformance — automated readiness SHIPPED; certification OPEN

**Automated readiness shipped 2026-07-12 as gate 26** (`src/pdf2epub/qa/a11y.py` +
`qa/ace.py`, pinned via `tools/ace/package.json`): stricter alt coverage
(role=presentation OR non-empty alt — not qa_imagecheck's permissive
empty-is-decorative) + accessibility-metadata presence + Ace by DAISY gating on
critical/serious (absence skips; a crash/timeout FAILS — the epubcheck-jar precedent).
The baseline run surfaced a real **serious** `epub-pagesource` violation on every
page-numbered book — fixed by emitting `<meta property="pageBreakSource">` + the
`printPageNumbers` feature in the packager. Context: the European Accessibility Act has
been in force since 2025-06-28; the W3C's EPUB-a11y↔EAA mapping (Group Note 2025-08-28,
https://www.w3.org/TR/epub-a11y-eaa-mapping/) concludes EPUB Accessibility 1.1 + WCAG
satisfies the ebook requirements.

**`dcterms:conformsTo` is deliberately NOT emitted.** Ace explicitly cannot verify all
of WCAG — image-alt *appropriateness*, reading-order sense, heading *meaning* need
human inspection; DAISY and W3C both require manual evaluation of the complete
publication before a conformance claim
(https://kb.daisy.org/publishing/docs/epub/validation/ace.html;
https://www.w3.org/TR/epub-a11y-11/). Gate 26 is a readiness floor, not a conformance
claim — over-claiming conformance is itself an accessibility (and legal) risk.

**Open: manual certification workflow (before any `conformsTo`).**
- A per-book checklist step (alt-text adequacy, reading order, table/figure semantics,
  navigation) recorded like a proofread finding, tied to a specific EPUB revision (the
  provenance manifest / release epoch from reliability-hardening §2–§3).
- Only a passed, recorded certification writes `dcterms:conformsTo` = `EPUB
  Accessibility 1.1 - WCAG 2.1 Level AA` — the claim is auditable, not asserted by a
  tool that admits it can't check everything.
- `schema:accessibilitySummary` stays agent-written per book (like alt text — never
  auto-generated); verify `dc:source` carries the print ISBN (pagination-source
  requirement, https://www.w3.org/TR/epub-a11y-11/).
- The convert-pdf/proofread skills gain the checklist step.
- ONIX codelist 196 metadata remains out of scope (no ONIX feed exists for these books).

**Acceptance (certification):** `conformsTo` appears ONLY on books with a recorded
manual certification against the shipped revision; epubcheck stays clean (it validates
the a11y metadata vocabulary); a re-build after certification invalidates the record
until re-certified (revision-tied by construction).

## 3. typogrify-lite (presentation-codepoint polish) — OPEN

**Problem.** The "beautiful" layer that distinguishes Standard Ebooks output:
word joiner U+2060 before em-dashes (no line starting with a dash), hair spaces
U+200A between adjacent quotation marks, proper ellipsis spacing
(https://standardebooks.org/manual/1.9.0/8-typography). Our shipped text carries the
book's own punctuation unpolished.

**Design.** A `flow.typography: true` opt-in textfix pass (default OFF — deviation from
source bytes must be a recorded judgment), applied in `_apply_textfix` after existing
repairs, inserting ONLY zero-width/space-class presentation codepoints:
- `X—Y` → `X⁠—⁠Y` (U+2060 WORD JOINER around em dash; SE convention).
- `"'` / `'"` adjacencies → hair space U+200A between.
- NEVER touch: quotes themselves (the corpus uses U+2018/2019 both as quotes AND as
  ʿayn/hamza stand-ins in transliteration — see specs/arabic-fonts.md; any quote
  "correction" risks corrupting the apparatus), hyphens/dashes substitution, ellipsis
  char replacement. Insertion-only, of invisible codepoints.
- Every insertion counted per class in the build log (`restore_spaces` precedent);
  `normalize()` must strip U+2060/U+200A so coverage/lost-space comparisons are
  unaffected (verify `\s` covers U+200A — yes — and add U+2060 to the translate map,
  it is NOT whitespace).

**Never-rewrite compliance**: zero visible-glyph changes; reversible by stripping two
codepoints; counted; opt-in per book.

**Integration points**: `src/pdf2epub/textfix.py`, `core/textnorm.py` (U+2060 strip),
`config.py` (flow key), tests (counting, normalize round-trip, ʿayn/hamza strings pass
through byte-identical).

**Acceptance**: enabled on one book, gate suite verdicts unchanged, renders show no
dash-orphaned lines in narrow-column Chrome slices; disabled books byte-identical.

## Non-goals (whole package)

- Popup-footnote `<aside>` restructuring: current endnotes file with
  `epub:type="footnote"` `<li>`s + noteref/backlink pairs already gets popups on
  Apple/Kobo/Kindle-ET/Thorium; restructuring risks the non-popup fallback rendering.
- EPUB Indexes package-document machinery (dead spec).
- Automated `accessibilitySummary` generation — agent-written per book, like alt text.
