# Commercial-parity landscape — what production houses ship that we don't

Status: landscape + open-item sketches. This is a POSITIONING map, not a single feature:
it enumerates what commercial ebook-production systems (Newgen, codeMantra/Ingram, Amnet/
ABE, Aptara, Innodata, Lumina) deliver relative to pdf2epub, marks which gaps are already
spec'd elsewhere, sketches the genuinely-open ones, and says what is out of scope by
design. Read it before proposing "we should also do X" — X may already be spec'd, already
built, or deliberately excluded.

**Framing (honest).** On pure *conversion correctness* for print book PDFs — text
fidelity, footnote marker↔note linking, witnessed dehyphenation, page anchors, semantic
verse, byte-reproducibility, a 26-gate QA harness + blind-reader proofread — we are
competitive-to-ahead of commercial practice (their own paid conversions of this corpus
ship the mid-word-gap defects gate 11 catches; see strategic research 2026-07-09). What we
lack is (a) accessibility *certification*, (b) content types we don't reconstruct, (c)
automatic linking beyond footnotes, and (d) output breadth — NOT core text fidelity.

**A fifth category the landscape map missed — reliability substrate (2026-07-12 review).** An
external implementation review read the code and found that several of our *own* trust claims
are unenforced or leaky: the flagship coverage gate is recall-only and cannot fail on a
reordered or duplicated book (its own comment delegates order to a gate that only checks
headings); FILL-ME-IN placeholders and seven config fields load silently despite the promise
that config records applied judgment; builds aren't transactional (an invalid EPUB can sit at
the canonical path); tests aren't hermetic and there's no CI. These aren't parity *features* —
they're the substrate that makes "validated" and "byte-reproducible" true. The review's core
argument is sound and is now reflected below: several reliability/QA-integrity items are
interleaved *ahead* of most remaining features. Details:
[reliability-hardening.md](reliability-hardening.md) (build/test/config/provenance) and
[qa-methodology.md §3](qa-methodology.md) (the page-aligned fidelity gate). Where I diverge
from the review's exact ordering — keeping a11y high rather than demoting it, ranking process
limits low, noting two of its items were already spec'd — is argued in the ranking notes.

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

Remaining open items — **re-ranked 2026-07-12 to interleave reliability/QA-integrity ahead of
most features** (external implementation review; see the "fifth category" framing above). The
review's ordering is adopted where its argument is strong and adjusted where I disagree; the
`[R]` reliability items live in [reliability-hardening.md](reliability-hardening.md), `[Q]` in
[qa-methodology.md](qa-methodology.md), `[F]` are features.

