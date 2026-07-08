---
name: convert-pdf
description: Autonomously convert a print-oriented book PDF (the only input — no InDesign, no source files) to a validated reflowable EPUB using the pdf2epub pipeline, inferring the book's structure from analyzer evidence and page renders, recording every judgment in book.yaml, and escalating only the hard-stop list. Use when asked to convert a PDF to an EPUB or run the pdf2epub pipeline.
---

You are the structure-inference agent this pipeline was designed around. The
extractor and analyzer produce deterministic evidence; only you can LOOK at
page renders and decide what the book's structure IS. Every judgment you make
goes in book.yaml — the build must stay a pure function of (PDF, book.yaml).
Work fast and autonomously; ship with safe defaults + handoff flags instead of
blocking. Python via `~/pyenv/bin/` only.

## Step 1 — Archive & init

- Copy the source PDF into `books/<slug>/package/` (the repo is the archive of
  record; treat the original as read-only). Provided cover art → `books/<slug>/assets/`.
- `~/pyenv/bin/pdf2epub init books/<slug>/package --workspace books/<slug>`
- Read `analysis/structure_report.md` COMPLETELY. `cp book.yaml book.draft.yaml`
  (the draft-vs-final diff feeds the refinement loop).

## Step 2 — Infer the structure (the judgment pass)

LOOK at renders with the Read tool (`analysis/pages/p####.png`, thumbnails in
`analysis/thumbs/`). Never decide a visual question from text evidence alone.

- **Metadata (JP-P5)**: read the title/copyright page renders; fill title,
  creators (marc roles: aut/trl/edt), publisher (from the copyright page — no
  default), language, print ISBN, date. Ebook ISBN: never invent; leave empty
  (urn:uuid ships, flagged). Cover: confirm the proposal by eye — render page,
  provided art, or `cover_synthesize: true` (flagged).
- **Pages (JP-P2)**: confirm cover/front/body/back ranges against thumbs; check
  the folio-vs-label agreement number and mismatch list; set `label_source`
  and any `label_overrides`. Add `role_overrides` for title/copyright pages.
- **Styles (JP-P1)**: review every non-high-confidence cluster row against its
  sample text and a page render. Map EVERY cluster the report lists (unmapped
  pstyles warn at build). Small-caps or symbol fonts → `charstyles`. Then set
  `fail_on_unmapped: true`.
- **TOC (JP-P3)**: cross-check the three witnesses (outline | printed parse |
  link targets). Choose `source`; verify 2-3 disagreements by LOOKING at the
  target pages. Set `nav_depth` to the printed TOC's real hierarchy.
- **Footnotes (JP-P4)**: check the marker census + region samples against one
  page render; set policy/marker.
- **Glyphs (JP-P6)**: for EACH pua_map FILL-ME-IN, open the sample-page render,
  identify the glyph (honorifics: ﷺ=U+FDFA, ﷻ, ؓ etc.), set
  `{action: char, char: "...", lang: ar, note: "verified on p.N render"}` or
  `{action: drop}` for pure ornaments. Add `gt_strip_phrases` for the poppler
  ToUnicode readings of those glyphs (QA's missing-segment list reveals them,
  e.g. "May God be pleased with him"). A glyph you cannot identify from the
  render is a HARD STOP.
- **Fonts (JP-P7)**: OFL system files only, never from the PDF. Honorific
  chars → Amiri (script: cjk, lang: ar). Live CJK → Noto Serif CJK. No Latin
  embed by default.
- **Figure pages (JP-P4b)**: vertical-CJK/art pages from the proposal →
  `images.figure_pages` with real alt text (LOOK at the renders). Image-only
  pages you can verify from renders ship as figures with alt; unverifiable
  content is a HARD STOP.
- Finish: `fail_on_unmapped: true`, `fail_on_unmapped_pua: true`.

## Step 3 — Build → QA → adjudicate → iterate (≤8)

- `~/pyenv/bin/pdf2epub build books/<slug>/book.yaml` must end `epubcheck: clean`.
- `~/pyenv/bin/pdf2epub qa books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml`
  (add `--reference <epub>` when a benchmark exists) must end `Overall: PASS`.
- Work `build/warnings.md` to zero-or-explained: LOOK at the page render for
  each entry, then fix via config or a `flow.overrides` entry ({page, line
  (RAW extract index), action, note}) — config fixes preferred; a code fix
  requires a unit test. Gate 2's missing-segment list is the real audit:
  every segment must be explainable (two-column index pages, glyph readings,
  dropped ornaments) or it's stop-the-line.
- Known judgment patterns: two-column index/back matter → exclude those pages
  (`pages.exclude`) with a note, or accept interleaved order explicitly;
  9-10pt block quotes near footnote regions → check gate 3 counts; folio
  offsets → `label_overrides`.

## Step 4 — Visual QA (you are the proofreader; the tool builds your desk)

- Run `~/pyenv/bin/pdf2epub qa <epub> --config <book.yaml> --visual`. Gate 18
  samples 10-20 pages (every pstyle cluster, drop caps, PUA glyphs, figures,
  disputed pages, seeded-random) and writes `build/qa_visual/`: side-by-side
  contact sheets (print LEFT, EPUB slice RIGHT), PUA glyph crop pairs, figure
  dHash verdicts, and `manifest.md` — your grading sheet.
- Read `build/qa_visual/manifest.md`, then Read EVERY `sheets/p####.png` and
  grade each checklist item against the print panel (content may start/end
  mid-paragraph — grade typography and presence, not pagination). Read every
  `glyphs/u*.png` pair (source glyph vs substituted reading). Any figure
  `review` verdict: open its pair image.
- A failed checklist item is stop-the-line, same as a gate-2 missing segment:
  fix via config or a flow.override, rebuild, re-run.
- Manual probes the tool cannot do: tap-test three deep TOC entries in a
  reader; page-list spot-check against two known printed pages.

## Step 5 — Ledger, commit, handoff

- Append a CONVERSIONS.md entry: date, source sha256, decisions worth
  remembering, QA outcome, lessons.
- Commit the workspace INCLUDING the built .epub; no AI-attribution trailers.
- Handoff report listing every flagged autonomous decision (uuid identifier,
  cover provenance, excluded pages, notable overrides) so a human can
  overrule AFTER the fact.
- Refinement loop: a correction made in two books becomes a heuristic; a
  misfiring heuristic becomes a code fix + unit test; update NOTES.md.

## Hard stops (never decide alone)

Rewriting or inventing the book's words (beyond the deterministic textfix
rules); embedding non-OFL fonts; live RTL text runs; true tables; multi-column
BODY text (index/back-matter columns may be excluded with a note instead);
image-only pages whose content you cannot verify from renders; any glyph
unidentifiable from its render.
