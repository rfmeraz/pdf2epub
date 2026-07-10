# Conversion ledger

One entry per finished conversion: date, source PDF (sha256), decisions worth remembering,
QA outcome, and anything the next conversion should learn from.

(No conversions yet — the four validation books land here as they finish:
book-of-knowledge, harmonious-unity, islam-and-buddhism, me-and-rumi.)

## sufism-veil-and-quintessence — 2026-07-09

- Source: `Sufism-Veil-and-Quintessence-by-Frithjof-Schuon.pdf` (sha256 5a4c08c2…,
  218 pp, World Wisdom 2006, WorldWisdomFont book face). First non-validation book.
- Result: build `epubcheck: clean`; QA `Overall: PASS` (all 23 gates; coverage
  99.97%, 170/170 footnotes placed, 216-entry page-list). 145 unit tests pass.
- Structure judgments:
  - Metadata off p4/p5 renders: aut Schuon; trl Perry + Lafouge; edt Cutsinger;
    aui Nasr (foreword). Print ISBN 978-1-933316-28-4; no ebook ISBN → urn:uuid
    (FLAG). Cover = render of the designed p1 (Timurid Koran cover art).
  - 39 font clusters mapped (report listed only the top 22); cover-p1 Goudy display
    + back-cover-p218 ACaslon clusters → drop (never flow). Small-caps name heads
    (WorldWisdomFont-Bold-SC8) → charstyle smallcaps.
  - TOC `source: printed` (not outline): the outline OMITS the Appendix
    ("Selections from Letters…" p152); the printed TOC lists it. nav_depth 1.
  - 2-column INDEX (pp.206-213): verso/recto have DIFFERENT binding margins
    (gutter x≈227 vs x≈209) — one `flow.columns` spec smeared the channel, so it
    is split into two margin-consistent specs. Frontispiece portrait p18 →
    `figure_pages` (dHash 1). Back cover p218 excluded (marketing). WoodtypeOrnaments
    rosette divider → drop; Wingdings back-cover bullet → "•". p4 publisher colophon
    adjudicated (embedded-image-uncovered, decorative). Section-break `*` kept
    (furniture.keep — some fall at a page top). Two furniture.extra heads the
    auto-detector missed ("Preface", the long Appendix running head).
- Reading QA + a user-reported section-break inconsistency drove EIGHT code fixes
  (the deterministic gates + sampled visual QA all PASSed a build that was in fact
  riddled with reader-level damage — a third of the book's paragraphs were wrongly
  split; ~412 lowercase-starting <p>):
  - FOOTNOTES (root cause): the digit marker is a SMALLER-font run ('8' at 7pt over
    9pt note text), so the `digit + [.)]/tab/2-space` text pattern never matched →
    `0 notes`; every multi-line footnote shattered per line AND its un-extracted
    lines broke the body paragraphs around them. New `_note_start`/`_note_marker`
    detect a superscript OR smaller-font leading digit; THREE more spots were still
    on the old regex — note-continuation merge (merged 1+2+3 into one note), marker
    capture (fell back to '*' so noterefs didn't attach), and marker STRIP (left the
    printed '1' before the auto-numbered <li> — user-reported) → all re-pointed at
    `_note_start`/`_note_marker`. Result: 0 → 170 clean, linked endnotes.
  - SOFT HYPHENS: MuPDF emits U+00AD at print line breaks; `normalize` strips them
    for the gates but the FLOW shipped 1159, several as a visible "eso­ terism"
    space at line joins. `_apply_textfix` strips embedded/space-seam soft hyphens;
    `dehyphenate_join` closes a trailing one.
  - RECTO/VERSO MARGIN SHIFT: `_break_before`'s "short line" test used the GLOBAL
    modal right edge (381), so full lines on a left-shifted verso page (x0=54, right
    ~360) read as paragraph ends (appendix §12 shattered). Scale the edge by the
    block's own left inset. Same shift broke index-column detection — the gutter
    census now skips furniture (running heads span both columns).
  - LINE-END DASHES: a soft/em/en-dash at a line end is a continuation, not a ragged
    short line (`_CONT_DASHES`); a closed em/en-dash joins without a space.
  - CENTERING vs the same recto/verso shift (user-reported: the `* / * *` section
    breaks were centered on recto pages, flush-left on verso): `line_pstyle` measured
    each line against ONE global body-page center, so a page-centered line on a
    left-shifted verso page missed `/center`. ColumnGeometry now carries a per-page
    shift (computed ONLY from left-aligned prose — >=3 long lines sharing an edge — so
    a fully-centered title page yields none and keeps its own headings centered), and
    line_pstyle + gate 14's witness offset their center/edges by it. Fixed all 34
    left-aligned section breaks AND the copyright page's merged centered lines.
  - QA: `is_endnotes()` replaces the `"notes" in href` heuristic (Editor's/
    Biographical NOTES are body sections, not the endnotes file — they were dropped
    from coverage/typography scope); coverage candidate now includes the notes;
    note excision is per SOURCE page (page-wrapping footnotes) with a hyphen/space
    squeeze match. All fixes carry unit tests.
