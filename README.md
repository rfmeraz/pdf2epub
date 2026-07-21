# pdf2epub

Convert a print-oriented book PDF into a validated, reflowable EPUB 3 with a
hyperlinked table of contents. The PDF is the sole input; the pipeline does not
require an InDesign project, publisher source files, or Adobe software.

## The problem

A print-oriented PDF places letters at fixed coordinates on fixed-size pages and
carries almost none of the structure a reflowable ebook needs: no paragraphs, no
heading levels, no notion of a footnote or a poem or a table. (Some PDFs include
bookmarks or internal links, which the pipeline uses when present, but those do not
describe the body text.) That structure has to be recovered — and books typeset by
different houses in different decades hide it differently, so no single fixed rule
set handles every book.

pdf2epub's answer is to separate the judgment calls from the mechanism. Mechanical
steps do everything reproducibly; an AI agent makes only the structural judgments,
every one written down in a single reviewable file (`book.yaml`); and multiple
independent checks catch what any single reading of the PDF would miss.

## How it works, step by step

1. **Read the PDF twice** (`init`). One tool (PyMuPDF) pulls out every piece of
   text along with its font, size, style, and exact position on the page, plus the
   PDF's bookmarks, internal links, and page numbering. A second, independent tool
   (poppler) reads the same pages. The two outputs are compared page by page, and a
   page whose two readings disagree materially (a similarity score below 90) is
   flagged as "extraction is uncertain here" for the agent's render-review queue,
   rather than silently trusting either one. A page is left unscored only when both
   readings contain fewer than 40 characters — that little text scores too noisily
   to compare.

2. **Gather evidence about the book's design** (`init`, continued). An analysis
   step groups the text by font and size (body text tends to be one cluster,
   chapter titles another, footnotes a third), detects repeating page decorations
   like running headers and page numbers, locates the printed table of contents and
   cross-checks it against the bookmarks, finds where footnotes sit on each page,
   and counts unusual characters (like custom honorific symbols). This is all just
   evidence — no decisions yet. It lands in `analysis/`, next to a draft
   `book.yaml`. (Optionally, `--layout` adds a vision layout model as a third,
   advisory witness for tables and figures.)

3. **An AI agent decides what the book's structure is.** This is the one judgment
   step. A conversion agent (Claude, via the `/convert-pdf` skill) reads the
   evidence and the rendered page images and decides things like: this font cluster
   means "chapter title," the real book starts on page 9, footnotes are marked with
   asterisks, this block is poetry, the index is set in two columns, this image is
   the cover. Every single decision is written into `book.yaml`. Nothing downstream
   guesses — it only applies what is recorded there, so a person can review or
   override any decision in one place.

4. **Rebuild the text as a book, not pages** (`build`). Using those recorded
   decisions — and no further judgment — the build strips page headers and footers,
   pulls footnotes out of the page flow, and joins lines back into paragraphs:
   removing end-of-line hyphens, repairing spaces the PDF lost, reattaching
   decorative first letters, and stitching paragraphs that continue across page
   breaks. It classifies special blocks (poems keep their line breaks, indented
   quotations become real quotations, numbered entries become real lists), puts
   two-column sections back into reading order, ships true tables and diagrams as
   cropped images with agent-written descriptions, rebuilds the table of contents
   as live links, and drops an invisible anchor where each print page began, so
   page references still work.

5. **Write the EPUB** (`build`, continued). The cleaned-up structure is turned into
   standard web-style chapter files with matching styles, a navigation menu, and
   open-licensed fonts (never fonts copied from the PDF), then zipped into an EPUB.
   This step is fully deterministic — the same PDF and the same `book.yaml` always
   produce the byte-identical file. Anything ambiguous along the way is written to
   `build/warnings.md` as a coded queue with ready-to-paste fixes — content is
   never dropped silently.

6. **Check it automatically** (`qa`). The EPUB is run through a battery of
   automated gates (26 of them), starting with the standard validator (epubcheck)
   and mostly comparing the finished book back to an independent extraction of the
   PDF — a separate witness, not the converter's own output. Every gating check that
   applies to the book must pass; a few checks are advisory, or run only when the
   feature they cover is present. Is every page's text present, in order, and
   nowhere duplicated? Do headings, italics, and centered lines match the print
   typography? Did footnotes land where they should? Is every image intact (each
   shipped figure is compared against a re-render of its source region)? Did poems
   keep their line breaks (a loss character-counting cannot see)? The page-by-page
   fidelity check grades the ordinary body text; the printed table of contents and
   figure images fall outside it and are covered by their own dedicated gates. Pages
   where the two extraction engines disputed each other are also excluded from
   fidelity scoring — neither reading is trustworthy ground truth there — and are
   instead reported for render review and adjudication; an advisory check lists any
   such page that lacks a machine-checkable defense (a per-page assertion or figure
   treatment), but QA can pass with those still open. An accessibility gate checks
   readiness — alt-text coverage, accessibility metadata, and (when the Ace by DAISY
   tool is available) its critical and serious findings — which is a floor that does
   not by itself establish screen-reader readiness or replace a manual review. The
   build's own warnings are policed too: those that carry a real content risk, and
   any stale adjudications, must be resolved or the gate fails (purely advisory
   warnings need not be). A domain gate even validates a "Qurʾānic verses cited"
   index against the Qurʾān's fixed structure. `qa --visual` adds side-by-side
   print-vs-EPUB contact sheets for grading by eye, and `--reference <epub>` scores
   against a known-good EPUB.

