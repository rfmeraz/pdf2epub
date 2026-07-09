# pdf2epub

Convert a print-oriented book PDF — the only input — into a validated, reflowable
EPUB 3 with a hyperlinked table of contents. No InDesign, no source files, no
Adobe products.

## How a conversion works

1. **Drop the PDF** at `books/<slug>/package/` (separate cover art, if any, in
   `books/<slug>/assets/`).
2. **`pdf2epub init`** extracts the PDF (PyMuPDF: text spans with font/size/style
   and positions, clipped to the trim box; bookmarks; internal TOC links; page
   labels) and analyzes it into deterministic evidence: font clusters with
   proposed roles, running-head/folio furniture, footnote regions, the printed
   Contents parse cross-checked against bookmarks and link targets, special-glyph
   census, page thumbnails. It writes `analysis/structure_report.md` and a draft
   `book.yaml`.
3. **The agent infers the structure.** A conversion agent (Claude, via the
   `/convert-pdf` skill) reads the evidence, LOOKS at page renders, and records
   every judgment in `book.yaml`: which font cluster is a heading, where front
   matter ends, which TOC witness to trust, how footnotes work, what each
   private-use glyph means, the cover. PDFs of different vintages behave
   differently — this inference step is part of the design, and the file it
   produces makes the build reproducible and auditable.
4. **`pdf2epub build`** is fully deterministic from (PDF, book.yaml): strip
   furniture, split footnotes, join lines into paragraphs (dehyphenation,
   drop-cap reattachment, cross-run lost-space seams), re-split columned back
   matter into print reading
   order (`flow.columns`: indexes and other tabular apparatus whose baseline-
   fused lines would otherwise interleave), ship true tables/diagrams as
   cropped rasters with agent-written alt (`images.figure_regions`), apply
   roles, insert exact printed-page markers (a page that begins mid-paragraph
   gets an inline anchor at the true run seam),
   rebuild the Contents with live hyperlinks, emit XHTML+CSS, subset OFL fonts,
   and package a byte-reproducible EPUB. Ambiguities WARN into
   `build/warnings.md` (`warnings.<stem>.md` for variant configs) as a coded,
   severity-classed queue with ready-to-paste override/adjudication snippets;
   nothing is ever silently dropped, and judgments already recorded in
   book.yaml auto-resolve their warnings.
5. **`pdf2epub qa`** runs 23 gates: epubcheck, text coverage against an
   independent poppler extraction, footnote placement, navigation, images/alt,
   reading order (every TOC entry's heading on its printed page), TOC agreement,
   furniture leaks, hyphenation / private-use / lost-space residue (gate 11
   gates at zero with a render-verified `qa.lost_space_allow` escape), an
   optional EPUB-vs-EPUB reference scorecard — plus five typographic-fidelity
   gates (13-17) that grade the SHIPPED markup+CSS against raw source geometry:
   cluster sizes survive into the CSS, every centered paragraph has genuinely
   centered source lines, emphasis is conserved, headings are typographically
   real, and each page's block-level signature (size buckets + centering)
   matches print — and a noteref-seam lint (11b: a letter directly after a
   note marker is always a lost join). Gate 19 validates a shipped "Qurʾānic
   verses cited" index against the Qurʾān's fixed structure (114 suras with
   Ḥafṣ/Kufan verse counts, monotone entry order, page refs in the page-list):
   the columned index pages are engine-disputed so gate 2's coverage witness
   is blind there, and column interleaving produces impossible citations this
   gate catches deterministically. Gate 20 scans the SHIPPED text for garble
   (U+FFFD and C0 controls unconditionally, plus the book's configured
   `qa.garble_chars` residue set) — candidate-only by design, since the
   coverage gate normalizes both sides identically and cannot see corruption
   both witnesses share. Gate 21 dHash-compares every shipped figure image
   against a re-render of its source PDF region (a blank or corrupt figure is
   content loss no text gate can see). Gate 22 re-derives the build's warning
   queue and fails on any open content-risk warning or stale `adjudications:`
   entry — `Overall: PASS` now certifies the risky-page queue was actually
   adjudicated. `qa --visual` adds gate 18: sampled
   side-by-side contact sheets (print page vs anchor-sliced EPUB render in
   headless Chrome), PUA glyph crop pairs, and figure perceptual-hash checks
   into `build/qa_visual/` for the converting agent to grade against a
   generated checklist.
6. **`pdf2epub proofread` — reading QA (mandatory).** The shipped EPUB is
   re-rendered as per-section review packets (page markers, `[n]` noterefs,
   figure alts, a generated protocol with a closed defect taxonomy and the
   book's do-not-flag conventions). The agent fans out one blind reader per
   packet hunting conversion damage — fused/split paragraphs, seam spaces,
   garble, flattened verse — verifies every finding against the print render
   (`pdf2epub lines <config> <page> --render`), and fixes accepted findings
   only via book.yaml or code, never by editing text. Rebuild, re-run,
   re-read changed packets until a round comes back clean.

A conversion is done when the build ends `epubcheck: clean`, QA ends
`Overall: PASS`, and the proofread loop ends with zero new confirmed
findings (or the remainder is escalated in the handoff report).

## Commands

```bash
~/pyenv/bin/pdf2epub init  books/<slug>/package --workspace books/<slug>
~/pyenv/bin/pdf2epub build books/<slug>/book.yaml [--upto extract|flow|map|images|xhtml] [--dump-ir]
~/pyenv/bin/pdf2epub qa    books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml [--reference <epub>] [--visual]
~/pyenv/bin/pdf2epub proofread books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml  # reading-QA packets
~/pyenv/bin/pdf2epub lines books/<slug>/book.yaml <page> [--render]  # raw line indexes for overrides
bash scripts/bootstrap.sh   # one-time: pip deps, epubcheck jar, fonts
```

## Design commitments

- **Never rewrite the book's words.** Deterministic, counted repairs only
  (line-end dehyphenation, lost-space restoration, verified glyph substitution);
  anything beyond that escalates to a human.
- **Warn loudly, never drop silently.** Unknown constructs and ambiguous
  decisions surface in `build/warnings.md` for adjudication.
- **OFL fonts only, from system files.** Fonts are never extracted from the PDF;
  proprietary faces (Minion, Bembo, MS Mincho…) are never embedded.
- **Byte-reproducible builds.** Fixed timestamps, deterministic identifiers, no
  randomness — same PDF + same book.yaml = same EPUB, on the same toolchain.
- **Two extraction witnesses.** PyMuPDF is the spine; poppler independently
  scores every page and grounds the QA coverage gate. Disagreement flags a page
  for review — engines never vote on the text.

## Provenance

The EPUB back-end (`src/pdf2epub/core/`) is forked from the sister project
[idml2epub](../idml2epub) (InDesign-package conversions); per-file provenance
headers name the source commit. The projects diverge independently by design.
