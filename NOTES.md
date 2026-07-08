# Engineering notes

Field notes, verified facts, and lessons. Read before nontrivial changes; keep current.
(Seeded from the planning session that designed this pipeline, 2026-07-07.)

## PDF field notes (verified on the four test books)

- **Page boxes vary per page**; read them per page, never document-level. Printer slug
  lines (".indd", "Page iv", date/time) sit OUTSIDE the TrimBox on older Fons Vitae PDFs
  (Book of Knowledge, Me and Rumi) but poppler/PyMuPDF still extract them → clip lines by
  TrimBox and keep the clipped lines as evidence.
- **/PageLabels are usually broken**: of the four test books, only Harmonious Unity's are
  clean. Book of Knowledge skips v–vi; Me and Rumi labels its cover spread "i" (off-by-one);
  Islam and Buddhism uses InDesign section labels ("Sec1:7"). The folio-vs-label agreement
  check runs on every book; `label_source: printed-folios` is a routine tool.
- **PUA codepoints** (U+E000–F8FF) come from symbol fonts ("Honorifics" → U+F048 for the
  ﷺ honorific). Every PUA char needs an agent-verified substitution recorded in
  glyphs.pua_map with a "verified on p.N render" note. Ornament dividers likewise.
- **Outline titles can carry trailing \x00 padding** (BoK, InDesign CS6) — strip NULs and
  whitespace.
- **Lost spaces in old prepress PDFs** (Me and Rumi, Creo Normalizer, no ToUnicode):
  `say,"If I`, `Erzincan.They`. Deterministic restore_spaces (initials-protected) repairs
  the common patterns; count every insertion; residuals escalate — never hand-edit text.
- **Small caps are separate fonts** (Bembo-SC, Gentium-SC700, TimesNewRomanPSMT-SC700).
  Text extracts with correct casing; render with a font-level smallcaps charstyle flag,
  never case-transform.
- **Drop caps extract as detached oversized 1–2 char lines** ("A" / "lmost…", BoK
  Foreword). Flow reattaches them; paragraph gets class first-dropcap.
- **Vertical CJK extracts column-interleaved** (Harmonious Unity Liu Zhi pages). v1 policy:
  those pages become figure pages (raster + alt), like idml2epub did; inline CJK mixed into
  Latin front matter stays live text with Noto substitutes.
- **Link annotations**: filter to internal GoTo; URI links exist in the wild (BoK has 4).
- Engine cross-check: PyMuPDF (primary) vs poppler pdftotext per-page similarity is the
  extraction-confidence signal. Engines witness, never co-author: disagreement flags a page
  for render review; nothing auto-merges. The poppler witness MUST be cropped to the trim
  box (`PdfDoc.trim_crop_box`, MediaBox top-left coords) — poppler reads the MediaBox, so
  uncropped it sees slug lines on otherwise-empty pages and scores them 0 vs MuPDF's
  correctly-empty CropBox view.
- **Internal TOC links are LINK_NAMED (kind 4), not LINK_GOTO** in all four test books
  (InDesign named destinations); PyMuPDF reports the target as a 1-BASED page-number
  STRING (verified vs pypdf). Handle both kinds.
- **Two-column back matter (BoK index pp. ~322–337) interleaves under y-sorted line
  order** — the agreement score flags exactly those pages. The extract-stage baseline
  merge (needed to reunite heading+folio fragments) also fuses same-baseline runs across
  columns; runs keep their bboxes, so a column-aware flow pass can re-split at the column
  gap for pages the agent marks as columned. Until that exists, multi-column pages
  escalate per the skill.
- PyMuPDF's page space is CropBox-anchored: slug text outside the CropBox never appears
  in get_text at all (poppler differs). The TrimBox clip only fires when trim ⊂ crop.

## Verification baselines

- Smoke counts (extract): BoK 338 pp / 79 outline / 83 GoTo links; Me and Rumi 441 / 0 / 32;
  Islam and Buddhism 170 / 0 / 0; Harmonious Unity 152 / 70 / 68.
- Coverage gate: ≥99% vs poppler ground truth (footnote bodies stripped from ground truth
  per page — they move to endnotes; gate 3 verifies each note on its page and guards the
  circularity). The itemized missing-segment list is the real audit.

## Refinement loop (inherited from idml2epub)

- Preserve init's draft (book.draft.yaml); the draft-vs-final diff measures heuristic quality.
- A correction seen in two books becomes a heuristic; a misfiring heuristic becomes a code
  fix + unit test; every human-found gate gap must become a check or a written reason.
- Reproducibility: fixed zip timestamps, uuid5 identifier (`pdf2epub:{slug}` seed),
  SOURCE_DATE_EPOCH pinned in core/fonts.py; wipe build/oebps each build (stale files ship).
  Reproducibility is scoped to the same toolchain — record PyMuPDF + poppler versions in
  the build log.

