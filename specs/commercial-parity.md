# Commercial-parity landscape — what production houses ship that we don't

Status: landscape + open-item sketches. This is a POSITIONING map, not a single feature:
it enumerates what commercial ebook-production systems (Newgen, codeMantra/Ingram, Amnet/
ABE, Aptara, Innodata, Lumina) deliver relative to pdf2epub, marks which gaps are already
spec'd elsewhere, sketches the genuinely-open ones, and says what is out of scope by
design. Read it before proposing "we should also do X" — X may already be spec'd, already
built, or deliberately excluded.

**Framing (honest).** On pure *conversion correctness* for print book PDFs — text
fidelity, footnote marker↔note linking, witnessed dehyphenation, page anchors, semantic
verse, byte-reproducibility, a 24-gate QA harness + blind-reader proofread — we are
competitive-to-ahead of commercial practice (their own paid conversions of this corpus
ship the mid-word-gap defects gate 11 catches; see strategic research 2026-07-09). What we
lack is (a) accessibility *certification*, (b) content types we don't reconstruct, (c)
automatic linking beyond footnotes, and (d) output breadth — NOT core text fidelity.

## Capability map

| Capability | Commercial | pdf2epub today | Where |
|---|---|---|---|
| Text fidelity, dehyphenation, lost-space repair | yes | yes (witnessed, gated) | shipped — often ahead |
| Footnote/endnote marker↔note linking + backlinks | yes | yes | shipped |
| Semantic verse / blockquote / list | partial | yes (block grammar) | shipped |
| Print page anchors + page-list nav | yes | yes | shipped |
| Furniture strip, column reading-order | yes | yes | shipped |
| **A11y CERTIFICATION** (`conformsTo`, Ace/DAISY, alt-text coverage) | yes | metadata only, no claim/gate | **[semantic-polish.md #2](semantic-polish.md)** |
| Index locator hyperlinking | yes | yes (opt-in, DAISY-container) | shipped (2026-07-11) |
| Site-specific regression tripwires (per-page assertion cells) | ad hoc / manual re-read | yes (gate 24) | shipped — **[qa-methodology.md #1](qa-methodology.md)** |
| Scanned / image-only pages (OCR) | yes | detect + escalate, no OCR | **[ocr-witness.md](ocr-witness.md)** |
| Arabic-script font coverage (honorifics) | yes | pairing spec'd | **[arabic-fonts.md](arabic-fonts.md)** |
| **Tables** → reflowable `<table>` | yes | flatten to prose (structure-loss) | **OPEN — §1** |
| **Math** → MathML | yes (STEM houses) | none (image/garble) | **OPEN — §2 (hard)** |
| **RTL / bidi LAYOUT** | yes | detect + hard-stop escalate | **OPEN — §3** |
| **CJK vertical writing / ruby** | yes | lang-tag only | **OPEN — §4 (low)** |
| **Output breadth** (Kindle/AZW3, FXL, EPUB2) | yes | +Kindle AZW3 (`pdf2epub kindle`); FXL/EPUB2 out | **§5 (Kindle shipped 2026-07-11)** |
| **Body cross-refs** ("see p. N", "fig. 3", "ch. 2") | yes | page anchors, no auto-link | **OPEN — §6** |
| ONIX 3.0 / BISAC-Thema / retail feed | yes | basic OPF DC only | out of scope (§7) |
| Per-retailer lint (Kindle Previewer, Apple assets) | yes | epubcheck only | out of scope (§7) |
| Fixed-layout / children's / art design | yes | reflowable only | out of scope (§7) |
| Scale / SLA / rights / distribution | yes | single-title CLI | out of scope (§7) |

---

## OPEN gaps (not spec'd elsewhere)

The semantic block grammar (verse/quote/list) is the template for §1 and §4: classify a
block shape in `blockshapes.py` BEFORE the join pass, add an IR type in `core/model.py`,
emit in `core/emit_xhtml.py`, gate structure-loss in `qa/`. Follow it.

### §1 Tables → reflowable `<table>`  (priority: medium; corpus-dependent)

**Problem.** Tabular matter has no representation; aligned rows/columns flow into prose
and the proofread taxonomy names it `structure-loss`. Reflowable EPUB wants a real
`<table>` (with `<th>` scope, `role="table"`), not an image.

**Design sketch.** Geometric detector in `blockshapes.py`: ≥2 rows whose runs cluster into
≥2 shared x-bands (column gutters, like `flow.columns` gutter detection) with consistent
row baselines. New `Table` block (rows × cells) in the IR; a per-book `blocks.tables` spec
(page + column x-bands + header-row flag), because auto-detection will misfire on
list/index/verse geometry — same judgment-recorded-per-book doctrine as verse/quote/list.
Emit `<table>`; never rewrite cell text. Non-goal: spanning/nested/rotated tables (WARN +
ship the source page as a figure raster, the image-fallback the pipeline already has).

**Integration**: `blockshapes.py`, `core/model.py` (Table/Row/Cell), `flowbuilder.py`
(classify before join), `core/emit_xhtml.py`, `config.py` (`blocks.tables`), new gate
(cell-count vs source, like gate 23 verse integrity).

### §2 Math → MathML  (priority: low for THIS corpus; genuinely hard)

**Problem.** Equations would ship as images or garbled glyph soup; accessible EPUB wants
MathML. **This is the hardest gap** — PDF math is positioned glyphs with no structure;
reconstructing MathML is a research problem, not a heuristic. Commercial STEM houses
**re-key** math or run specialized math-OCR (Mathpix-class), not a generic converter.

**Design sketch (only if a math-heavy book appears).** Do NOT attempt structural
reconstruction from the glyph stream. Options, cheapest first: (a) detect math regions
(font clusters / operator density) and ship them as cropped rasters with agent-authored
alt text (reuses `figure_regions`); (b) a math-OCR witness (external, like the OCR spec's
third-witness pattern) producing LaTeX→MathML, agent-verified. The corpus (sacred-knowledge
/ humanities) is math-light — keep this a documented non-goal until a title needs it.

**Integration**: `figures.py` (region raster path already exists) for (a); a new witness
module mirroring `ocr-witness.md` for (b).

### §3 RTL / bidi layout  (priority: high IF non-romanized Arabic ships; else deferred)

**Problem.** We DETECT right-to-left script (`core/lang.py`, `_RTL`) and `warnqueue`'s
`rtl-live-text` is a CONTENT_RISK hard-stop — the build refuses to lay out RTL rather than
emit wrong-direction text. `arabic-fonts.md` explicitly leaves "RTL paragraph flow" as an
unchanged hard stop. The corpus is mostly romanized/transliterated Latin (so this rarely
fires), but a genuinely Arabic-script title cannot ship.

**Design sketch.** Per-paragraph base direction from the dominant script of its runs:
`dir="rtl"` + `xml:lang`/`lang` on RTL paragraphs, `dir="auto"` on mixed, wrap
strong-directional inline runs (`<span dir="rtl">`) — the Unicode Bidi Algorithm handles
the rest in the reader. Column reading-order must reverse for RTL spreads. Verse/quote/list
join rules are direction-agnostic (geometry), but indent-side flips. Gate: a bidi-sanity
check (no LTR-punctuation-mirroring defects) + render review. This is a real effort, not a
knob — promote the hard stop to a first-class mode only when a book demands it.

**Integration**: `core/lang.py` (direction classifier alongside script detection),
`core/emit_xhtml.py` (`dir` attrs), `core/emit_css.py` (RTL indent/margin logic),
`flowbuilder.py` (column order), `warnqueue.py` (downgrade rtl-live-text once supported),
`qa/`.

### §4 CJK vertical writing / ruby  (priority: low)

**Problem.** We lang-tag Han/Kana (`cjk_han_only`, `languages.overrides`) but emit only
horizontal LTR; no `writing-mode: vertical-rl`, no ruby annotations. Corpus has occasional
CJK inline (HU foreword) but no vertical-set titles needing it.

**Design sketch.** Detect vertical-set pages (`vertical` flag already on extract lines) →
a `chinese-page`/vertical block already exists as a figure fallback (`Figure.role =
"chinese-page"`); a live-text vertical mode would add `writing-mode` CSS on a per-section
`blocks.vertical` spec. Ruby: `<ruby>`/`<rt>` from base+annotation run pairing (rare).
Keep as documented non-goal until a vertically-set title appears.

### §5 Output breadth  (Kindle SHIPPED 2026-07-11; FXL/EPUB2 remain out)

**Problem.** One deliverable: reflowable EPUB 3. Commercial ships Kindle (AZW3/KF8),
EPUB2 fallback, fixed-layout, tagged PDF from one source.

**Design sketch.**
- **Kindle — SHIPPED** (`src/pdf2epub/kindle.py`, `pdf2epub kindle <epub> [--out]`): our
  EPUB 3 → AZW3 (KF8) via Calibre `ebook-convert`, a thin post-process wrapper that runs
  the external tool and reports path/size/warnings. No pipeline change — the EPUB is the
  source of truth; the `.azw3` is gitignored. Calibre is documented warn-only in
  `bootstrap.sh`; a missing converter is a hard error. Kindle Previewer retail-lint stays
  deferred (its CLI is absent on Linux). Was the highest ROI of this section.
- **EPUB2 fallback:** low value (EPUB3 reader support is universal in 2026); skip.
- **Fixed-layout (FXL):** a genuinely different pipeline (per-page image + text overlay,
  no reflow) for art/children's books — out of scope for the print-reflow mission; note it
  as a separate product if the backlist needs it.

**Integration**: new thin `pdf2epub kindle` subcommand shelling to the external converter;
document the external dependency in `scripts/bootstrap.sh` (epubcheck-jar precedent).

### §6 Body cross-reference linking  (priority: medium; the cheapest open feature — its chain is now proven)

**Problem.** "see p. 42", "cf. figure 3", "as in chapter 2", "→ Glossary" ship as dead
text. Index locators shipped this exact `page:<label>` linking for the back-of-book index
([semantic-polish.md #1](semantic-polish.md), `src/pdf2epub/index_locators.py`); this is the
general in-prose case — the tokenizer/guard/advisory pattern there is the template to copy.

**Design sketch.** A conservative emit/textfix pass detecting *explicit* locator patterns
— `p{p}. \d+`, `pp. \d+[–-]\d+`, `fig(ure)? \d+`, `chapter \d+`/`ch. \d+` — and wrapping
them via the **`RunFormat.link` + `resolve_crossref_links` machinery already built for the
World Wisdom imprint** (`page:<label>` targets resolve to `#pg-N`; figure/chapter targets
resolve to heading/figure ids in the second pass). High precision only: link ONLY exact,
unambiguous references; WARN-and-skip the rest (advisory), never guess. Per-book opt-in
(`flow.crossrefs: true`) since false links are worse than dead text.

**Integration**: `core/emit_xhtml.py` (detector + reuse `resolve_crossref_links`),
`core/model.py` (already has `RunFormat.link`), `config.py` (opt-in flag), `warnqueue.py`
(advisory unresolved code), tests.

---

## §7 Out of scope by design

Not conversion-fidelity gaps — business/scale/breadth concerns a single-purpose pipeline
deliberately excludes:

- **ONIX 3.0 / BISAC / Thema / retail metadata feeds & distribution** — no ONIX feed
  exists for this corpus (semantic-polish.md already notes codelist 196 out of scope). The
  OPF ships correct Dublin Core; ONIX is a publisher-ops layer.
- **Per-retailer ingestion lint** beyond epubcheck (Kindle Previewer, Apple Books asset
  rules) — partially addressable via §5's Kindle wrapper; full retail QA is ops.
- **Scale / SLA / project management / rights clearance / human typesetting staff** — the
  production-house business, not the converter.
- **Multi-source (InDesign/IDML/XML) conversion** — deliberate: PDF is the ONLY input
  here; the sister project `../idml2epub` owns full InDesign packages.

## Priority ranking (for this corpus)

**Shipped 2026-07-11** (were #2 and #4): index locator hyperlinking
([semantic-polish.md #1](semantic-polish.md)) and Kindle AZW3 output (§5). Both reused
existing machinery — the `RunFormat.link → resolve_crossref_links` cross-ref chain, and a
Calibre `ebook-convert` post-process — so neither cost a pipeline change. Earlier waves
shipped the semantic block grammar (verse/quote/list) and the World Wisdom imprint relink.
Also 2026-07-11: **gate 24 per-page regression assertions**
([qa-methodology.md #1](qa-methodology.md)) — every print-verified fix becomes a
`qa_assertions.yaml` tripwire, a QA-only change (shipped `.epub` bytes unchanged) hardening
the corpus ahead of the text-mutating features below.

Remaining open items, re-ranked:

1. **A11y certification** ([semantic-polish.md #2](semantic-polish.md)) — the top open item:
   small, closes a legal/market gap (EU Accessibility Act, in force since 2025-06-28),
   metadata is already ~80% present, and the just-shipped index-locator container
   (`epub:type="index"`) is a down payment on it. Add `dcterms:conformsTo` + an Ace-by-DAISY
   gate.
2. **§6 body cross-references** — auto-link "see p. N" / "fig. 3" / "ch. 2"; the cheapest
   open feature to build because it reuses the *exact* `RunFormat.link → resolve_crossref_links`
   chain the index locators now use (high-precision, per-book opt-in, WARN-and-skip the rest).
3. **typogrify-lite** ([semantic-polish.md #3](semantic-polish.md)) — opt-in presentation
   polish (word-joiners around em-dashes, hair spaces between adjacent quotes); small and
   self-contained, insertion-only of invisible codepoints.
4. **§1 tables** / **§3 RTL layout** — backlist-driven: tables if the books have them; RTL
   only for a genuinely non-romanized Arabic title (today a `rtl-live-text` hard stop).
5. **§2 math** / **§4 CJK vertical writing** — documented non-goals until a title forces them.
