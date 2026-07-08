# Conversion ledger

One entry per finished conversion: date, source PDF (sha256), decisions worth remembering,
QA outcome, and anything the next conversion should learn from.

(No conversions yet — the four validation books land here as they finish:
book-of-knowledge, harmonious-unity, islam-and-buddhism, me-and-rumi.)

## book-of-knowledge — 2026-07-07

- Source: `adult-The_Book_of_Knowledge_cover and TOC links.pdf` (sha256 48ea4f71…, InDesign CS6/2015, 338 pp).
- Result: build `epubcheck: clean`; QA `Overall: PASS` (coverage 99.21%, 670/670 notes placed, 323-entry page-list, byte-reproducible).
- Judgments worth remembering:
  - 23 Honorifics-font PUA glyphs identified from 350dpi crops against the book's own
    legend (Publisher's Note p.26) and rendered as parenthesized English readings —
    incl. raḥimahu llāh forms the legend omits, dual forms (Ibn ʿAbbās, Ibn Ḥanbal+Sufyān),
    and a full basmala calligraphy line. FLAG: publisher may prefer Arabic glyphs + font.
  - eBook ISBN 978-1-941610-21-3 printed on the copyright page — no uuid fallback needed.
  - Two-column Index (pp.324–336) EXCLUDED (column-interleaved extraction; page-list keeps
    print-page navigation working) + image-only closing page 338. FLAG for publisher.
  - 4 flow.overrides: hanging-indent turnovers (numbered list + Qurʾān quotes) the indent
    rule misread as paragraph starts.
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