## Open items

- Live vertical-CJK flow (v2; figure pages for now).
- RTL live text: detect + warn + escalate (unimplemented, same as idml2epub).
- OCR for image-only pages: out of scope; such pages ship as figures when the agent can
  verify content from the render, else escalate.
- Multi-column body text: detected + escalated, not converted.

## 2026-07-08 — false-centered body lines (user-reported, all four books)

A body-size line starting at the paragraph indent whose LENGTH happens to
land its midpoint near column center is a PARAGRAPH, not a centered line
(BoK p.206 'This should suffice…': x0 = indent, center offset 1.6pt; print
shows an ordinary indented paragraph; the EPUB rendered it as a centered h3
and put it in the nav). Fixes promoted to code + config doctrine:
- line_pstyle: body-size lines need BOTH insets >= 12% of column width to
  be '/center'; display-size lines keep the loose rule (wide heads are real).
- Body-size '/center' clusters map to role p (the synthetic catalog still
  emits text-align:center) — heading roles are for structure, not for
  every visually centered line; this also stops nav pollution.
- Audit tool: scan emitted h1-h3 for sentence-like text (>55 chars ending
  in punctuation) — caught MR's centered aphorism quotes mis-roled as h3.
- nbsp+space does NOT collapse in HTML rendering: glyph substitutions after
  space-trailing runs need cross-run space collapsing (plain double spaces
  are harmless — readers collapse them).

## Session lessons for future agents (2026-07-08)

- **Unicode literals don't survive the toolchain**: PUA chars written literally
  in heredocs/scripts/YAML get silently stripped (a `[-]` regex
  written with literal chars became `[-]`, matching hyphens). Always write
  `\uXXXX` escapes and VERIFY by parsing (yaml.safe_load + assert ordinals)
  before building on the file.
- **When a metric refuses to move across several fixes, stop hypothesizing and
  dump the actual data at the seam.** The I&B hyphen count sat at exactly 83
  through four plausible fixes; the answer (paragraph broken mid-word at a
  roman/italic boundary) was visible in one raw-bytes dump of the flow items.
  Same discipline solved BoK's 0-noterefs (tab-separated markers) and the
  coverage cascade (bounded find window).
- **QA text extraction shape matters**: EpubDoc.text()'s space-joined itertext
  fabricates 'no- dharma' artifacts across inline tags — join inline content
  with '', blocks with ' '. And nbsp+space does NOT collapse in renderers;
  plain double spaces do.
- **Trust structural invariants over similarity thresholds for repairs**:
  the shifted-CMap repair (+0x1D) was provable from 'WKH'→'the', space→\x03,
  digits→\x14-range simultaneously; a fuzzy approach would have guessed.
- **The engine-agreement score pays for itself**: it located the two-column
  index pages, the vertical-CJK section, AND the broken-CMap essay before any
  human saw them. Text both engines agree on can still be wrong only when the
  source's own ToUnicode lies identically — that's what print-render
  verification is for.
- **Standard post-build audit**: scan emitted h1–h3 for sentence-like text
  (>55 chars ending in punctuation). It found every false-heading class the
  user's screenshot pointed at, plus one more (MR aphorism quotes).

## Typographic fidelity QA — gates 13-18 (2026-07-08)

Design record for the five deterministic typography gates + the visual
sampler; regression baselines below are the acceptance contract.

- **Architecture**: EPUB side reads the SHIPPED artifact (css/styles.css via
  core/qa_cssresolve, markup sliced per source page via core/qa_pageslice);
  PDF side reads raw extract-IR geometry through FlowResult.para_lines
  provenance. Anchor pairing is ORDINAL (k-th pagebreak == k-th in-flow page)
  — folio labels collide across roman/arabic; count mismatch degrades every
  check to one info line (fail-safe, never false-fires).
- **Centering witness ≠ line_pstyle** (that was the buggy rule): block-level,
  one-directional (verifies claims only), stop-veto + midpoint-agreement.
  Neutrality means flush at BOTH edges (≤6pt) — width-based neutrality would
  have exonerated BoK p.206 (91%-wide line starting at the indent). Accept
  region ⊇ current line_pstyle's /center region for col_w ≥ 180pt.
- **Gate 17 compares structure only (size bucket + class-centering)**:
  per-paragraph italic FRACTIONS are irreducibly noisy across witnesses (PUA
  readings without lang tags dilute one denominator; I&B bibliography ~50%,
  BoK Qurʾān quotes ~0.75 knife-edge every threshold). Graded emphasis is
  gate 15's job (permanently informational; would-FAIL at ≥2 page findings
  or book |Δfrac| > 0.03).
