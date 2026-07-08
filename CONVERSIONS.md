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
