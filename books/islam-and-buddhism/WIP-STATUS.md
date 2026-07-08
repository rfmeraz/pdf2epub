# islam-and-buddhism: IN PROGRESS (do not ship)

State: epubcheck clean; QA gates 1,3(placement),4,5,8,10 pass.
Remaining FAILs and diagnosis so far:

- gate 9 (83 vs source 16): NOT the QA space-join artifact (fixed via
  _doc_text) and NOT in raw xhtml scans (only 2 found by tag-strip scan).
  Next: dump pdfchecks.hyphen_residue matches ON all_text_norm with context —
  suspect normalize() interaction or notes-side seams from the cmap-repaired
  section (in-run 'word- word' where next word starts uppercase, skipped by
  the lower-only collapse in repair_shifted_cmap).
- gate 2 (98.05%): missing segments concentrated on note-heavy pages 28-32
  (13 gt-excision misses) + essay section. Interacts with gate 9's cause.
- gates 6/7 (25/41, 29/41): subsection heads now exist as h3 via 36 generated
  flow.overrides (role:h3 + break pairs, see book.yaml). Remaining misses:
  check whether the missing titles' overrides landed on continuation pages
  (duplicate standalone lines matched on non-heading pages?) or folio labels
  still off by one in the essay section (printed-folios backfill).
- Cover renders from p.1 (done). Print ISBN only (uuid flagged).

All pipeline-level fixes from this book are already committed (shifted-CMap
repair mechanism, printed-folio backfill, block-aware QA text, title/toc
leak exemptions). What remains is book-level adjudication.
