# Conversion ledger

One entry per finished conversion: date, source PDF (sha256), decisions worth remembering,
QA outcome, and anything the next conversion should learn from. Ten books are converted
(eleven tracked configs — book-of-knowledge also ships an Arabic-glyph variant);
`pdf2epub corpus` rebuilds and QAs all of them.

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
    RE-SYNCED 2026-07-10 (review #455): the variant had frozen before Phase F, so its
    `blocks:` (verse/quotes/lists), the 41 flow.overrides, the Minion@12→h2 census heal,
    and the p.245 verse-suspect adjudication were missing — the verse-suspect witness
    fired 8× and gate 22 FAILED (exactly the D6 drift-detection this witness exists for).
    Mirrored the main variant's render-verified structural judgments (identical page
    geometry; only pua_map/fonts differ); rebuilt to 2799 blocks — structurally identical
    to the main — epubcheck clean, gate 22/23 PASS, Overall: PASS. Its committed artifact
    was also stale (built pre-final-code); refreshed. Lesson: variant configs must track
    the primary's structural judgments; the verse-suspect witness catches the drift on
    rebuild, but only if the variant is rebuilt.
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

## me-and-rumi — 2026-07-10 re-ship 2 (blocks.lists: the notes apparatus healed)

Phase L turns the notes apparatus (physical pp.336-374) into a real
decimal list: 233 items / 364 list paragraphs ship as <ol>/<li> with the
passage-number markers kept in the text. Blind re-reads of the changed
packets (three rounds, 14 readers total incl. two textfix-delta packets)
drove the fixes; every finding was verified against raw extraction or a
print render before repair.

Fixed this pass:
- entry-break + hang-join heals the two shipped damage classes (nearly
  every note's first line split from its body; full-width note ends fused
  into the next entry) — round-1 packets 037-040 were the evidence
- the apparatus's INSET BLOCK level (lemma glosses and quoted passages at
  hang+9, their paragraphs indented a further 18pt): stepping into the
  inset breaks (20+ geometry-verified lemma fusions healed), within it
  geometry rules (note 244's quoted anecdote had shattered one paragraph
  per print line under the first cut of the rule)