**SHIPPED 2026-07-12** (Tier 0 + most of Tier 1): config integrity (0a), test hermeticity (0b),
transactional builds + provenance (0c/3), the page-aligned **fidelity gate 25** (Tier 1 #1),
the **a11y readiness gate 26** (Tier 1 #2, automated portion — manual certification still
deferred), CI + markers + hashed lockfile + ruff (Tier 1 #3), and the config validator +
identity/revision metadata (Tier 1 #4). Corpus re-shipped: all six EPUBs rebuilt, `Overall:
PASS`. Still open below: a11y **manual certification** + `conformsTo`; §6 body cross-refs;
typogrify-lite; the PDF-era census (ocr-witness step 1); process limits (§5); tables/RTL/math.

**Tier 0 — cheap correctness fixes, do first (each ~hours, they're effectively bugs):**

0a. `[R]` **Config integrity** ([reliability-hardening.md §1](reliability-hardening.md)) —
    enforce FILL-ME-IN (the promise at `initcmd.py:5` is currently a lie; 3/5 tracked drafts
    load with `title: FILL-ME-IN`), and reject/remove the seven dead config fields. Protects
    the "config = applied judgment" doctrine directly; near-free. *Ranked above the review's
    #4 placement because it's cheap and strikes at a core doctrine.*
0b. `[R]` **Test hermeticity** ([reliability-hardening.md §4](reliability-hardening.md)) —
    drop the `idml2epub` sibling-repo import in `test_lang.py:35`; fix `test_cdp.py` to skip on
    Chrome *launch* failure, not just absence. Two isolated bug-fixes; the CI/lockfile buildout
    (same §) is the larger follow-on in Tier 1.
0c. `[R]` **Transactional build** ([reliability-hardening.md §2](reliability-hardening.md)) —
    package to a temp path, `os.replace` only after epubcheck passes. Small; stops an invalid/
    stale EPUB from sitting at the canonical path.

**Tier 1 — top substantive items, ahead of new features:**

1. `[Q]` **Page-aligned fidelity gate** ([qa-methodology.md §3](qa-methodology.md)) — the
   review's "priority zero", and I agree it's the #1 substantive item. Recall+precision+order+
   duplication over the existing page anchors; folds in the disputed-page machine-defense
   requirement (66k/27k/13.6k chars currently defended by one heading assertion). Cheap
   (anchors exist), and it closes a hole in the project's central "validated" claim — a gate
   that can't fail on a duplicated book is false assurance.
2. `[F]` **A11y — automated readiness gate** ([semantic-polish.md #2](semantic-polish.md)) —
   **kept high, NOT demoted to the review's #5.** It has an external legal forcing function
   (EU Accessibility Act in force 2025-06-28) and is ~80% built; the Ace gate + alt-coverage +
   metadata is small. Refinement adopted from the review: ship *automated readiness* now but
   assert `dcterms:conformsTo` ONLY behind a recorded *manual* certification (Ace can't verify
   WCAG alone) — so this splits into a near-term gate (here) and a later certification workflow.
3. `[R]` **CI + test tiers + lockfile + provenance manifest** ([reliability-hardening.md
   §4](reliability-hardening.md), [§2](reliability-hardening.md)) — the substrate that keeps
   items 0–2 from silently regressing, plus the `{slug}.manifest.json` the byte-reproducible
   claim implies. Medium effort; foundational.
4. `[R]` **Config validator + schema_version + package identity/revision metadata**
   ([reliability-hardening.md §1](reliability-hardening.md), [§3](reliability-hardening.md)) —
   `pdf2epub config validate`; persistent book identifier (not slug-derived UUID);
   `dcterms:modified` from a release epoch, not the print year. Incremental on the existing
   parser — explicitly NOT a Pydantic rewrite.

**Tier 2 — features & continuous quality:**

5. `[R]` **PDF-era / font / ToUnicode pathology census** — the review's "cheap census"; note
   it is **already spec'd as [ocr-witness.md](ocr-witness.md) step 1** (pure metadata reading,
   always-on). Pull it forward independently of the OCR witness: cheap legacy-backlist
   insurance, a fact on page one of the structure report.
6. **Broader holdout corpus + aggregate quality metrics** — build/QA more real titles, track
   aggregate fidelity over time; continuous, medium value.
7. `[F]` **§6 body cross-references** — auto-link "see p. N" / "fig. 3" / "ch. 2"; the cheapest
   open *feature*, reusing the exact `RunFormat.link → resolve_crossref_links` chain the index
   locators now use (high-precision, per-book opt-in, WARN-and-skip the rest). Below the
   QA-integrity + a11y items because it's additive polish, not a trust fix.
8. `[F]` **typogrify-lite** ([semantic-polish.md #3](semantic-polish.md)) — opt-in
   presentation polish (word-joiners around em-dashes, hair spaces between adjacent quotes);
   small, self-contained, insertion-only of invisible codepoints.

**Tier 3 — demand-driven / conditional:**

9.  `[F]` **§1 tables** / **§3 RTL layout** — backlist-driven: tables if the books have them;
    RTL only for a genuinely non-romanized Arabic title (today a `rtl-live-text` hard stop).
10. `[R]` **External-process resource limits** ([reliability-hardening.md
    §5](reliability-hardening.md)) — **ranked low, deliberately below the review's implicit
    placement.** It's threat-model-conditional (today's workflow is a *trusted* dropped PDF),
    and the Chrome/CDP path the review flagged is *already* bounded — only three `subprocess.run`
    sites are unbounded. Do it when untrusted/batch intake becomes real.
11. `[F]` **§2 math** / **§4 CJK vertical writing** / **guarded `verified-ocr` source mode**
    ([ocr-witness.md](ocr-witness.md)) / **EPUB2 / FXL** — documented non-goals until a title
    forces them.

**Cross-cutting (not a numbered slot):** the maintainability extraction
([reliability-hardening.md §6](reliability-hardening.md)) — flowbuilder/emitter/config/QA-runner
concentration — is gated on characterization tests (Tier 1 item 3) and done *alongside* the
first big content feature, never as a standalone rewrite.