- **Line matcher hygiene** (gates 14/16): exclude the flow's own stripped
  furniture (a heading's running-head echo on the NEXT page fuses with the
  folio and matches its text); tiny blocks (<8 chars) match exact-only
  (partial_ratio aligns the SHORTER side — any line containing '1' scores
  100 vs a chapter numeral); fuzzy requires the line to fit INSIDE the block
  (+12 chars slack); space-insensitive matching for MR's prepress-lost
  spaces (unmatched dropped 514→239); duplicate-instance fallback (MR p.70:
  same aphorism printed as a left verse line AND a centered head — any
  single full-coverage centered instance sustains the claim).
- **TRUE POSITIVES the gates found in shipped, Overall:PASS books** (both
  fixed + rebuilt, all four books): (1) class-level `font-style: italic` from
  italic-family pstyles swept the roman runs of MIXED paragraphs along (BoK
  p.xx Qurʾān-quote paragraph rendered all-italic; MR/I&B too) — styles_synth
  no longer emits font-style from the family name; run-level <i> covers 100%
  of italic-family chars on the corpus (verified against extract IRs), and
  test_styles_synth pins the rule. (2) I&B shipped a GARBLED h3
  '%LEOLRJUDSK\' (= 'Bibliography', -0x1D shifted CMap) into body + nav —
  single-WORD shifted lines carry no \x03 space marker, so is_shifted_run
  gained a word-shape detector (whole line in the shifted range AND
  un-shifting yields a real word; real caps/digits shift to junk, so
  precision holds — test_flow covers both directions).
- **Regression matrix (acceptance contract, final code)**: pre-fix EPUBs at
  3cfca48 → gate 14 fires 42/27/68/87 (BoK/HU/I&B/MR), gate 16 fires 56+9 /
  29+2 / 69+33 / 149+38 (suspects + h3 audit), gate 17 fires 43/16/39/65
  pages, gate 15 advises on the 3 books with italic clusters. Current
  builds: all five gates SILENT on all four books. GATING = {13, 14, 16, 17}
  flipped on that evidence; any future threshold tuning must keep every
  expected-FIRE cell firing.
- **Visual QA (gate 18, `qa --visual`)**: CDP over system google-chrome
  (websocket-client; PUT /json/new since Chrome 111;
  --allow-file-access-from-files for file:// css/font subresources;
  Page.captureScreenshot captureBeyondViewport + clip does arbitrary-height
  slices with no scrolling; document.fonts.ready before offsets). Chrome
  launch is ~0.2s here — cheap enough to run per book. Sampling is
  phenomenon-first (every pstyle cluster, rarest first; PUA/dropcap/figure/
  disputed firsts; ≥3 seeded-random from sha256) — errors are systematic per
  cluster, so one sample per phenomenon beats volume. dHash hand-rolled
  (10 lines) instead of an imagehash dep. Pillow can't shape multi-char
  Arabic without libraqm — glyph pairs note 'shaping approximate'.

## Justified-block last lines: the second false-centering class (2026-07-08)

User-reported (BoK p.185 'may be categorized under ten headings:', p.193 'be
the first of your people to rise to his service.'): the short LAST line of a
justified block whose left edge is inset — quote indent (x0=108) or drop-cap
wrap (x0=122) — clears the 21fc8ed 12%-inset floor on BOTH sides whenever its
midpoint lands near column center, so line_pstyle marked it /center and it
broke out as its own centered paragraph. Four instances in BoK (also p.184,
p.227 — same shape, unreported); zero in the other three books.

- Fix promoted to code doctrine: `continues_justified_block` (prev raw line
  same x0 ±2pt, x1 ≥ col_right−6, one normal leading above) → a body-size
  line continuing a justified block is NEVER /center, whatever its midpoint.
  Shared by line_pstyle (all call sites now pass the raw predecessor) and
  gate 14's witness (candidates carry (line, prev) pairs).
- Why gate 14 missed it: the witness's stop-veto was CAPPED below the
  deep-inset floor to honor the superset doctrine ('never fire on what
  line_pstyle accepts') — x0=108/122 are massively attested stops, but the
  cap excluded them. **The doctrine protected the buggy rule.** Lesson: a
  witness that by construction cannot disagree with the code it audits
  verifies consistency, not truth — every witness needs at least one
  evidence path the audited rule does not consult (here: the predecessor
  line's geometry, which line_pstyle never looked at).
- Rejected fix shape for the record: a blunt 'x0 at any attested stop' veto
  would have de-centered 21 BoK + 35 MR lines including GENUINE title-page
  centering and MR verse lines — the predecessor-line signal is what makes
  the rule surgical (4 hits, all true positives).