- hang-column paragraphs after a short entry line break ('Intellect is a
  veil.', p.341); range markers ('19-22.', '102-103.') are entries; the
  notes actually START mid-p.336 and END p.374 (the first spec cut both)
- the p.370-371 ghazal continuation: the page-top base line ending 7.3pt
  short is the poem's second couplet, now verse with the page anchor
  inline at the line seam (gate 23: 307/307)
- the false-center trap inside items: short lemmas whose midpoints chance
  near the column center ('He sits in front of me like a son.', 'Atabeg.')
  were /center-labeled, splitting the ol and detaching downstream lemmas
  ('Possessors of the kernels', 'On the sash and Abu Yazid',
  'Saddle-cloth') — a centered line at the item's own columns now stays a
  member with the label stripped (the verse precedent); genuinely
  centered dividers ('Part 2.') still break the list
- one per-line judgment: note-211's 'Unlettered.' lemma opens its inset
  paragraph after a lemma ending only 12.2pt short — under the ragged-end
  floor, invisible to geometry (flow.overrides break, p.357 line 20)
- print-verified textfix classes: marker+single-capital ('84.O you', 7
  sites), semicolon+letter (54 sites), digit+comma+capital, digit+comma+
  year ('October 11,1244'), closing-quote+period+capital
- dehyphenation: the Arabic article keeps its hyphen when a capitalized/
  diacritical word precedes ('Mirsad al-ibad'; the rule also heals 12
  'Qut alqulub'-class sites in the SHIPPED BoK, which re-ships in Phase
  F); seven-/just- joined the closed compound set

REFUTED (as-printed, verified against raw extraction/renders): the tight
passage-citation seam '”(343)' and quote-bracket '”[kafshak]' (the book's
convention), '(M I 638-38)', 'word's of Iblis', 'His father' tradition',
'That this a commentary', 'is common theme', 'a things', 'awliya'Allah'
(U+2019+letter stays permanently unsafe), '(nîstî )', MSM vs MMS sigla.

HANDOFF (unchanged + new): the bibliography 'Abbreviations and Works
Cited' (pp.334-336a) has no markers — its ~250 hanging-indent entries
keep their old one-line-per-block damage until a hang-only shape exists
(incl. 'SPL.W. C. Chittick' and the 'trans-'/'lated' stranded hyphen);
the introduction's six digit-note pages stay inline as flagged at
conversion; single-line verse quotations remain short paragraphs;
'earthof Tabriz' and 'hundredthousand-year' remain.

qa Overall: PASS (all 23 gates; gate 23 verse 307/307), epubcheck clean,
246 unit tests green. Final state: 233 items / 366 list paragraphs.

## islam-and-buddhism — 2026-07-10 re-ship (quotes/verse/lists re-judge + CMap heals)

Phase F re-judge under the semantic block grammar, driven by three blind-
reader rounds (24 readers) plus a 2-reader round-2 verification pass; every
accepted finding was verified against raw extraction or a line dump before
repair.

Fixed this pass:
- blocks.quotes ships the 18/18pt justified insets as real blockquotes
  (94 quote paragraphs) and blocks.verse the ragged scripture verse on 18
  pages (24 groups / 130 lines: Dhammapada, Flower Ornament, Milarepa,
  sura 107, the Jami couplet)
- the Hamza Yusuf essay's footnotes: _note_start/_note_marker now probe
  the shifted-CMap repair PER RUN — a clean line whose only 'shifted'
  evidence is the lone honorific dingbat was line-shifted into garbage,
  leaking note 1 ('The Sunnah is the normative…') into the body as 9pt
  paragraphs with bare 'Sunnah1' markers; notes 199 -> 229, all linked
- '3.The Dhammapada' / '4. The hadith' endnote fusions: a digit marker
  abutting a capital (prepress lost the space) now opens a note
- the Bibliography (printed 139-144) ships as a real hanging-indent list
  via the new marker-less `blocks.lists marker: hang` — entries at the
  column edge break, +18pt turnovers join (~40 reader-flagged splits and
  fusions healed, incl. every '———.' same-author entry)
- mixed-encoding CMap repairs: raw space->'=' seams, line-end hyphen->'J'
  ('conJ stantly' class), trailing 0x2D; title-page/copyright display
  breaks; 36 flush-left subsection heads role:h3 (TOC-corroborated);
  'wa al-' keeps the article hyphen ('Kitāb al-milal wa al-nihal')

REFUTED (as-printed, raw-verified): 'can only compared with', 'insofar',
'Shakymuni', 'Budhha', 'nodharma', 'de-void', 'herebelow', 'Cha'n',
'Ummayayd', 'Daihetz', 'op.cit,.', 'E.Conze', '422– 423' and the other
round-3 lows; 'refrain in the Qur'ān' duplication (both sentences print).

HANDOFF (round cap reached; all on the engine-disputed shifted-CMap pages
unless noted): honorific-glyph drops leaving ' .'/' ,' seams (needs
per-glyph render verification); mid-line note fusions ('…128. 17. Cyril
Glasse' — two notes share one physical line; no mid-line split machinery);
ragged-inset hadith/dialogue quotes (pp.82-86, 135-137) stay unmarked (the
quote detector is justified-only by design); 'farwah bay\ā’'-class Arabic
garbles (render-review queue); 'Kitābal-milal' lost space inside a shifted
run; the al-Alusi quote opener (printed 116) outside its blockquote.

Round-2 verification (2 readers): the essay-notes leak and the ~40
bibliography splits/fusions confirmed healed; every residual is a
pre-documented handoff class on the shifted pages (plus the biographies
page's works-list fusions — same hanging shape, out of the current
spec's pages).

qa Overall: PASS (all 23 gates), epubcheck clean, 259 unit tests green.
Final state: 796 blocks, 229 notes, 94 quote paras, 24 verse groups,
96 list items.

## book-of-knowledge — 2026-07-10 re-ship (verse corpus-wide + honorific seams)

Phase F re-judge: blocks.verse/quotes/lists recorded (round 1), then a
9-reader structural round and a 2-reader round-2 verification; findings
verified by line dumps before repair.

Fixed this pass:
- blocks.verse on nine pages (11 groups / 47 lines): the ʿAlī poem
  (printed 10), couplets printed 144/169/230, the al-Shāfiʿī poem
  printed 167, the quatrain printed 173, admonisher verses printed 185,
  the six-line poem printed 232 — near-full poem lines and hanging
  turnovers pinned line-by-line with class:verse overrides (each
  turnover ships as its own verse line, exactly as printed);
  prose intros at the same inset pinned class:prose
- honorific punctuation seams: the glyph's advance extracts as a literal
  space before following punctuation ('(exalted is He) .') — collapsed
  at the PUA substitution site, including across run boundaries
  (13 seams; twice reader-flagged)
- Minion@12 remapped p -> h2 (census: every such line is a heading); the
  wide two-line chapter subtitles that lose /center no longer ship half
  as body ('An Elucidation of the Traits… / Hereafter and of the
  Reprehensible Scholars' is one h2, printed 170; also printed 1/135/141)
- prepress size wobble: lone Minion@10.5 lines amid 11pt broke paragraphs
  mid-sentence (printed 165/166, 'three blocks' readers) — join overrides
- wrong-script lookalike: GREEK CAPITAL ALPHA WITH MACRON standing in for
  Ā in transliteration ('ʿᾹmir', 8 sites) repaired before Latin lowercase
- blocks.quotes (36pt justified insets) and the forty-books decimal lists
  (pp.41-42) from round 1 stand

REFUTED (as-printed, raw-verified): 'becaues', 'and or', 'mis-spoke',
'this worldly', 'Hold fast to silence' (fresh indented line in print),
'even if they give you a ruling' ×3 (hadith emphasis), the title-page
letterspacing ('K i t ā b a l - ʿ i l m' — print display type), the
p.ii Contents-list fusions (pre-existing front-matter display).

Round-2 verification (2 readers) closed the loop: the quatrain's four
missing verse lines exposed the justified veto silently unwinding
class:verse forces (shared-code fix: explicit overrides now beat the
geometric vetoes; gate check = build-log verse-lines vs recorded
forces), and the p.220 quotation's page-turn continuation joined its
blockquote (p.221 added to the quotes spec). The ']' and closing-quote
flags are as-printed (raw-verified).

HANDOFF: 'this-worldly' compound ambiguity; turnover verse elsewhere
hides below geometry.

qa Overall: PASS (all 23 gates; gate 23 verse 51/51), epubcheck clean,
259 unit tests green. Final state: 2802 blocks, 671 notes, 11 verse
groups (51 lines), 40 list items, 13 honorific seams healed.

## harmonious-unity — 2026-07-10 re-ship (CJK seams + display blocks + lists)

Phase F re-judge: bulleted chapter-digest lists (round 1), HU title-block
overrides (round 2), then a 8-reader round plus 2-reader round-2
verification; findings verified by line dumps and raw extraction.

Fixed this pass:
- CJK line-wrap seams (shared textfix rule): a Chinese title wrapping
  across a print line now rejoins CLOSED — both-CJK seams and
  bracket↔CJK seams ('天方至圣实录', '上海辞书出版社', '([天方性理]',
  '一斋)…' — ~25 reader-flagged sites across the foreword)
- title page (physical 3): U+FEFF line and CJK-placeholder dots dropped,
  byline/credits display units broken apart ('…Five-Fold Path by Liu Zhi
  Foreword by Wang Genming' fusion healed); copyright page (physical 4)
  imprint lines each their own block; page-level roles were off by one
  (physical 2 is empty — title-page role now on physical 3, copyright 4)
- foreword ragged quotes (physical 24): the four 'I …' quotations were
  each split into three paragraphs by the short-line rule — join
  overrides restore them; the two-line section heading on physical 25
  rejoined into one h3; '一斋).' pstyle-change split joined
- the back part-title (physical 146) mirrors the p.35 fix: placeholder
  dots dropped, 18pt byline role:p + join (gate 6 outline anchors hold)
- bulleted source/chapter digests (pp.10-18) ship as real lists (77
  items) with CJK turnovers now closing correctly

REFUTED (as-printed, raw-verified): 'Liu Zhi's intellectual framework,
the "Wisdom of Earth" constitutes' (print has no 'In'), 'In Liu Zhi's
"Wisdom of Humanity" centers' (print grammar), 'Chuko Shinso, 1993,
58 p)', ISBN 979-889640-0141, the '© dropped' suspicion (raw reads
'Copyright Fons Vitae 2026').

HANDOFF: 'far-reaching'/'lead-type' line-break hyphens eaten by
lower-only dehyphenation (compound vs syllable is lexicon work —
specs/qa-methodology.md second-witness proposal); the epigraph
attribution 'Liu Zhi, Tianfang Dianli' shares its raw extract line with
the quote end (no mid-line split machinery); printed-p4 inline digit
notes stay inline (footnotes: none — the book's translated-text
convention, flagged at conversion); the Chinese source-text section
remains mirror-bound page images (idml2epub-parity limitation).

Round-2 verification (2 readers): the ~25 CJK seams were confirmed
healed; two residuals fixed and verified (the two-line section-I heading
rejoined; the '十一年马福祥刻本).' ArialUnicodeMS pstyle split joined).
Additional refuted-as-printed: 五功义/礼书五功义 (raw reads without 释 in
both engine witnesses), the 384-acts sum, [] around CJK titles.
Additional handoff: the foreword's inset quotations (Cihai entry, the
declaration, the Ma Kuilin preface) stay unmarked body paragraphs — a
mixed justified/ragged inset family; marking part of it would be worse
than none.

qa Overall: PASS (all 23 gates; gate 6 outline 70/70 with the byline
overrides), epubcheck clean vs the idml2epub reference, 259 unit tests
green. Final state: 750 blocks, 77 list items, 69 figure pages.

## sufism-veil-and-quintessence — 2026-07-10 re-ship (front-matter list + re-verify)

Phase F re-judge: the corpus-wide detector upgrades (verse suspects = 0
firings; quotes witness re-checked) left the body untouched; blind
readers (3 incl. round-2) flagged only the front matter.

Fixed this pass:
- the 'Books by Frithjof Schuon' page (physical 3): one title per print
  line — the indent-join fused neighbours whose x0 steps sit under the
  threshold (the 9pt display lines never trigger the body short-line
  rule), and the round-2 justified-cluster coverage change had widened
  the fusion; per-line break overrides with 'ed. …' turnovers joining
  their titles (round-2 reader caught one residual seam — the indent
  rule never fires on non-body pstyles; explicit break added)

REFUTED (as-printed, verified): printed 112/114 'empty page' suspicions
(both pages carry only paragraph continuations and notes — reading
order is correct); the Koranic-signs sequence pp.111-115 intact.

HANDOFF: unchanged from the original conversion (index column-split
recto/verso specs stand; PUA ornaments dropped as recorded).

qa Overall: PASS (all 23 gates), epubcheck clean, 259 unit tests green.
Final state: 1580 blocks, 170 notes.

### 2026-07-10 addendum — Editor's Notes relinked (World Wisdom imprint)

User request: the Editor's Notes are keyed to ORIGINAL PRINT PAGE NUMBERS
with no body-text marker — dead after reflow. Two asks: (1) a World-Wisdom-
specific module that doesn't clutter the generic pipeline, (2) an intelligible
EPUB link. Decision (with user): a gated `imprint:` block routing to
`pdf2epub.imprints.world_wisdom`; **Tier C** linking, **no body-side markers
in v1**. See NOTES.md "Imprint transforms + Editor's Notes relinking".

- `imprint: {name: world-wisdom, editors_notes: {…}}` added to book.yaml.
- Each note's leading bold page number → the `#pg-<label>` print-page anchor
  (carry-forward across continuation paragraphs); each `Note N` → the author
  footnote, resolved chapter-aware `(chapter, local N) → global fn` (the EPUB
  renumbers footnotes globally, so Exo-Esoteric "Note 3" = fn22, not fn3).
- Result: 99 page links + 61 footnote links, 0 unresolved. Every note link
  verified to point at the correct footnote (61/61; 5 callout-page readings
  differ by ±1 only because the marker sits at a page seam — not a mislink).
- qa Overall: PASS, epubcheck clean; me-and-rumi rebuilt clean (imprint inert).

HANDOFF: `body_backlinks` deferred (parsed, rejected as unimplemented);
intra-notes cross-refs ("see editor's note for Preface, p. 4") ship as plain
text. Consider a blind-reader `/proofread-epub` pass to confirm the linked
page numbers read naturally in a reader.

### 2026-07-11 addendum — full /proofread-epub pass (31 packets)

First full blind-reader pass over the shipped book (29 readers, 31 packets;
15 clean). 24 findings, almost all pre-existing (orthogonal to the imprint
change, whose Editor's Notes area read textually clean). User scope decision:
fix the **high-value subset** (Editor's Notes entry-fusions + TOC Appendix),
document the rest.

FIXED (render-verified; rebuild epubcheck clean, qa Overall PASS; changed
packets 003/024/025 re-read clean of these):
- 4 back-matter entry-fusions — an entry starting at a page TOP fused into the
  previous page's last entry (no gap signal across the seam). A pagebreak-anchor
  + entry-label scan found EXACTLY the 4 readers flagged: `Gaudapada` (p182),
  `Note 15: Ahmad al-Alawi` (p184), `Selection 22` (p193), `Sepher Torah` (p202).
  Fixed with `flow.overrides` breaks at each (page, line 1). Fixing `Note 15`
  also un-suppressed its imprint footnote link (61→62 — the linker only fires
  "Note N" detection at a paragraph start).
- TOC `Appendix` fused onto `Hypostatic Dimensions of Unity` (part-divider line
  carries no folio → was read as a wrapped-title turnover). New `toc.standalone_lines`
  knob (config + printed-TOC rebuild branch) makes it its own entry; gate 6 now
  skips folio-less part-divider entries (can't page-verify a page-less label).

HANDOFF QUEUE (pre-existing; not fixed this pass, print-verify before acting):
- Dropped compound hyphens from `dehyphenate: lower-only` over-stripping a real
  compound broken at its hyphen (8): `religion-quintessence` p29, `prayer-niche`
  n162, `karma-yoga` p138, `quasi-supernatural` p89, `vis-à-vis` p.ix,
  `lightning-like` p73, `logician-like` n42, `non-theological` p90. The project
  deliberately refuses a keep-hyphen lexicon (see the dehyphenate doctrine);
  a per-book render-verified keep-list would be the sanctioned mechanism if wanted.
- Spurious space after a hyphen/dash WITHIN a source line (5) — an extraction
  artifact, NOT a join bug (verified: `al- Bātin` sits inside one raw line):
  `al- Bātin` p106, `Apara- Brahma` p176, `[113]:1- 2` p12, `ʾIhyā— whether` p51,
  `God”— and` p47. Would need a shared textfix normalization (risk of over-firing).
- Index column line-break hyphens RETAINED (2): `anthropomor- phist` p187,
  `Muham- mad` p189 — dehyphenation not applied on the column re-split path.
- Other: stray U+00AD in `poverty` p27; `beyondcaste` (lost space) n120;
  Ibn Arabi Fusūs passage p39 should be a blockquote (quote-boundary).
- Structural: `Seyyed Hossein Nasr Bethesda, Maryland` signature block (foreword)
  low-confidence fusion — verify against p.x before touching.

### 2026-07-11 addendum 2 — nav nesting + handoff compound-hyphens

Follow-up ("continue with both"): side-nav nesting fix + first handoff theme.

- **Nav nesting bug (user-reported):** the Editor's Notes chapter subheads (all
  h3) nested UNDER `Preface` instead of being its siblings. Root cause in
  `nav._nest`: the old `min(level, stack+1)` clamp lost same-level identity
  across the `h1->h3` jump. Rewrote to compute each heading's depth as its count
  of strictly-shallower ancestors — same-level headings are now siblings
  regardless of the gap, and no `<li>` ever gets a second `<ol>` (an earlier
  attempt did, failing epubcheck via GLOSSARY h2 after the h3 chapters). Shared
  fix; 6 new `test_nav` cases; all books re-QA clean.
- **Handoff theme FIXED — dropped compound hyphens (8):** new per-book
  `flow.keep_hyphens` (render/in-book-verified list, like `qa_lost_space_allow`
  — an agent judgment, NOT the global lexicon the doctrine refuses). Preserves a
  real compound's hyphen when it falls at a line break. `religion-quintessence`,
  `prayer-niche`, `karma-yoga`, `quasi-supernatural`, `vis-à-vis`,
  `non-theological`, `lightning-like`, `logician-like` — all now hyphenated, 0
  fused. `dehyphenate_join` gained a `keep` param.
- Soft-hyphen `poverty` (U+00AD): already resolved — 0 soft hyphens in the
  current build (the reader saw a pre-fix build).

STILL DEFERRED (lower value / higher regression risk): hyphen/dash space-seam
SOURCE artifacts (`al- Bātin` etc. — gate-9-tolerated, ~1-3 left, would need a
shared or per-book close-rule with over-fire risk); index column-hyphen
retention (intricate column-join path); `beyondcaste` lost space (no clean
per-book split knob); Ibn Arabi Fusūs quote-boundary (needs a blocks.quotes
spec).

## form-and-substance-in-the-religions — 2026-07-13 (new conversion + 6 pipeline fixes)

Frithjof Schuon, *Form and Substance in the Religions* (World Wisdom, 2002;
trans. Mark Perry & Jean-Pierre LaFouge from *Forme et Substance dans les
Religions*, Dervy-Livres 1975). 266pp PDF, source
sha256 `1f713dd1…a166cba1`. ISBN-13 978-0-941532-25-9. Sixth+ shipped book;
first NEW conversion since the 2026-07-10 re-ship wave. Build `epubcheck: clean`,
`qa Overall: PASS` (coverage 99.94%, 334 notes, fidelity min-recall 0.997,
a11y ace pass). Backend ML layout witness installed for the run
(torch 2.13.0+cpu / transformers 5.13 / timm 1.0.28, Python 3.14).

### Structure judgments
- Classic World Wisdom / Library of Perennial Philosophy design — a near-twin of
  `sufism-veil-and-quintessence`, but this 2002 edition uses **NewBaskerville**
  directly and **headings are ROMAN, sized (17pt), NOT bold** (`@17/center` +
  italic-`@17/center` for `Âtmâ-Mâyâ`/`Pâramitâs`/`Mahâyâna` chapter titles → h1).
- Furniture: italic-centered running heads (book title verso / chapter title
  recto) + centered folios → role p (band-stripped). NB the ch.11 running head
  carries a **print typo `Feminime`** (title/TOC/body read `Feminine`) — added
  as-printed to `furniture.extra` so it strips.
- Section dividers: `* / * *` asterisk pyramid (`@14/center`) kept as content;
  `keep: ["*"]` so top-of-page ones aren't stripped.
- Cover = rendered p1 (Bagan temple photo). Back cover p266 (endorsements,
  barcode, $17.95) **excluded**. Copyright p5 role p; title p4 role title-page.
- TOC: `source: printed`, nav_depth 1; ch.6 wraps ("…in Koranic / Onomatology").
- Footnotes: digit markers, geometric bottom-region split (334 notes).
- **NO** verse / blocks.quotes / blocks.lists / flow.columns / PUA / CJK / RTL —
  the analyzer's list/quote flags were footnote numbers + footnote hanging
  indents (verified on renders); the layout witness's "columns" were the known
  weak signal (analyzer `column_suspect_pages` empty). Simplest corpus book yet.
- 6 chapter titles wrap to 2 lines → join overrides (join_center_lines off).

### Six pipeline code fixes (each with a unit test; all 5 reference books re-QA PASS)
Surfaced by this book, all generalizable:
1. **Note-region gap-break** (`flowbuilder` + test): the copyright page is set
   WHOLLY sub-body-size, so the note-region scan walked up a 107pt gap from the
   LCCN `1. Religious. I. Title` line and swallowed the whole cataloging + World
   Wisdom address block, which — having no in-body marker — was **silently
   dropped**. Fix: the scan stops at a gap > 2.5×max-note-size (a note block is
   contiguous). *Content-loss bug.*
2. **TOC wrapped-numbered-entry** (`flowbuilder` + test): a numbered entry whose
   folio wrapped to the turnover line ("6. …in Koranic" | "Onomatology 69")
   fused ch5+ch6 and shipped a bogus "Onomatology" entry. Fix: a marker line
   with no folio opens a pending entry; the number-less folio turnover completes
   it. (Guarded so standalone entries like sufism's "Appendix" are untouched.)
3. **`_ps_root` roman/italic fold** (`flowbuilder` + test): only "Italic" was
   stripped, so `NewBaskerville-Roman@x` ≠ `NewBaskerville-Italic@x` and a
   full-line inline italic Latin/Arabic gloss read as a pstyle change — **8
   paragraphs split** into lowercase-initial blocks (ch.12 "Spiritus ubi vult…"
   opening broke into 3). Fix: fold "Roman" too.
4. **Em-dash line-join seam** (`textfix.dehyphenate_join` + test): a closed
   em-dash arriving as its OWN roman run after an italic word (`<i>Vajrayâna</i>—`)
   left `prev = "—"`; the old `[letter][—]$` guard missed a bare dash and a
   quote-before-dash. Fix: `(?<!\s)[—–]$`. ~19 seams closed.
5. **`strip_stray_grave`** (`textfix` + groundtruth + test): a lone ToUnicode
   grave accent `Subjectivity itself`.` (invisible in the render, unique in the
   book) stripped when NOT followed by a letter — preserves M&R's 27 ʿayn
   graves (`a`a`, ` `Ali`) by construction. Shared flow/ground-truth.
6. **Shift-corrected indent** (`flowbuilder` + test): the absolute indent test
   used the global `col_left`, so on a left-shifted verso page (continuations at
   x0≈43 vs modal 55) a real ~16pt citation indent read ~5pt and a page of
   Biblical proof-texts fused into one paragraph (ch.13 Magnificat). Fix:
   `eff_left = col_left - geo.shift(pno)` (same shift the verse/quote passes use).
   *Latent across the corpus — also un-fused ~105 paragraphs in sufism, still
   PASS at recall 0.997.*

### keep_hyphens (13, render/reader-verified real compounds broken at a line)
`three-dimensionality` p104, `equilibrium-restoring` n179, `near-divine` n128,
`prayer-niche` p117, `super-eminence` p119, `non-attachment` p177, `void-like`
p178, `multi-dimensional` p210, `bi-idhni’llâh` n25; transliterated definite
article `al-malakût`/`ash-shahâdah`/`al-mutlaq`/`al-qism` (lowercase, so the
arabic-article keeper skips them). NOT `reabsorbed` (authorial-solid, 5×) /
`preeminent` (n122 as-printed solid, cf. hyphenated `pre-eminent` on same page).

### Reading QA — 3 rounds (mandatory /proofread-epub)
- Round 1 (37 packets, 34 blind readers): ~40 findings. Fixed the real ones via
  the 6 code fixes + keep_hyphens; refuted as-printed (`worldy` p189, `intent,:`
  p191, doubled `"the "First"` p70, LCCN `English}` p.iv, `Ps.126` no-space).
- Round 2 (32 changed packets re-read): caught a **regression** — the shift fix
  re-fused the p265 centered book list — plus `bi-idhni` (my rejoin dropped its
  transliteration hyphen) and `multi-dimensional`. All fixed.
- Round 3 (5 changed packets): the p265 line-per-line breaks over-split the
  2-line entries; final fix = BREAK each title + JOIN each publication turnover
  → one paragraph per book (satisfies both rounds). Converged.
- Verified false-positive: `{p.136–139}` "truncation" — all body content present
  (clustered page markers = a long paragraph spanning the pages, protocol-exempt).

### Documented (deferred — justified-extraction spurious spaces, gate-9-tolerated)
Consistent with prior books' deferral (over-fire risk of a shared close-rule):
3 mid-line em-dash spaces (`another— otherwise` p18, `way— it` p192, `Throne—
Heaven` p55), 2 transliteration-elision spaces (`wa’ s-sifât`, `wa’ shshahâdati`),
2 verse-range spaces (`17- 18`, `27- 30`), `aspects , two` (space-before-comma),
`“ Hear` (space-after-open-quote). All in-source; render shows the closed form.

## Keys to the Beyond — Patrick Laude (SUNY Press, 2020) — 2026-07-14

- source sha256 `a4ac119194cd4c0eff7a9ebdce3cb7d77691eccda8de63eec137597932057cd7`
  (406pp; **producer: calibre 4.8.0** — the first non-InDesign producer in the
  corpus, and the source of this book's two hardest defects)
- 584 footnotes, 2-column linked index (printed 375–394), 2 bibliographies,
  2 Schuon poems, 2 blockquotes, cover rendered from p1. `Overall: PASS`.

### Structure decisions worth remembering
- **The p7 "verse" is an EPIGRAPH.** The witness measured base 24.2 / turns 44.4
  — but the "turn" is the attribution's deeper indent, not a couplet drop, and
  the block is JUSTIFIED. `role:epigraph` overrides, not `blocks.verse`.
- **The layout witness called the Contents page (p8) a "Table"** (conf 0.865).
  The render says otherwise. It flags; it never decides.
- **Verse vs quote separated by the right edge, as designed**: p149/p353 lock at
  x1=349.5 (quotes); p317/p355 scatter 181–350 (Schuon poems, optically centred
  so each has its OWN inset: base 42.2 and 25.2).
- **`indent_threshold` 12.0, not the proposed 18.0** — see NOTES: the proposal
  comes from the BODY histogram (24pt) and landed exactly on the index's 18pt
  turnover column, making `entry_break` a knife-edge that cost ~42 index entries
  their locators.
- Both bibliographies are marker-less hanging apparatus → `blocks.lists`
  `marker: hang, hang: 24`. The chapter NUMBER is its own 13.5pt cluster: joined
  onto the title via overrides so each chapter ships ONE h1 matching its outline
  entry (two h1s would strand a file containing only the digit).
- 12 `keep_hyphens`, each attested hyphenated mid-line in this same book (audited
  by hooking `dehyphenate_join` over all 752 joins). `inner-most` is settled by
  the book's own INDEX, which prints the phrase hyphenated twice.
- `qa.duplicate_allow` (new): Laude prints the same Schuon paragraph in two
  chapters' notes — gate 25's ≥400-char repeat witness assumes damage.

### Reading QA — 2 rounds (mandatory /proofread-epub)
- Round 1 (55 packets, 53 blind readers): **every reader on a chapter-opening
  page independently reported the same thing** — a bare folio in the prose, the
  page's footnote as body text, and an unlinked bare-digit marker. Root cause was
  an extractor bug (CropBox outside MediaBox → trim slid 24pt → drop folio
  unstripped → note-region walk broken on its first line). All 12 chapter
  openings; **10 footnotes were missing from the apparatus and no gate saw it.**
  Also confirmed: the `S.ah.īh.` transliteration garble (6 readers) and the
  `non- Buddhist` seams.
- Round 2 (52 changed packets re-read): **zero new confirmed findings.** The
  chapter-opening packets return `[]`. Every remaining finding was REFUTED
  against the print — this volume carries its own typos, all verified in-source:
  `hererodoxy`, `noumemon`, `Jehowah`, `Blakesleee`, `After after`, `that that`,
  `should not to be confused`, `hinder the recognition the Absolute`,
  `each of the great tradition`, `principal non-manifestation`, `( nafas-`,
  `ParamaŚiva`, `overcivilized`, `if one say so`, `multistratified`,
  `herebelow` (closed mid-line here, `here-below` elsewhere), and
  `323–350passim` (the index's own lost space, print-verified at 900dpi).
- **A near-miss worth recording**: fixing `non- Buddhist` by text alone would
  have rewritten sufism's `(al- Bātin)`, which print really sets with a space.
  Identical in TEXT, opposite in GEOMETRY. The render caught it; the fix moved
  to the extractor.

### Known limitation (documented, not a defect)
Index sub-entry levels are a 9pt ladder; `flow.columns` flattens level 3 into
its level-2 parent (level 3's base and level 2's turnover share x0 exactly).
Same as sufism. Text, order and locator links are intact — only the sub-entry
line structure inside a top-level entry runs on.

## Pray Without Ceasing — ed. Patrick Laude (World Wisdom, 2006) — 2026-07-14

- Source: `Pray Without Ceasing.pdf` (sha256 67d07b5a…, 250 pp, World Wisdom
  2006, Minion Pro + WorldWisdomFont). An anthology: 3 parts, 45 selections,
  108 footnotes, a 9-page 2-column index.
- Outcome: **epubcheck clean; all 26 gates PASS** (coverage 99.97%; 44 gate-24
  assertion cells). 2 proofread rounds, 33 packets, ~95k words.

### The book's defining defect: a producer that pads with phantom spaces
Four distinct shapes, ALL invisible to the gates (both engines read one stream)
and all repaired in `extract.mupdf` from glyph geometry alone:
1. **Ligature pads (2572 sites)** — a Minion ligature advances less than its own
   ink (`Th` = 10.71pt of ink, 5.34pt of advance) and a space is drawn back
   UNDER it. Text layer: `Th e Way`, `oft en`, `fi rst`, `affi  rmation` on
   nearly every page. Poppler reconstructs words from gaps and never sees it,
   so gate 2 was measuring against a witness that disagreed on 2779 words.
   Discriminator: the pad is drawn ENTIRELY BEFORE the nearest preceding
   non-space glyph. Scanning back past earlier pads catches a 3-char ligature's
   second pad; the alphabetic guard keeps BoK's 1225 kerned TOC dot leaders out.
2. **Presentation-form pads (9)** — a one-glyph `ﬁ` has no continuation glyph to
   hide behind, so the pad overlaps the ligature's OWN ink. Six words shipped
   broken through the INDEX (`Cruciﬁ ed`, `Abulafi a`, `Sufi sm`), where gate 2
   is blind (engine-disputed pages) — only the gate-18 visual sheet caught them.
3. **Zero-advance spaces (9)** — the next letter drawn at the space's own
   origin: `invoca tion`, `qual ity`, `antici pation`. Blind readers only.
4. **Inline RTL (11 glyphs)** — the producer draws a Hebrew run's CLOSING
   punctuation as a jump back out to its right, so the stream emits it BEFORE
   the Hebrew: `Yod-He-Vav-He ( ,)יהוה`. Escalated (RTL is a hard stop); the
   user chose the reorder. Only the displaced neutrals move.

**These fixes repaired SIX other corpus books** — Keys shipped `im plies`,
`es sence`; I&B `athe istic`; BoK/F&S/sufism spaced number ranges.

### Structure decisions worth remembering
- **PUA oldstyle figures**: the printed Contents sets its folios in Minion's
  PUA-encoded oldstyle digits (U+F643-F64C = 0-9), so NO line looked like a TOC
  entry and the analyzer parsed zero. Decoded by matching all 24 folios against
  the p8 render. The build now passes `glyphs.pua_map` to the folio parse.
- **Unnumbered wrapped TOC entries**: 8 of 48 entries wrap and push their folio
  onto the turnover; the folio-less first line fused into the PRIOR entry and
  the turnover shipped as a bogus one (`in the right practice`). The indent is
  the unnumbered form's marker — stored as geometry (p8) OR as leading spaces
  (p9), so test both. **This fixed book-of-knowledge too: 53 -> 64 linked
  Contents entries.**
- **The index needed `indent_threshold: 10.0`, not the analyzer's 13.5**: its
  hanging indent is 10.8pt (the body's is 18). At 13.5 every turnover read as a
  new entry and ~90 entries shipped split from their locators. Readers only.
- **Columns split by BINDING SHIFT**: gutters are computed per spec over all its
  pages, so one 240-248 spec smeared recto (x0=63) against verso (x0=36) and
  found NO gutter — the whole index would have shipped y-sorted. One spec a side.
- **Two diagrams drawn in live type** (Mir Valiuddin's latīfa sphere p160, the
  Lām-alif p158): `join_center_lines` fused each into one `<h3>`. Rastered via
  `images.figure_regions` — their meaning is the spatial arrangement.
- p1 is a full cover SPREAD (MediaBox 915pt; CropBox isolates the front) —
  `box: media` renders the CropBox, which is what a cover wants.
- Print's own pagination excludes the 2 praise leaves: the title page's drop
  folio `iii` fixes the series page as `i`. FLAGGED.

### Reading QA — 2 rounds (33 packets, ~95k words)
- Round 1 found all four phantom-space classes plus the index turnover split,
  two-line titles shipping as two h2s, and two section heads that missed
  `/center` on pages where the shift detector abstains.
- REFUTED against the print: `you should he completely detached` (p38) and
  `will still he hungry` (p39) are the **2006 edition's own typos** — both
  engines agree and the p59 render shows `he`. Pinned as `present` cells so a
  future "repair" cannot rewrite the book's words.

### Known limitations (documented, not defects)
- **Small caps ship lowercase** on 5 pages: the printed Contents' 45 titles
  (`he who thinks of me constantly`) and 3 epigraph attributions (`simone
  weil`). The font's small-cap glyphs sit at gids 94-108 of the SAME subset and
  size as the body, so no pstyle or charstyle can separate them, and rawdict
  exposes no gid. The nav (from the outline) carries proper Title Case.
- Unattested Wade-Giles/compound hyphens (`Tao-ch'o`, `Huai-kan`,
  `wu-liang-shou`, `tailor-made`): the book prints them ONCE, at the break, so
  neither the render nor the book can settle them. 6 attested ones are in
  `flow.keep_hyphens`.

## Frithjof Schuon: Life and Teachings — Aymard & Laude (SUNY Press, 2004) — 2026-07-20

Source `package/Frithjof Schuon Life and Teachings.pdf` sha256 `c0eb9f27358651…`,
211pp, Acrobat Distiller 5.0.5. Six shipped photo/painting plates, German verse,
letter-heavy biography with 500+ endnotes, year-headed bibliography, 2-col index.

### Structure decisions worth remembering
- **TOC source: printed, not outline** — the outline carries junk the print
  never had (25 A–Z index letters with no printed letter headings, a phantom
  Notes 'CHAPTER 4' subhead entry, half-title/Contents self-entries). The 13
  printed entries all have real headings; the nav is heading-built either way.
- **Chapter kickers joined into the h1** ('CHAPTER ONE' + title → one h1 via
  flow.overrides join, keys-to-the-beyond precedent): the splitter fires per
  paragraph, so an h2 kicker before the h1 orphans at the previous file's tail.
  Ditto 'APPENDIX 1/2' + 'Frithjof Schuon'.
- **Endnote numbers are RIGHT-ALIGNED** — 1/2/3-digit markers sit at three
  stops (51.6/46.6/44.6). New `blocks.lists.stops:` (explicit, RAW x0) carries
  the judgment: the cluster filter drops the small 1-digit cluster, and
  partitioning pages into per-stop specs severed every note wrapping a spec
  boundary (round-2 readers found notes 3/12/56/89/96/13 split mid-sentence).
  tol 2.5 NOT 2: the pp.179-182 wide-gutter turnovers are exactly 2.0pt off
  the hang column and float epsilon pushed them out.
- **Bibliography = marker:hang** (I&B precedent) with 14 render-verified
  `break` overrides: editions print one per line, but coincidental ragged-edge
  pairs misderive block_right so the short-line break signal never fires.
- **Photo plates are TEXT-LESS figure_regions** — no line carries the region,
  so the in-loop Figure emission never fired and all six plates shipped as
  orphaned images (no gate caught it; gate 5 listed them only as info). Code
  fix: emit in place with the caption line(s) as live paragraphs beside the
  figure. Print order kept (gate 25's monotonic witness is the doctrine) — the
  running sentence around a plate stays split exactly as the page turn splits it.
- The Notes ch.4 subhead is letter-spaced caps at the hang column and too wide
  for the centered detector — absorbed into note 64 until a class:prose
  override; it ships as a plain paragraph (role: overrides still hang-join).

### Pipeline fixes landed here (all with unit tests; corpus re-verified)
1. blockshapes.quote_shape_runs: a quote candidate's OWN x1 must fit the quote
   measure — justified_rights hands body first-lines the block's clustered
   margin, and ~20 intro/exit lines shipped inside blockquotes. Healed PWC (9
   sites its own proofread missed) and I&B (1).
2. flowbuilder: text-less figure_regions emit their Figure + caption in place.
3. flowbuilder: marker:hang specs treat deeper-than-hang lines as turnovers
   (list_sub split bibliography wraps mid-word: 'Ein-'/'führung').
4. flowbuilder: columned-entry test tightened to min(indent_threshold, 6) —
   this index's 9pt hanging turnovers all split as entries at 15.
5. flowbuilder: blank-page anchors flush before the printed-TOC run (pagelist
   'vi' shipped after 'vii'); QA runner now runs link_index_locators so gate
   22's re-derived queue matches the build's (a locator adjudication read
   stale); emit/ordercheck contents matchers fold punctuation and match
   enumeration-stripped titles (kicker-joined h1s), tie-broken by printed page.
6. textfix: SUSPENDED HYPHENS before bare conjunctions (and/or/und/oder/et/ou)
   survive both dehyphenation paths — 'pseudo- and neoesoterism', 'Tage- und
   Nächtebuch' had fused to 'pseudoand'/'Tageund'.

### Reading QA — 3 rounds (35 packets, ~85k words, 31 readers + 8 verifiers)
- Round 1: ~90 findings → the 5 systemic roots above + keep_hyphens
  (so-called, quasi-secretary, vis-à-vis, jîvan-mukta, Japanese-like,
  light-colored), 4 absorbed colon-intro lines (class:prose), copyright-page
  joins, series-page break, p.74 heading role:h3, quote spec +pp.65-66/89.
- Round 3: ZERO new confirmed findings. 9 gate-24 cells seeded.
- REFUTED against print (the book's own quirks, preserved verbatim): 'is not
  be interpreted', 'in iself', 'never been lost', 'allow it reach', 'not all
  mysterious', 'eternel present', 'properly so which', 'even more that',
  'Bloomingon', 'Theospohical', 'Editons', 'Sapientae', 'dansle', '221.The',
  'S.Ibrahîm', 'L' Oeil', '1997(poems', index '515'/'x1'/'19–10'/'120 142'/
  '162–3', spaced opening quotes ('" the/In/If/he/isolated/to see'), spaced
  noterefs ('nature 4', '1934. 23', '(the Praised) 32'), reversed close quote
  p.60, unclosed quotes pp.73/88/166, missing em dash p.66, unclosed paren
  p.64. The blind readers' noteref-anomaly chorus (bare digits) is the
  packets flattening <sup> — markers ship as superscripts; policy: none by
  design (all notes are endnotes, unlinked as printed).

### QA outcome
epubcheck clean; qa Overall: PASS (26 gates; 447 unit tests); visual gate 18
graded across 14 sheets ×2 passes, 6 figures dHash distance 0; corpus 10/10
QA PASS with baseline updated. Flagged for human review: urn:uuid identifier
(no ebook ISBN printed), cover from PDF p.1 render, kicker-joined h1 texts,
plate-interrupted sentences kept in print order.

## The Mystics of Islam — Reynold A. Nicholson (World Wisdom, 2002) — 2026-07-20

*(Ledger entry reconstructed 2026-07-21 from the tracked artifacts — book.yaml,
build metrics, commit 638e141 — the conversion session predates it.)*

Source: `The Mystics of Islam (2003).pdf`, sha256 `d9515c30…f805403`, 145 pages
(printed folio 1 = p14). A quotation- and verse-dense Sufi anthology: nearly the whole
body (pp.14–133) is covered by ONE blocks.quotes spec (17pt insets, 10pt justified
quotations), with 44 verse pages across two specs (base 17.2, turns 34.1, mixed
convention) and two lists (numbered stages of illumination p.56; bibliography hangs
pp.134–137).

### Structure judgments
- Printed Contents (p.6) definitive; outline is flat and padded with non-heading
  Series/Copyright bookmarks → `nav_depth: 1`, rebuild, strip page numbers.
- Footnotes: mixed markers — 30 numbered notes + three publisher's asterisk notes.
- No PUA, no embedded fonts, no figure pages/regions; one adjudication
  (embedded-image-uncovered p.4 — title-page colophon, all semantic text live).
- **The heaviest per-line classification in the corpus**: 486 flow.overrides
  (335/100pp — the previous high was I&B at 78.8): 401 `class:quote` (short quoted
  sayings the justified-inset witness can't see), 67 `class:verse`, 10 `class:prose`.
  The commit also landed semantic-block code fixes (blockshapes/flowbuilder) with
  119 lines of new flow tests.

### Flow metrics (build_metrics.json)
895 quote lines / 155 quote paras / 75 runs; 447 verse lines / 57 groups / 55 stanzas;
24 list items; 33 noterefs; 394 dehyphenated; 6 column pages (430 lines); 9 keep_hyphens.

### QA outcome
epubcheck clean; qa Overall: PASS. Gate-24 fixture is an authored `[]` (no
print-verified fixes yet — proofread findings land cells as they come). Baseline entry
seeded 2026-07-21 with the review-#90 reseed; corpus 11/11 QA PASS.
