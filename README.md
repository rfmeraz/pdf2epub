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
   drop-cap reattachment), apply roles, insert exact printed-page markers,
   rebuild the Contents with live hyperlinks, emit XHTML+CSS, subset OFL fonts,
   and package a byte-reproducible EPUB. Ambiguities WARN into
   `build/warnings.md` with ready-to-paste override snippets; nothing is ever
   silently dropped.
5. **`pdf2epub qa`** runs 12 gates: epubcheck, text coverage against an
   independent poppler extraction, footnote placement, navigation, images/alt,
   reading order (every TOC entry's heading on its printed page), TOC agreement,
   furniture leaks, hyphenation and private-use residue, and an optional
   EPUB-vs-EPUB reference scorecard.

A conversion is done when the build ends `epubcheck: clean` and QA ends
`Overall: PASS`.

## Commands

```bash
~/pyenv/bin/pdf2epub init  books/<slug>/package --workspace books/<slug>
~/pyenv/bin/pdf2epub build books/<slug>/book.yaml [--upto extract|flow|map|images|xhtml] [--dump-ir]
~/pyenv/bin/pdf2epub qa    books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml [--reference <epub>]
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