- FLAGS / escalated to handoff (front-matter paratext + hyphenation cosmetics, all
  low-impact; body + reader nav clean): the "Books by Frithjof Schuon" list (p3) still
  fuses — the per-page centering shift needs left-aligned prose to anchor it and p3 is
  ALL centered display type, so its titles keep the plain (non-center) class and don't
  break; in-body Contents merges the page-number-less
  "Appendix" label onto the previous entry (reader nav is correct); ~6 residual
  hyphenation artifacts (compound hyphens religion-quintessence / vis-à-vis /
  logician-like dropped by lower-only dehyphenation; al-Bātin / Apara-Brahma /
  ʾIhyā— single-run space-after-dash extraction artifacts).

## book-of-knowledge — 2026-07-07

- Source: `adult-The_Book_of_Knowledge_cover and TOC links.pdf` (sha256 48ea4f71…, InDesign CS6/2015, 338 pp).
- Result: build `epubcheck: clean`; QA `Overall: PASS` (coverage 99.06%, 670/670 notes placed, 336-entry page-list, byte-reproducible).
- Judgments worth remembering:
  - 23 Honorifics-font PUA glyphs identified from 350dpi crops against the book's own
    legend (Publisher's Note p.26) and rendered as parenthesized English readings —
    incl. raḥimahu llāh forms the legend omits, dual forms (Ibn ʿAbbās, Ibn Ḥanbal+Sufyān),
    and a full basmala calligraphy line. FLAG: publisher may prefer Arabic glyphs + font.
  - eBook ISBN 978-1-941610-21-3 printed on the copyright page — no uuid fallback needed.
  - Columned back matter flows via `flow.columns` (2026-07-08 rework — the original
    conversion shipped the Qurʾānic Verses Cited pages COLUMN-INTERLEAVED because
    pp.322-323 sat outside the excluded index range, and gate 2 was blind there:
    engine-disputed pages leave the coverage ground truth; user-reported): 3-col
    Qurʾānic index pp.322-323 + 2-col general index pp.324-336, both verified against
    print renders; gate 19 now validates the Qurʾānic citations structurally. Only the
    image-only closing page 338 stays excluded.
  - 4 flow.overrides: hanging-indent turnovers (numbered list + Qurʾān quotes) the indent
    rule misread as paragraph starts.
  - Publisher's Note glyph legend (p.26) is a TRUE 3-column table — shipped scrambled by
    the line flow until 2026-07-09 (user-reported; presence-based coverage cannot see
    ordering damage). Now `images.figure_regions`: cropped raster + full alt, region text
    excised from gt. Applies to both variants.
  - ARABIC-GLYPH VARIANT (2026-07-09, user-requested): `book.arabic.yaml` →
    `build/book-of-knowledge-arabic.epub`, same judgments with pua_map rendered as Arabic
    (U+FDFA/U+FDFD ligatures + spelled honorific phrases, lang: ar) and an embedded OFL
    Amiri subset (48KB). epubcheck clean, qa Overall: PASS (coverage 99.08%). The map
    stage's RTL escalation warning is ADJUDICATED for this variant: inline-only
    strong-RTL runs, bidi-verified on Chrome renders (ﷺ placement, multi-word phrase
    order, basmala line). The English-readings EPUB remains the default deliverable.
- Lessons promoted: coverage/gt reconciliation for glyph substitutions and renumbered
  noterefs; note regions must start at a marker line (9pt block quotes); first-line indent
  is relative to the previous line (drop-cap wraps); visual verification of PUA glyphs via
  tight high-dpi crops is cheap and decisive.
- Visual QA: text probes all pass (honorifics, dehyphenation, drop caps, basmala, deep TOC,
  page-list). Reader-app spread comparison deferred to human inspection. FLAG.

## harmonious-unity — 2026-07-07 (PDF-only benchmark)

- Source: `Harmonious Unity EBOOK.pdf` (InDesign 20.5/2026, 152 pp) — ONLY the print
  PDF; the idml2epub EPUB of the same book served purely as the `qa --reference`
  scorecard. Result: `epubcheck: clean`; QA `Overall: PASS` (coverage 99.92%,
  152-entry page-list, byte-reproducible). Scorecard vs the IDML-derived EPUB:
  118 vs 88 semantic headings (finer chapter nav), text parity.
- Judgments: outline TOC (70 bookmarks, three witnesses agree); vertical Chinese
  source text (pp.79–145) as figure pages with per-page alt (mirror-bound section
  reads back-to-front in physical order — same known limitation as the reference;
  FLAG); five-pillars calligraphy plate (p.33) as figure with descriptive alt;
  Noto Serif CJK SC subset embedded for inline CJK (MS Mincho/Arial Unicode are
  proprietary); SYNTHESIZED typographic cover (the PDF carries none; the reference
  used cover art from the manual EPUB — FLAG: supply real cover art); no ebook
  ISBN → urn:uuid (FLAG); two flow.overrides dropping the part-header divider
  repeated inside the printed Contents (it shadowed the real part opener).
- Lessons: contents-page part-headers need drop overrides when they duplicate
  outline entries; gate 8 exempts title/toc-entry/titletext paragraphs (headings
  legitimately mirror running-head text).

## islam-and-buddhism — 2026-07-08

- Source: `Islam and Buddhism.pdf` (InDesign CS3/2010, PDF 1.3, 170 pp). Result:
  `epubcheck: clean`; QA `Overall: PASS` (coverage 99.78%, 197/197 notes, 168-entry
  page-list, byte-reproducible).
- The hard book: zero bookmarks/links (pure printed-TOC source); broken `SecN:`
  /PageLabels (printed-folio labels with backfill); and a **-0x1D-shifted ToUnicode
  CMap** in the closing essay — deterministically repaired (266 runs, verified
  highmap) with poppler's differently-garbled pages (138-145, 67K chars) excluded
  from coverage as ENGINE-DISPUTED (neither witness can arbitrate; render review
  covers them — FLAG for human spot-read of the essay section).
- 36 generated overrides for flush-left subsection heads (typographically identical
  to body text; identified by exact TOC-title match) + 51 generated join overrides
  for hyphen-seam paragraph breaks. Gate 6 tolerates the book's own ±1 TOC/print
  discrepancy (Epilogue). No ebook ISBN -> urn:uuid (FLAG). Cover from p.1 JPEG.
- Heuristics promoted to code (third book = strong signal): italic-twin pstyle
  fold for break decisions; role-override implies break; in-run/cross-run
  lower-only dehyphenation; marker-line gt excision fallback; engine-disputed
  page exclusion.

## me-and-rumi — 2026-07-08

- Source: `Me and Rumi with TOC links and cover.pdf` (Creo prepress 2004, PDF 1.6,
  441 pp, no ToUnicode). Result: `epubcheck: clean`; QA `Overall: PASS` (coverage
  99.72%, 374-entry page-list, byte-reproducible).
- Judgments: printed TOC (pp.8-9) as source with indent-derived levels and
  nav_depth 1 — the TOC's chapter groupings have NO physical headings in the book
  (only part openers at 21pt); nav mirrors the physical structure: parts (h1) +
  passage numbers (h3, ~560 entries = per-passage navigation, arguably better than
  print). restore_spaces healed 3,024 lost spaces + 843 ligature expansions.
  Cover from the p.1 spread's CropBox-isolated front panel. printed-folio labels
  (the /PageLabels are cover-offset). 28 generated join overrides for hyphen-seam
  paragraph breaks.
- Excluded + FLAGGED apparatus (print-page refs remain navigable via page-list):
  Index of Koranic Verses (375-380), Index of Hadiths and Sayings (381-391),
  Index and Glossary (392-432), Table of Sources (433-436, a true table).
- FLAGS: no ebook ISBN (urn:uuid); the introduction's six digit-note pages and
  occasional body asterisk notes remain INLINE as small-type paragraphs rather
  than linked endnotes (marker census too sparse/mixed for reliable pairing —
  content fully preserved); human spot-read of quote-heavy pages recommended
  (62 residual fused patterns, informational).

### 2026-07-08 addendum — typography fix pass (user-reported)

All four books rebuilt after fixing the false-centered-line class (body-size
paragraph lines whose midpoint lands near column center were rendered as
centered h3 headings and entered the nav — e.g. BoK 'This should suffice…',
verified against the print render). Body-size centered clusters are now
centered PARAGRAPHS; MR's 13pt aphorism quotes likewise; nbsp+space visible
gaps before honorific readings collapsed (0 remaining in all books). All
four: epubcheck clean, QA Overall: PASS, tests green.

### 2026-07-08 addendum — typographic-fidelity gates + two shipped defects fixed

QA grew gates 13-17 (typography: size fidelity, centered witness, emphasis,
heading census, per-page signature diff — 13/14/16/17 gating) and gate 18
(`qa --visual`: sampled print-vs-EPUB contact sheets + PUA glyph pairs for
agent grading). Validated against the pre-fix EPUBs at 3cfca48: gates 14/16/17
fire on all four old builds; current builds silent (matrix in NOTES.md).

The new gates found two REAL defects in shipped, Overall:PASS books; all four
rebuilt after fixing:
- mixed-emphasis paragraphs with an italic-family pstyle rendered ENTIRELY
  italic (class font-style swept the roman runs along; BoK Qurʾān-quote
  paragraph p.xx, MR/I&B similar) — styles_synth no longer emits font-style
  from the family name; run-level <i> markup carries italics.
- I&B shipped a garbled h3 '%LEOLRJUDSK\' (= 'Bibliography', shifted CMap)
  in body + nav on the bibliography pages — single-word shifted lines carry
  no space marker; is_shifted_run gained a word-shape detector and the
  heading now reads 'Bibliography'.

All four: epubcheck clean, QA Overall: PASS with promoted gates, tests green.

### 2026-07-08 addendum 2 — justified-block last-line false centering (user-reported)

BoK: the short last line of an INSET justified block (quote indent, drop-cap
wrap) false-centered whenever its midpoint landed near column center — the
12%-inset rule can't see it because the whole block is inset ('may be
categorized under ten headings:' p.185, 'be the first of your people…' p.193,
plus two unreported instances p.184/p.227; zero in the other books). New
doctrine in line_pstyle + gate 14's witness: a body-size line continuing a
justified block (previous raw line at the same x0 reaching the right margin)
is never /center. BoK rebuilt: all four lines rejoin their paragraphs;
epubcheck clean, QA PASS.

