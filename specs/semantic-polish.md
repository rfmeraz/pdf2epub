# Semantic-EPUB polish package

Status: spec'd, not implemented. Three independent items, individually shippable, in
priority order. Shared goal: close the gap between "passes epubcheck" and "excellent
semantic EPUB" using machinery the pipeline already has (page anchors, endnote
apparatus, textfix counting).

## 1. Linked index locators

**IMPLEMENTED 2026-07-11** (`src/pdf2epub/index_locators.py`; opt-in via
`flow.columns[].index: true` or the new `index` role; DAISY `<section
epub:type="index">` container; guarded page-anchor linking + advisory
`index-locator-unlinked`; BoK ships 3770 linked locators, epubcheck clean, gates
4/19/Overall PASS). Deferred: aria-label on ranges, roman-numeral fm locators,
and Me & Rumi's index pages (a separate conversion effort that now inherits
this). See NOTES.md "Linked index locators + Kindle output (2026-07-11)".

**Problem.** Back-of-book indexes ship (via `flow.columns`) as plain paragraphs whose
page numbers are dead text. The DAISY knowledge base's recommended shape is an index
whose every locator hyperlinks to an anchor at the referenced location
(https://kb.daisy.org/publishing/docs/html/indexes.html) — and we already emit an
anchor for every printed page (`epub:type="pagebreak"`, complete monotone page-list,
exact inline seams since 2026-07-09). This is the highest-leverage polish item: it
makes the shipped index *better than print* and is the prerequisite for shipping
Me & Rumi's currently-excluded 62 index pages (375–436) well.

**Design.**
- At emit time, for paragraphs on `flow.columns` pages (and any paragraph carrying a
  new `index-entry` role), tokenize trailing/embedded locator lists: `\d+(?:[–-]\d+)?`
  sequences separated by `, ` after the entry text. Wrap each in
  `<a href="<file>#pg-<label>">` resolved through the existing page-anchor registry
  (emitter's `pagebreaks` records + nav page-list builder in `core/nav.py:104-110`).
- Ranges link to the FIRST page's anchor with an accessible label:
  `<a href="...#pg-49" aria-label="49 to 51">49–51</a>` (DAISY pattern).
- Locators referencing pages outside the page-list (roman-numeral fm refs, "n." note
  suffixes like `189n.4`) keep the printed text unlinked — WARN once per book with
  counts (`index-locator-unlinked`, ADVISORY).
- Container semantics: the index section's wrapper gains `epub:type="index"
  role="doc-index"`. Do NOT implement the IDPF EPUB Indexes package machinery — the
  spec is dead in the field (DAISY KB: "no need to follow the package document
  identification requirements").
- Numbers must remain the printed text (never-rewrite); linking wraps, never rewrites.

**QA.** New check inside an existing gate or a small new gate: every emitted index
locator link resolves to an existing id (epubcheck catches broken hrefs, but pre-empt
with a targeted check listing per-page counts); gate 19 (Qurʾānic index) is unaffected
— it reads text, and its (sura, verse, pages) parse must be taught to see through `<a>`
wrappers (it uses text extraction, so likely no change; verify).

**Integration points**: `core/emit_xhtml.py` (locator tokenizer at contents/columns
emission), `core/nav.py` (anchor registry already exists), `qa/quran.py` (verify
parse), `warnqueue.py` (advisory code), tests: BoK pp.322–336 fixture (132 verse-index
entries + general index with sub-entries and turnover joins — real geometry in
`books/book-of-knowledge/build/ir/`).

**Acceptance**: BoK rebuild ships both indexes fully linked (spot-verify 35:8→35:28
seam entries land on pp.322–323 anchors); M&R indexes conversion (separate effort)
inherits it for free.

## 2. EAA / accessibility conformance

**Problem.** The European Accessibility Act has been in force for products/services
since 2025-06-28; the W3C's EPUB-a11y↔EAA mapping (Group Note 2025-08-28,
https://www.w3.org/TR/epub-a11y-eaa-mapping/) concludes EPUB Accessibility 1.1 + WCAG
satisfies the ebook requirements. We are close but not declared: `packager.py:102-115`
already writes accessMode/accessModeSufficient/accessibilityFeature/accessibilityHazard
(+ pageNavigation/pageBreakMarkers when anchors exist).

**Design.**
- Add to the OPF: `dcterms:conformsTo` = `EPUB Accessibility 1.1 - WCAG 2.1 Level AA`
  (only when the checks below pass), `schema:accessibilitySummary` (already optional —
  make the convert-pdf skill record one per book), and verify `dc:source` carries the
  print ISBN (pagination source requirement, https://www.w3.org/TR/epub-a11y-11/).
- New QA gate: run **Ace by DAISY** (https://daisy.org/activities/software/ace/) when
  installed (`npx @daisy/ace`), fail on Ace "critical"/"serious" violations, skip with
  an info line when the binary is absent (epubcheck-jar precedent in
  `scripts/bootstrap.sh` — add Ace install there).
- Language declarations: already strong (`lang`/`xml:lang` on html + inline `:lang`
  spans). Heading hierarchy: gate 6/audit already police h1–h3 sanity.
- ONIX codelist 196 metadata is out of scope (no ONIX feed exists for these books).

**Acceptance**: all five shipped books re-validate through Ace clean (or with
documented, adjudicated exceptions); OPF carries conformsTo + summary; epubcheck stays
clean (it validates the a11y metadata vocabulary).

## 3. typogrify-lite (presentation-codepoint polish)

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
  `normalize()` must strip U+2060/U+200A so gate 2/11 comparisons are unaffected
  (verify `\s` covers U+200A — yes — and add U+2060 to the translate map, it is NOT
  whitespace).

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
