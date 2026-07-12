# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository.

## What this is

A pipeline converting print-oriented book PDFs — the ONLY input; no InDesign, no IDML, no
Links folder — into validated reflowable EPUB 3 ebooks with hyperlinked TOCs. It is a
general-purpose tool (any publisher's PDFs), though the expected corpus skews toward
scholarly/sacred-knowledge books: transliteration diacritics, honorific glyphs, footnote
apparatus, occasional CJK/RTL content. The README is the authoritative process description;
NOTES.md carries engineering lessons and verification baselines — read it before nontrivial
changes and keep it current.

Sister project: `../idml2epub` converts full InDesign packages. This repo FORKED its
back-end into `src/pdf2epub/core/` (see the per-file provenance headers). The projects
diverge by design — never edit idml2epub from here, and apply shared-logic fixes per-repo.

## The canonical process

A human drops a PDF at `books/<slug>/package/` (cover art, if separate, in
`books/<slug>/assets/`), kicks off a conversion ("build the epub for books/<slug>"), and
inspects the finished EPUB in a reader; **every other decision is the agent's**. The
`/convert-pdf` skill (`.claude/skills/convert-pdf/SKILL.md`) is the process definition:
deterministic extract+analyze produce evidence, the agent infers the book's structure
(the AI-agent step: pstyle roles, page ranges, TOC source, footnotes, PUA glyphs, cover,
columned back matter, semantic block shapes such as verse)
and records every judgment in `book.yaml`, then `build` is fully deterministic. After QA,
the mandatory reading-QA step (`/proofread-epub`: blind reader subagents over `pdf2epub
proofread` packets, findings verified against print renders, fixes only via config/code)
must end clean or escalate. Escalate only the skill's hard-stop list; everything else
proceeds with safe defaults + handoff flags.

## Commands

```bash
~/pyenv/bin/pdf2epub init  books/<slug>/package --workspace books/<slug>
~/pyenv/bin/pdf2epub build books/<slug>/book.yaml [--upto <stage>] [--dump-ir]
~/pyenv/bin/pdf2epub qa    books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml [--reference <epub>] [--visual]
~/pyenv/bin/pdf2epub proofread books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml   # reading-QA packets (proofread-epub skill)
~/pyenv/bin/pdf2epub lines books/<slug>/book.yaml <page> [--render]   # RAW line indexes for flow.overrides
~/pyenv/bin/pdf2epub kindle books/<slug>/build/<slug>.epub [--out <path>]   # EPUB -> Kindle AZW3 via Calibre (post-process; optional)
~/pyenv/bin/pytest -q                 # unit tests
bash scripts/bootstrap.sh             # one-time machine setup (pip, epubcheck jar, fonts)
```

A build must end `epubcheck: clean` and `qa` must end `Overall: PASS` before results are
presented as done. Stage snapshots land in `books/<slug>/build/ir/` (stages: extract, flow,
map, images, xhtml); build warnings land in `build/warnings.md` (`warnings.<stem>.md` for
variant configs) as a coded queue with ready-to-paste override/adjudication snippets — the
agent adjudication queue. Judgments recorded in book.yaml auto-resolve their warnings;
the rest need `adjudications:` entries (render-verified notes) or QA gate 22 fails.

## Architecture in one paragraph

`src/pdf2epub/`: `extract/` reads the PDF with PyMuPDF (spans with font/size/flags, TrimBox
clipping, outline, internal links, page labels) and cross-scores every page against poppler
`pdftotext` (engine disagreement = extraction-confidence flag — engines witness, never
co-author). `analyze.py` gathers deterministic evidence (font clusters → pstyles, furniture,
folio-vs-label agreement, TOC witnesses, footnote regions, PUA census, join stats) into
`analysis/` for the agent. `flowbuilder.py` applies the recorded judgments to produce the
typed FlowDoc IR (furniture strip, footnote split, semantic block classification —
`blocks.verse` calibrated indent specs make verse line breaks content: stanza Paragraphs
with U+2028 line separators that bypass the prose joiner, plus an uncalibrated
verse-suspect witness on every build; `blocks.quotes` classifies justified inset blocks
into real coalesced blockquotes, class entry/exit breaking the paragraph;
`blocks.lists` turns marker lines at per-spec entry stops into real ol/ul lists,
entry-break + hang-join healing split/fused apparatus entries —
paragraph join with dehyphenation,
drop-cap reattachment and cross-run lost-space seams, flow.columns re-split of columned back
matter into print reading
order, textfix, printed-TOC rebuild, exact page anchors — inline at the run seam when a
page begins mid-paragraph). `core/` is the
back-end forked from idml2epub: role application, CJK lang tagging, XHTML emitter, synthetic
CSS, nav, OFL font subsetting, deterministic packager, and the EPUB-generic QA gates.
`qa/` runs 26 gates (incl. 11 lost-space, 11b noteref-seam, 19 Qurʾānic-citation validation
against the fixed 114-sura structure, 20 garble residue in shipped text, 21 figure-image
integrity vs re-rendered source regions, 22 warnings-adjudicated — the build's coded
warning queue re-derived via `warnqueue.py`, failing on open content-risk items —
23 verse integrity: the flow's classified verse line count vs shipped `span.vl` spans,
the one structure-loss witness presence-based coverage cannot be; 24 per-book
regression assertions — the tracked `books/<slug>/qa_assertions.yaml` tripwire fixture that
pins every print-verified fix against silent regression, `assertions.py`;
25 page-aligned fidelity (`fidelity.py`) — per-page recall+precision (char-level slices vs
poppler ground truth) + monotonic order + rolling-hash duplication, the gate coverage's
one-directional recall cannot be (it passes a reordered/duplicated book), with 25b an
advisory on engine-disputed pages lacking a machine-checkable defense; and 26 accessibility
readiness (`a11y.py`) — alt coverage + accessibility metadata + Ace-by-DAISY critical/serious,
NOT a conformance claim); text
ground truth is poppler-extracted,
trim-cropped, footnote-stripped page text through the same textfix/normalize chain the flow
used; gates 13-17 grade
typographic fidelity (shipped CSS+markup vs raw extract geometry, sliced per source page via
the pagebreak anchors), and `--visual` (gate 18) emits sampled print-vs-EPUB contact sheets
plus PUA glyph pairs into `build/qa_visual/` for agent grading. `proofread.py` renders the
shipped EPUB as reading-QA packets (+ the `lines` raw-geometry dump) for the mandatory
`/proofread-epub` blind-reader pass — the one reviewer that consults linguistic plausibility,
which no deterministic gate has.

## Conventions and constraints

- Python via `~/pyenv/bin/...` only; install with `~/pyenv/bin/pip`.
- Unknown PDF constructs and ambiguous decisions must WARN loudly, never silently drop
  content; every WARN goes to build/warnings.md for adjudication.
- NEVER rewrite or invent the book's words; deterministic textfix repairs only.
- NEVER embed fonts extracted from the PDF or any proprietary font; OFL from system files only.
- Builds are byte-reproducible: no wall-clock, no randomness in outputs.
- Per-book workspaces `books/<slug>/` (tracked): `package/` archived source PDF, `book.yaml`
  the complete record of judgments (JP-P1..P9), `analysis/` evidence (thumbs/ gitignored),
  `build/` outputs (only the .epub tracked). Treat original PDFs outside the repo as read-only.
- book.yaml unknown keys are build errors; flow.overrides address RAW extract line indexes.
- Commit messages: no AI attribution trailers (user preference).

## Test books

Four books validate the pipeline (see CONVERSIONS.md): book-of-knowledge (bookmark-rich,
PUA honorifics), harmonious-unity (PDF-only rerun of idml2epub's test book — its idml2epub
EPUB is the `qa --reference` benchmark, not an input), islam-and-buddhism (printed-TOC-only,
digit footnotes), me-and-rumi (prepress quirks, lost spaces, asterisk footnotes).