### 2026-07-08 addendum 3 — proofread harness acceptance run (I&B) + join-rule overhaul

First full run of the new reading-QA flow (`pdf2epub proofread` + blind
reader subagents per packet + print verification): 21 readers over 24 I&B
packets returned 328 findings, which root-caused into a few systemic
classes. All three seeded acceptance defects found, plus discoveries:

- JOINER (code, all books): added the 'ragged line ends its paragraph' rule
  and its cross-page mirror; indent breaks now require the previous line to
  have plausibly ended (hanging-indent list continuations no longer split).
  Fixed at once: quote→commentary fusions (~80), flattened verse/bullet/
  signature blocks (~35), page-turn wrong-splits, hanging-list splits.
- NOTEREF SEAMS (code): the join separator parked on a marker run was
  discarded when the run became a NoteRef — 43 'word.[38]The' seams in I&B,
  31 in BoK. Gate 11b now guards this permanently.
- CONTENTS TRUNCATED (config + code): a role_overrides entry annotated
  'copyright' actually sat on the CONTENTS page and wiped 36 toc-entry
  roles; separately the emit contents-gather stopped at a mid-TOC subtitle.
  The rebuilt Contents now carries all 41 entries with its interludes.
- FOREWORD MISSING (config + code): the Dalai Lama's foreword is a
  facsimile-letter IMAGE both engines are blind to; figure_pages gained
  keep_text and the plate now ships with a descriptive alt under its
  typeset h1.