7. **Have it actually read** (`proofread`, mandatory). Finally, "blind reader"
   agents — who never saw the PDF — read the finished EPUB in chunks and report
   anything that reads wrongly: a garbled word, a missing space, a paragraph that
   stops mid-sentence, a poem flattened into prose. Each report is verified against
   images of the printed page. Real problems are fixed by changing `book.yaml` or
   the pipeline code and rebuilding — the book's words are never hand-edited — and
   the changed sections are re-read until a pass comes back clean.

A conversion is done when the build ends `epubcheck: clean`, QA ends
`Overall: PASS`, and the proofread loop ends with no new confirmed findings (or the
remainder is escalated in a handoff report). The human's whole role: drop in the
PDF, start the conversion, and inspect the finished EPUB in a reader — every
judgment in between is the agent's, recorded in `book.yaml`.

## Running it

Drop the PDF at `books/<slug>/package/` (and separate cover art, if any, at
`books/<slug>/assets/`), then run the stages in order:

```bash
~/pyenv/bin/pdf2epub init  books/<slug>/package --workspace books/<slug>
~/pyenv/bin/pdf2epub build books/<slug>/book.yaml [--upto extract|flow|map|images|xhtml] [--dump-ir]
~/pyenv/bin/pdf2epub qa    books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml [--reference <epub>] [--visual]
~/pyenv/bin/pdf2epub proofread books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml
~/pyenv/bin/pdf2epub lines books/<slug>/book.yaml <page> [--render]   # raw line indexes, for overrides
~/pyenv/bin/pdf2epub corpus [--only <slug>] [--upto flow] [--strict]  # rebuild+QA every tracked book; byte-compare shipped EPUBs
bash scripts/bootstrap.sh   # one-time setup: pip deps, epubcheck jar, fonts
```

In practice the whole flow is driven by asking the conversion agent to "build the
epub for books/<slug>" — the commands above are what it runs on your behalf. Between
`init` and `build`, editing `book.yaml` is how you correct or override any judgment.

## Under the hood

**Everything is files.** Each command reads and writes concrete artifacts under
`books/<slug>/`, and `book.yaml` is the seam between the deterministic stages and the
agent's judgment:

```
  package/*.pdf
      │  init       ── deterministic: extract + analyze the PDF
      ▼
  analysis/   +   book.yaml (draft)      evidence, and a first-guess config
      │
      │  ← the AGENT reads the evidence + page renders and fills in book.yaml
      ▼
  book.yaml (final)                       every judgment about this book, in one file
      │  build      ── deterministic: (PDF + book.yaml) → EPUB, same bytes every time
      ▼
  build/<slug>.epub   build/warnings.md   build/ir/*.json (with --dump-ir)
      │  qa          ── deterministic: 26 gates vs an independent poppler extraction
      │  proofread   ── deterministic packets → the AGENT reads them for damage
      ▼
  epubcheck: clean  +  Overall: PASS  +  clean read  →  done
```

**Inside `build`** is a fixed internal pipeline —
`extract → flow → map → images → xhtml → package` (`--upto <stage>` stops early;
`--dump-ir` writes each stage's intermediate representation to `build/ir/` so you can
see exactly where a change took effect):

1. **extract** — PyMuPDF reads the PDF into typed page/line/span objects (text with
   font, size, and position), each page cross-scored against a poppler extraction.
2. **flow** — the core step: it applies the judgments in `book.yaml` to turn placed
   glyphs into a document — strip furniture, split footnotes, classify verse/quote/
   list blocks, join lines into paragraphs (dehyphenation, lost-space repair),
   re-order columns, insert page markers. The output is a typed **FlowDoc**: a flat
   list of blocks (paragraphs, page markers, figures) plus a footnote list.
3. **map** — gives each paragraph its semantic role (h1/h2/body/…) from the font-to-
   role table in `book.yaml`, and tags language runs (e.g. CJK).
4. **images** — rasterizes the cover and any `figure_regions` (true tables and
   diagrams) at the configured DPI.
5. **xhtml** — emits XHTML + generated CSS, builds the navigation document, subsets
   the OFL fonts, then **packages** a byte-reproducible EPUB.

**Where the judgment lives.** Everything *before* `book.yaml` — extract and analyze —
only observes and measures the PDF; it never decides. Everything *after* it — the
whole build and all 26 QA gates — is a pure function of *(PDF, book.yaml)*: same
inputs, same bytes out, no clock, no randomness. So the judgment calls are confined
to one small, human-readable file, written by the agent and open to review. The agent
re-enters only where a program cannot decide — reading the proofread packets and
adjudicating the risky-page warnings; the resulting fixes go into `book.yaml`, or into
the pipeline code when the cause is a general bug rather than a per-book judgment. The
mechanical stages are therefore reproducible and diffable, and every per-book decision
sits in one file.

## Design commitments

- **Never rewrite the book's words.** Only deterministic, counted repairs — line-end
  dehyphenation, lost-space restoration, verified glyph substitution. Anything beyond
  that escalates to a human.
- **Warn loudly, never drop silently.** Unknown constructs and ambiguous calls
  surface in `build/warnings.md` for adjudication.
- **OFL fonts only, from system files.** Fonts are never extracted from the PDF;
  proprietary faces (Minion, Bembo, MS Mincho…) are never embedded.
- **Byte-reproducible builds.** Fixed timestamps, deterministic identifiers, no
  randomness — same PDF + same `book.yaml` = the same EPUB, on the same toolchain.
- **Two extraction witnesses.** PyMuPDF is the primary extractor; poppler
  independently scores every page and supplies the ground truth for the QA coverage
  gate. The two extractions are compared to flag disagreements, never merged to
  produce the text.

## Provenance

The EPUB back-end (`src/pdf2epub/core/`) is forked from the sister project
[idml2epub](../idml2epub), which converts full InDesign packages; per-file provenance
headers name the source commit. The two projects diverge independently by design.
