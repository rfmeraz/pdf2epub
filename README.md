# pdf2epub

Convert a print-oriented book PDF — the only input — into a validated, reflowable
EPUB 3 with a hyperlinked table of contents. No InDesign, no source files, no
Adobe products.

## The problem, and the approach

A print PDF has no structure. It is a set of glyphs placed at fixed coordinates on
fixed-size pages: no paragraphs, no heading levels, no notion of a footnote or a
poem or a table. A reflowable EPUB needs all of that recovered — what is a heading,
where a paragraph actually breaks, which lines are a footnote, which are verse, what
reading order a two-column index has. Books typeset by different houses in different
decades hide that structure differently, so no single fixed rule set gets every book
right.

pdf2epub splits the job into five stages so the hard part — the judgment calls — is
separated from the mechanism, written down, and checked:

1. **Extract + analyze** (deterministic) — read the PDF and gather evidence.
2. **Infer the structure** (the agent) — read the evidence, look at the pages, and
   record every judgment in one file, `book.yaml`.
3. **Build** (deterministic) — turn *(PDF + book.yaml)* into an EPUB, the same way
   every time.
4. **QA** (deterministic) — grade the EPUB against an independent extraction of the
   same PDF.
5. **Proofread** (the agent) — read the finished book for damage a machine can't
   judge.

The human drops the PDF, kicks the conversion off, and inspects the finished EPUB;
every judgment in between is the agent's, recorded in `book.yaml` where a person can
review or override it.

Because every judgment lives in `book.yaml`, a build is reproducible and auditable:
you can see exactly why the converter did what it did, and change any decision in one
place.

## The stages in detail

**1. `init` — extract and analyze.** Reads the PDF with PyMuPDF: text spans with
their font, size, style, and position (clipped to the trim box), plus bookmarks,
internal links, and page labels. Every page is independently re-read with poppler and
the two extractions are scored against each other — a disagreement flags the page for
review, but the engines never vote on the text. From this it derives evidence: font
clusters with proposed roles (heading, body, footnote…), running-head and
page-number furniture, footnote regions, the printed table of contents cross-checked
against the bookmarks and link targets, a census of special (private-use) glyphs, and
page thumbnails. It writes `analysis/structure_report.md` and a draft `book.yaml`.
(Optionally, `--layout` adds a vision layout model as a third, advisory witness for
tables and figures.)

**2. The agent infers the structure.** A conversion agent (Claude, via the
`/convert-pdf` skill) reads the evidence, looks at the page renders, and fills in
`book.yaml`: which font cluster is which heading level, where the front matter ends,
which table-of-contents source to trust, how footnotes are marked, what each
private-use glyph means, where verse and block quotes and lists sit, which pages are
multi-column, what the cover is. This inference step is the point of the design — it
is where the real, book-specific judgment gets made once and written down, so the
build that follows can be purely mechanical.

**3. `build` — deterministic assembly.** From *(PDF + book.yaml)*, with no further
judgment, the build:

- strips running heads and page numbers, and splits footnotes off the body;
- classifies semantic blocks from the geometry recorded in `book.yaml` — **verse**
  (print line breaks preserved as real lines, shipped as `z3998:verse`), **block
  quotes** (justified inset blocks become real `<blockquote>`s), and **lists**
  (marker lines become real `<ol>`/`<ul>`);
- joins the remaining lines into paragraphs, repairing line-end hyphenation, drop
  caps, and spaces lost at run seams;
- re-orders multi-column back matter (indexes and similar apparatus) into reading
  order;
- ships true tables and diagrams as cropped images with agent-written alt text;
- marks every printed-page boundary and rebuilds the table of contents with live
  links;
- emits XHTML + CSS, subsets OFL fonts, and packages a byte-reproducible EPUB.

Anything ambiguous is written to `build/warnings.md` as a coded, severity-ranked
queue with ready-to-paste fixes. Nothing is ever silently dropped, and judgments
already recorded in `book.yaml` resolve their own warnings.

**4. `qa` — automated grading (23 gates).** The EPUB is checked against an
independent poppler extraction of the same PDF, so QA measures the conversion, not
the converter's own guesses. The gates cover:

- **Validity** — epubcheck passes.
- **Text** — every word of the source is present; no garbled characters, no leaked
  furniture, no lost spaces at note markers.
- **Structure** — footnotes land correctly, navigation and reading order hold (each
  table-of-contents entry's heading is on its printed page), and verse keeps its line
  breaks (the one loss that presence-of-text checks can't see — a flattened poem
  loses no characters, only its shape).
- **Fidelity** — the shipped CSS and markup match the source geometry: headings are
  typographically real, emphasis is conserved, centering is genuine, and each page's
  block signature matches print.
- **Images** — every shipped figure perceptually matches a re-render of its source
  region (a blank or corrupt image is content loss no text gate would catch).
- **Adjudication** — the build fails if any risky-page warning went unaddressed, so
  `Overall: PASS` certifies the warning queue was actually cleared.

A domain gate also validates a shipped "Qurʾānic verses cited" index against the
Qurʾān's fixed structure. `qa --visual` adds side-by-side print-vs-EPUB contact
sheets for an agent to grade by eye, and `--reference <epub>` scores against a known-
good EPUB.

**5. `proofread` — reading QA (mandatory).** The finished EPUB is re-rendered as
per-section reading packets. An agent fans out one blind reader per packet, hunting
for damage a gate can't judge — fused or split paragraphs, missing spaces, garbled
words, flattened verse — verifies every finding against the print render, and fixes
accepted ones only through `book.yaml` or code, never by editing text. Rebuild and
re-read the changed sections until a pass comes back clean.

A conversion is done when the build ends `epubcheck: clean`, QA ends `Overall:
PASS`, and the proofread loop ends with no new confirmed findings (or the remainder
is escalated in a handoff report).

## Running it

Drop the PDF at `books/<slug>/package/` (and separate cover art, if any, at
`books/<slug>/assets/`), then run the stages in order:

```bash
~/pyenv/bin/pdf2epub init  books/<slug>/package --workspace books/<slug>
~/pyenv/bin/pdf2epub build books/<slug>/book.yaml [--upto extract|flow|map|images|xhtml] [--dump-ir]
~/pyenv/bin/pdf2epub qa    books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml [--reference <epub>] [--visual]
~/pyenv/bin/pdf2epub proofread books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml
~/pyenv/bin/pdf2epub lines books/<slug>/book.yaml <page> [--render]   # raw line indexes, for overrides
bash scripts/bootstrap.sh   # one-time setup: pip deps, epubcheck jar, fonts
```

In practice the whole flow is driven by asking the conversion agent to "build the
epub for books/<slug>" — the commands above are what it runs on your behalf. Between
`init` and `build`, editing `book.yaml` is how you correct or override any judgment.

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
- **Two extraction witnesses.** PyMuPDF is the spine; poppler independently scores
  every page and grounds the QA coverage gate. Engines witness the text; they never
  co-author it.

## Provenance

The EPUB back-end (`src/pdf2epub/core/`) is forked from the sister project
[idml2epub](../idml2epub), which converts full InDesign packages; per-file provenance
headers name the source commit. The two projects diverge independently by design.