- PART HEADINGS (overrides): 'Part One/Two/Three'/'Epilogue' labels split
  from their titles (4 break overrides).
- DEHYPHENATION (code): compound-forming prefixes keep their hyphen
  (self-, all-, half-, well-, ill-, cross-, low-, twenty-…ninety-).

All four books rebuilt: epubcheck clean, QA Overall: PASS, gate 11b clean,
old-EPUB regression detection preserved. Round-2 spot reads: packet finding
counts dropped ~6-17 → 0-4; the seeded defects and both discoveries are
gone from the packets.

HANDOFF (CLOSED 2026-07-09, see the addendum below — the font-scoped
design proved impossible on this PDF): shifted-CMap coverage
on the essay/back-matter italic runs ('=' spaces, J-hyphens, shifted
transliterations, FFFD note prefixes, ³´ quotes) — design: font-scoped
repair; footnote-capture failures on pages 30/38-41 + essay (bare digits,
inline note bodies that also cause page-turn splits, folio leaks);
fused/possibly-missing essay endnotes (printed 12-15); dash/slash seam
spacing and BoK sample items (flush-style page-turn paragraphs in the
biographical essay, two undetected section heads) pending print checks.

### 2026-07-09 addendum — precision pass: gates 20-22, gate 11 promoted, inline anchors

External-feedback evaluation pass; every claim verified against shipped
artifacts before acceptance (evidence matrices in NOTES.md). All five
artifacts rebuilt: epubcheck clean, QA Overall: PASS on the now-23-gate
suite, byte-reproducible (double-build hash check).

- ME AND RUMI: 62 shipped cross-run fused seams (`believer.This`) repaired
  by the new paragraph-level seam pass + the bracket/digit-quote pattern
  (spaces-restored-crossrun=85, +3 bracket) — gate 11 now gates at zero.
  Three "unrecognized top-band" lines were shipped running-head LEAKS
  (9pt-italic 'William C. Chittick', two smallcaps chapter heads) — drop
  overrides. p.437's content photograph (Yakutiye Medrese portal) shipped
  caption-only — now a figure page with descriptive alt. Decorative
  medallions/dividers adjudicated (renders reviewed).
- ISLAM AND BUDDHISM: closed the 2026-07-08 shifted-CMap handoff — but NOT
  via the prescribed font-scoping (dead: identical font names on broken and
  healthy pages; see NOTES). Highmap gained render-verified ³→" ´→" ²→—
  «→… Ɩ→Ā; µ/¶ remapped to the book's own quote convention (they are the
  subset's single-quote glyphs, not bare ayn/hamza); 'VDED¶' caught by the
  highmap-aware word-shape detector; 474 U+FFFD chars removed via
  glyphs.fffd_repairs (renders show no visible content at all 8 spots);
  garbled 'Bibliography' running heads pp.166/168 dropped (single h3
  ships). qa.garble_chars pins the whole residue set; gate 20 fires 15 runs
  on the old EPUB, 0 after.
- HARMONIOUS UNITY: p.8's Yin-Yang facsimile plate shipped caption-only —
  now a keep_text figure page. Calligraphic section glyphs adjudicated as
  ornamental (chapter heads carry the titles). The "2 RTL chars" warning
  was two U+FEFF BOM artifacts, not RTL — census range fixed.
- BOOK OF KNOWLEDGE (both variants): title-page top-band line adjudicated;
  the arabic variant's RTL adjudication moved from NOTES prose into config.
  Per-variant warnings files (warnings.book.arabic.md) end the last-run-wins
  collision.
- ALL BOOKS: exact inline page anchors (BoK 179 / BoK-arabic 179 / HU 31 /
  I&B 98 / MR 181 pages start mid-paragraph and now anchor at the true run
  seam; remaining approximate anchors are verified blank pages). Gates
  13-17 verdicts unchanged; proofread packets differ only in blank-page
  marker placement (now on the correct side of section boundaries).

## me-and-rumi — 2026-07-10 re-ship (verse feature + proofread rounds 1-3)

First book through the semantic block grammar (blocks.verse) and the
heaviest proofread pass to date: 38 blind readers × 2 full rounds + a
print-verification round. Build: 93 verse groups / 305 lines / 98 stanzas
ship as z3998:verse blockquotes (gate 23: 305/305); all print-verified
damage cells healed (p.35 quatrain, p.46 Kaaba couplet, p.165 ghazal,
p.356 notes ghazal). qa Overall: PASS on all 23 gates; gate 6 8/8 TOC
entries (parts now real entries) on their printed pages.

Fixed this pass (each class print-verified before repair):
- prepress lost-space classes incl. the long-deferred comma+lowercase
  (~1000 additional restored spaces; residual grep-verified 0), the
  wrong-side-of-closing-quote class (0 residual), text-asterisk seams,
  citation seams, display-ampersand title seams
- indent_threshold 10 -> 8 (paragraph indent 9-11pt vs per-page column
  drift): +827 recovered paragraph breaks — the dialogue-turn and
  re-opened-quotation fusion classes
- 22 section-title+passage-number h3 fusions; copyright page block
  structure (center-gap rule); printed-TOC part entries (were fused into
  neighbors); page labels 28-30 (roman interpolation across the front/
  body boundary — wrong in the old artifact's page-list too)
- compound-chain dehyphenation (so-and-so kept; know-noth-/ing joins)

READING CONVENTIONS (print-verified 2026-07-10; do NOT flag): the
translator's elliptical English is as printed — "you'll along with
thorns", "no else saw", "How do explain", "If I were I to tell",
"it as if", "the neck one of those words", "conceal it my sleeve",
"a another sobriety". '53 bis.' is set in lining figures vs the
smallcaps passage numbers IN PRINT. The p.63 part-divider epigraph has
no passage number or citation by design.

HANDOFF (deferred to Phase L, blocks.lists): the notes apparatus
(pp.337-373) and Works Cited ship with systematic hanging-indent damage
— nearly every note's first line splits from its body and short-ending
notes fuse into the next. That is the list shape (marker + turnovers);
round-1/2 packet-037-040 findings are the Phase L acceptance evidence.
Also open: single-line verse quotations ship as short paragraphs (the
2-line classifier minimum, by design); 'earthof Tabriz' single in-PDF
lost space (no safe pattern).
