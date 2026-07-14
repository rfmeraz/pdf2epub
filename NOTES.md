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
- **Columned back matter (BoK indexes pp.322–336) interleaves under y-sorted line
  order** — the agreement score flags exactly those pages. The extract-stage baseline
  merge (needed to reunite heading+folio fragments) also fuses same-baseline runs across
  columns; runs keep their bboxes, so `flow.columns` re-splits at the section's gutters
  and reads column-by-column (see the 2026-07-08 design entry below). Columned body
  PROSE still escalates per the skill.
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
- Multi-column body PROSE: detected + escalated, not converted (tabular
  back matter converts via flow.columns since 2026-07-08).
- MR comma+LOWERCASE fusions (`Now,however`, `another,higher state`) still
  ship: outside restore_spaces' before-capital doctrine and gate 11's
  pattern family. A `[a-z],[a-z]` repair needs its own print-verification
  pass before extending a text-changing rule (2026-07-09 pass deliberately
  deferred it).
- HU title pages carry two invisible U+FEFF-only paragraphs (BOM prepress
  artifacts; cosmetically harmless, stripped from QA text by normalize).

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

## Proofread harness: first acceptance run (2026-07-08, I&B)

21 blind readers over 24 packets returned 328 findings; root-cause work
collapsed them into a handful of systemic classes. Lessons:

- **The joiner lacked the classic 'ragged line ends its paragraph' rule.**
  A justified line only ends visibly short when its paragraph ends there —
  quote→commentary fusions (83 findings), flattened verse/bullets/signatures
  (35), all one missing rule: prev line ends short (x1 < col_right −
  max(24pt, 8% col)) and the next starts at/left of the same x0 → break.
  Cross-page mirror: continuation is the default; break only on prev-short
  or full-line + genuine indent (comparing the indent against the previous
  page's last-line x0 alone split quote blocks whose insets differ by 9pt).
- **'Short line' must measure against the BLOCK's margin, not the column's**
  (user-reported 2026-07-09: I&B Qurʾān quotes 'broken across lines in
  unpredictable ways'). A block quote is inset on BOTH sides, so its justified
  lines end ~18pt short of the body col_right — but the prev_short test only
  corrected eff_right for LEFT shift (recto/verso), never a right inset, so
  every full quote line read as ragged and the quote shattered line by line
  (I&B p.151's al-Jūzjānī quote: 23 fragments; the roman Dalai Lama blocks on
  p.51 too — block quotes are NOT always italic). The 18pt threshold sat a
  hair inside the quote's edge (344.76 vs a 345 cutoff), so lines flipped
  break/join on sub-point jitter — hence 'unpredictable'. Fix (`_assign_block_right`):
  a run of ≥2 consecutive same-inset lines whose right edges cluster to
  sub-point precision is JUSTIFIED; that shared edge is the block's OWN right
  margin, used in prev_short via `_L.block_right`. Ragged verse (line widths
  scatter by whole points) yields no cluster → None → falls back to col_right,
  so its meaningful line breaks survive (the discriminator that keeps
  test_short_line_ends_paragraph's verse block broken). The change only ever
  lowers the short-cutoff (block_right ≤ col_right) → it can only join MORE,
  never split a currently-joined line. Baseline: I&B flow 1218 → 896 blocks
  (roman quote paras 893→650, italic 129→53), all inset block quotes; build
  epubcheck-clean, qa Overall PASS (verified past the separate pre-existing
  p.154 folio-'129' @10 leak).
- **Page-scoped role_overrides are a blunt instrument**: a mislabeled page
  number ({page: 6, role: p} annotated 'copyright' sitting on the CONTENTS
  page) silently wiped 36 toc-entry roles. Invisible to every gate because
  gate 7 checks nav.xhtml (built from source entries), never the in-body
  Contents. Adjudicate override page numbers against `pdf2epub lines`.
- **The emit contents-gather stopped at the first non-entry paragraph** —
  a mid-TOC subtitle ('Common Ground…', 'Contents, continued') ended the
  gather and every later entry emitted as plain text. Now gathers the whole
  run in flow order with interludes kept in place.
- **Facsimile plates**: I&B's Dalai Lama foreword is a full-page IMAGE both
  engines are blind to — no gate can see 'missing' text that never extracts.
  figure_pages gained keep_text (plate + typeset heading both ship); packets
  now carry `{figure} <alt>` lines so blind readers don't report plates as
  truncated text.
- **Compound hyphens**: lower-only dehyphenation destroyed self-/all-
  compounds ('selfevident', 'allembracing'). Fix: a SHORT whole-word prefix
  list (self, all, half, well, ill, cross) keeps the hyphen; 'love-'/'thought-'
  can't join the list (love-/ly, thought-/ful are ordinary splits) — lexicon
  work if ever needed.
- **Round-2 spot reads confirm the classes cleared** (packet-level findings
  dropped ~6-17 → 0-4, remainder mostly as-printed suspects). Old-EPUB
  regression detection PRESERVED after all join changes (old BoK: 11b=18,
  g14=46, g16=56+9, g17=48).
- **HANDOFF (CLOSED 2026-07-09 — see the shifted-CMap closure entry below;
  the font-scoped design proved IMPOSSIBLE on this PDF)**:
  shifted-CMap coverage on isolated italic runs ('=' shifted spaces,
  J-decoded hyphens, VǌUDK/6DKƯK transliterations, ³´« quote glyphs, FFFD
  note prefixes) — design: font-scoped repair (config lists broken font
  families; repair ALL their runs, not text-shape detection); essay-page
  footnote-region failures (inline '12. See…' notes + folio leaks mid-prose);
  fused/possibly-missing endnotes (printed 12-15); dash/slash seam-space
  class needs per-instance print checks.

## flow.columns + gate 19 (Qurʾānic citations) — 2026-07-08

User-reported: BoK shipped its 'Qurʾānic Verses Cited' pages (322-323)
column-INTERLEAVED. Root cause chain worth remembering: the original
conversion excluded the general index (324-336) for exactly this hazard but
missed that the verse index sat on two more columned pages OUTSIDE that
range; and no gate could see it — engine-disputed pages (agreement < 90)
leave gate 2's ground truth, which is precisely what columned pages are.
A whole failure class (columned back matter) lived in the coverage witness's
blind spot.

- **flow.columns design** (the NOTES seed above, now built): gutters are
  computed per SPEC over the raw lines of ALL its pages, not per page — a
  single sparse page (p.323, 15 lines) leaves the whitespace channel between
  an entry and its right-aligned page numbers as the widest low-coverage
  strip; aggregated over the section that channel fills in while true
  gutters stay empty. A gutter must be interior (rejects the folio margin),
  ≥6pt, low-coverage (≤6% of lines may cross: a centered heading does), and
  hugged on its right by column-START runs (≥20% of lines; rejects the
  ragged right edge of index columns). Split points sit 2pt left of the
  gutter's RIGHT edge (column starts hug it; the left boundary is fuzzy).
  A run crossing a split = full-width spanner (the 'Index' heading): flush
  columns read so far, emit in place, new band. Entry paragraphing on
  columned pages is by indent alone (column-left = new entry, deeper =
  hanging-indent turnover joins — BoK turnovers sit +21..31pt, threshold
  is flow.indent_threshold); the ordinary joiner rules don't apply (tab-
  leader entries END at the column right edge, so prev_short never fires).
  Footnote-region detection is skipped on columned pages (an all-9pt page
  would read as one giant note region continuing the previous page's notes).
  RAW line indexes are preserved on split lines: overrides/para_lines
  provenance address the fused source line (coarse but documented).
- **Gate 19**: a Qurʾānic verses index is the one apparatus with a fully
  checkable external structure — 114 suras, fixed Ḥafṣ/Kufan verse counts
  (sum 6236, pinned by test), monotone (sura, verse) entry order, page refs
  ⊆ page-list labels. Interleaving produces impossible refs ('9318:67')
  and order breaks. Regression cell: the OLD shipped BoK EPUB fires 131
  defects; the fixed build is silent (132 entries, 0 defects). Heading scan
  requires the Qurʾān to be NAMED (a bare 'Verses Cited' could index a
  scripture this table can't judge).
- **Gate 6 lesson**: re-including the indexes surfaced a matcher bug — the
  outline's 'Indexes' GROUPING bookmark (no printed heading of its own)
  fuzzy-stole the 'Index' heading from the exact-titled entry two pages
  later. Fix: exact-title entries claim their headings first; grouping
  bookmarks fall through to an info note. (qa_ordercheck, unit-tested.)
- Verified against print renders of pp.322 and 330 entry-by-entry (3-col
  verse index incl. the p.322→323 seam 35:8→35:28; 2-col index incl. the
  'knowledge' sub-entry run where italic 'kalām' sorts WITHIN the
  sub-entries, and the joined '189' turnover of 'of [practical] conduct').
  BoK rebuilt: epubcheck clean, qa Overall: PASS, coverage 99.06%,
  page-list 321→336 labels.

## figure_regions + the Arabic-glyph variant — 2026-07-09

User-reported: the Publisher's Note legend (p.26) shipped scrambled. It is a
TRUE 3-column table (Arabic glyph | English meaning | Usage) — row
correspondence is the content, so neither the line joiner nor flow.columns
(column-major by design) can represent it. **Lesson: presence-based coverage
is blind to ordering damage** — p.26 scores agreement 91.1, all the cell text
was 'covered', and every gate passed while the page read as nonsense. The
ordering witnesses are the proofread pass and human eyes.

- **images.figure_regions**: a rect on a page ships as a cropped raster
  figure — the safe path for true tables/diagrams embedded in prose. Rect is
  recorded in extract-space (top-origin page coords — the same space
  get_pixmap's clip reads; take it from `pdf2epub lines` / extract IR
  geometry, then check the crop for slivers of neighboring lines: descenders
  reach ~4pt below a line's nominal bottom). alt is REQUIRED (config error
  without it) and written from the render. Region lines leave the flow and
  the gt: excision matches poppler lines against the region lines' whole
  texts AND per-run texts (poppler splits what MuPDF fuses), plus a
  token-subset fallback (poppler also fuses what MuPDF splits). Region lines
  are exempt from the footnote-region scan (a bottom-of-page table would
  read as a note block). Itemized in gate 2 as 'figure-region chars'.
- **Arabic-glyph variant (book.arabic.yaml)**: same judgments as book.yaml,
  three deltas — pua_map chars become Arabic (U+FDFA ṣallā…, U+FDFD basmala
  ligatures where Unicode has them; spelled phrases otherwise), every char
  rule gains lang: ar, fonts.embed gains OFL Amiri (system file, subset
  48KB). The lang plumbing (span.ar + :lang(ar) stack) was already inherited
  from idml2epub. The map stage's RTL warning fires (by design, doctrine
  says escalate): ADJUDICATED — the user requested this variant; runs are
  short inline strong-RTL phrases inside LTR paragraphs, which the bidi
  algorithm renders correctly with no dir attrs; verified in Chrome renders
  (inline ﷺ placement, multi-word سبحانه وتعالى order, basmala line). RTL
  PARAGRAPHS remain a hard stop.
- **Variant-config pattern**: a second book.yaml beside the first (same
  workspace, same package/, distinct output.slug) → both EPUBs live in
  build/ and only they are tracked. qa_report.md/qa.json are per-run
  (last-run-wins in the shared build dir) — record per-variant outcomes in
  CONVERSIONS.md. Generate variant configs programmatically and VERIFY by
  parse + codepoint assertions (the unicode-literal toolchain hazard).

## Cross-run lost spaces + gate 11 promoted — 2026-07-09

MR shipped 62 fused seams (`believer.This`, `aiming.When`) invisible to a
raw-XHTML grep: they sit at roman/italic TextRun boundaries and only appear
when inline content is joined with '' (the QA text shape). Root cause:
restore_spaces runs PER RUN inside _apply_textfix; a fusion at a run seam is
never seen by it.

- Fix: `restore_space_seam` (textfix) applies the same patterns to a 3+3-char
  window across every adjacent-TextRun seam; the space lands in the earlier
  run so formatting survives. Called at close_para and note-close
  (`_restore_cross_run_spaces`), gated on flow.restore_spaces, counted as
  spaces-restored-crossrun (MR: 85). InlinePageBreak items are transparent
  to both seam walkers.
- The rebuilt MR still failed the promoted gate at 6: all `,"X` residuals
  whose PRECEDING char is `]`/`)`/digit (`[about me],"This`, `(216),"We`,
  `86:9,"On`) — the lowercase-before guard excluded them from repair while
  the gate's own pattern counted them. Safe relaxation promoted to code:
  bracket/paren/digit + `,`/`.` + DOUBLE QUOTE + capital is never legitimate
  prose (the mandatory quote keeps initials and numerics out) —
  _SPACE_AFTER_BRACKET, +3 repairs, MR → 0. **A detector wider than its
  repair leaves exactly the differences shipping**; keep the pair in sync.
- Gate 11 promotion evidence (2026-07-09): old shipped EPUBs fire
  MR=62 / BoK=0 / BoK-arabic=0 / HU=0 / I&B=0; rebuilt MR fires 0.
  Zero-tolerance with a render-verified `qa.lost_space_allow` escape
  (exact snippet + note; stale entries fail the gate).

## I&B shifted-CMap closure + gate 20 (garble residue) — 2026-07-09

The NOTES 2026-07-08 handoff prescribed font-scoped repair (config lists
broken families). **That design is dead — negative result recorded**:
PyMuPDF reports IDENTICAL font names (TimesNewRomanPSMT/-ItalicMT, no
subset prefixes) on broken and healthy pages, and the essay pp.138-168
interleave 1489 healthy runs with 404 shifted runs — any blanket scope
repair corrupts healthy text. What actually shipped garble, and the fixes:

- ³´²«Ɩ residue (19+ lines): chars ≥0x60 pass repair_shifted_cmap untouched
  — they were MISSING HIGHMAP ENTRIES, config-only. Render-verified:
  ³→" ´→" (p.138), ²→— (p.143), «→… (p.151), Ɩ→Ā (p.159 Ibn ʿĀbidīn).
- µ/¶ were mapped ʿ/ʾ but the p.160 render proves they are the broken
  subset's LEFT/RIGHT SINGLE QUOTE glyphs, used for quotes AND ayn/hamza —
  exactly as the healthy pages extract them (U+2018/2019). Remapped to the
  book's own convention; the old mapping shipped modifier letters as
  quotation punctuation.
- One run book-wide ('VDED¶' p.140 = sabaʾ) evaded is_shifted_run (¶ outside
  the shifted range): the word-shape detector is now highmap-aware (≥4
  in-range chars whose un-shift alone is a real word + ≥1 highmap char +
  full coverage). Same precision bar; all old negatives pinned.
- U+FFFD is a SEPARATE phenomenon (pp.36-47 notes + p.98 body, 474 chars,
  NOT the essay): MuPDF's unmapped-glyph placeholder carries zero
  information, so only page-scoped render-adjudicated replacement is
  deterministic — `glyphs.fffd_repairs` {pages, replace, note REQUIRED},
  stale entries are build errors, unconfigured survivors warn
  (fffd-unrepaired). Renders show NO visible content at all 8 spots
  (invisible zero-width prepress glyphs) → replace "". Poppler emits the
  same FFFDs, so the gt mirror applies symmetrically.
- **Gate 20** polices the SHIPPED text (candidate-only — gate 2 normalizes
  both sides identically and cannot see corruption both witnesses share):
  U+FFFD + C0 controls unconditionally (C0 ⊇ the shift markers), plus
  per-book `qa.garble_chars` (I&B: every char the broken subset can emit;
  per-book because superscript-³ is legitimate elsewhere). Evidence: old
  shipped I&B fires 15 runs; rebuilt fires 0; other books 0/0.
- The garbled '%LEOLRJUDSK\' running heads pp.166/168 (word-shape-repaired
  to 'Bibliography' and shipped as duplicate h3s) are furniture: dropped by
  override, single Bibliography heading ships.
- **Shifted-CMap FOLIOS leaked past the furniture strip** (found 2026-07-09
  chasing an unmapped `TimesNewRomanPSMT@10` that blocked the build): the
  furniture/folio shape test runs BEFORE the flow's per-run repair, so a
  shifted folio arrives as control bytes ('129' -> '\x14\x15\x1c'), never
  looks like digits, and ships as a stray body paragraph (pp.143/144/153/154:
  118/119/128/129). Fix: `textfix.probe_text` repairs a shifted run before the
  `is_folio_line` shape test, applied symmetrically at BOTH folio checks — the
  flow strip (`flowbuilder`) AND the poppler ground truth (`groundtruth`,
  whose own pre-repair folio check kept the same garble, so gate 2 matched and
  hid it). Gated on `shifted_cmap_repair` → a no-op for every other book.
  furniture-folio 155 -> 159; build epubcheck-clean and qa Overall PASS from
  the committed book.yaml (previously unbuildable).

## Gates 21 (figure integrity) + 22 (warnings adjudicated) — 2026-07-09

- **Gate 21** promotes figure_phashes (dHash vs a re-render of each
  Figure's source region, hamming ≤16) from --visual-only to always-on: a
  blank/corrupt shipped figure is content loss no text gate can see.
  Promotion evidence: clean on all five artifacts (incl. HU's 68
  CJK page-figures — the false-positive surface); a scratch BoK EPUB with
  region-0026-0.png blanked white FAILS with a review pair written to
  build/qa_figures/. Cover images (no pdf_page) are skipped.
- **Gate 22** ends `Overall: PASS` coexisting with open content-risk
  warnings. `warnqueue.py` is the single derivation used by BOTH
  build/_write_warnings and QA (zero divergence): stable codes with a
  severity table (content-risk vs advisory), page lists derived from
  doc/flow/cfg FIELDS (display strings truncate at 15), auto-resolve for
  warnings a config judgment demonstrably covers (image-only ∈
  cover/exclude/figure_pages; agreement-low ∈ those ∪ columns ∪
  printed-TOC; embedded-image ∈ exclude ∪ figure_regions; top-band with an
  exact-line override), and a book.yaml `adjudications:` section
  ({warning, pages?, note REQUIRED}) for the rest. Stale entries are build
  errors (flow.overrides doctrine) and gate-22 failures. warnings.md is
  per-config (`warnings.<stem>.md` for variants — ends the BoK
  last-run-wins collision) and renders grouped by code with
  OPEN/auto-resolved/adjudicated status + paste-ready snippets.
- The first enforcement pass caught real losses the old queue had let
  coast: MR p.437 (a content PHOTOGRAPH — Yakutiye Medrese portal — whose
  caption shipped while the image didn't; now a figure page), HU p.8 (the
  Yin-Yang diagram facsimile plate, same class; figure page keep_text),
  and MR's three "unrecognized top-band" lines which were NOT content but
  shipped running-head leaks (a 9pt-italic 'William C. Chittick' + two
  smallcaps chapter heads) — gate 8 was blind to them because its
  templates come from the flow's own strip set. Dropped by override.
- HU's "2 RTL chars" were U+FEFF (BOM/ZWNBSP prepress artifacts on the
  title pages), not RTL text: the census range wrongly included U+FEFF
  (Arabic Presentation Forms-B ends at FEFC — _RTL_RE fixed). BoK-arabic's
  genuine RTL warning is now a config adjudication, not NOTES prose.

## Exact inline page anchors — 2026-07-09

A print page beginning mid-paragraph now gets an InlinePageBreak at the
exact run seam (`<span epub:type="pagebreak" role="doc-pagebreak">` inside
the paragraph) instead of a block anchor deferred to the next new block.
Far bigger than the `approximate` flag suggested: BoK 179 / BoK-arabic 179 /
HU 31 / I&B 98 / MR 181 pages get exact anchors (the flag only marked pages
with NO new block at all; pages whose anchor landed at their first new
paragraph — lines into the page — were silently imprecise).

- The seam is ALWAYS a run boundary: the insertion index is captured BEFORE
  _append_line (join separator/dehyphenation land on the previous TextRun
  first — inserting before the join would fabricate the exact fused seams
  gate 11 polices) and the anchor inserted after; pending blank-page
  anchors flush at the same seam, keeping the page-list monotone.
  Dehyphenated page turns put the anchor mid-word (empty span; sep "");
  accepted.
- ZERO slicing changes: qa_pageslice and proofread.walk_doc both use
  pre-order body.iter() with tag-agnostic epub:type matching, so an inline
  span attributes the straddling paragraph to the page it STARTS on and
  advances the cursor after it — byte-identical partition to the old
  deferred div (pinned by test_slicer_inline_equals_block_partition).
  Gates 13-17 verdicts unchanged on all five artifacts.
- What DID need changes: qa/visual.py's anchor collector (flow.blocks scan
  missed inline anchors → count_ok false → every EPUB slice silently
  skipped) and its two 'div.pagebreak' JS selectors; emit-side rescue for
  role=drop/absorbed paragraphs (an anchor inside a skipped paragraph
  re-emits as a block div — nothing may swallow an anchor); model
  round-trip via the "ordinal" key sniff.
- `approximate` now means exactly "page contributed no flowable text":
  remaining block anchors with the flag are genuinely blank pages (BoK 2,
  HU 9, I&B 4, MR 6 — verified 0-char pages), where a block-boundary anchor
  IS positionally exact. Proofread packets moved only blank-page {p.N}
  markers to the correct side of section boundaries (the old deferral
  pushed them past the break into the next file).

## Footnotes, soft hyphens, recto/verso shift — 2026-07-09 (Sufism)

First non-validation book, and the one that proved the deterministic gates +
sampled visual QA can BOTH pass a build that reads as damaged. The deterministic gates and
gate-18 contact sheets were green while ~412 body/footnote paragraphs (a third of
the book) were wrongly split. Only the blind-reader proofread caught it. Lesson:
**never present a build as done on gates alone — the mandatory proofread is the
only reviewer that sees paragraph integrity and reader-level fusion/splitting.**

- **Footnote markers can be a SIZE DOWN, not superscript-flagged.** WorldWisdom sets
  the digit marker at 7pt over 9pt note text with a single space ("8 Let us…"), so the
  `_NOTE_START_DIGIT` text pattern (`digit + [.)]/tab/2-space`) never fired → `0 notes`.
  A note whose footnotes never extract does NOT fail a gate: the note text flows as
  small-font body paragraphs, shatters per line, and breaks the body paragraphs it sits
  between. `_note_start`/`_note_marker` now also accept a superscript OR smaller-font
  leading digit/asterisk. **Watch the build's `N notes` line — `0 notes` on a book with
  a visible footnote apparatus is a red flag the gates won't raise.**
  - The note-continuation merge (cross-page wrap) and the marker capture were on the
    same old regex — they must track `_note_start`, or every page's first note merges
    into the previous (1+2+3 → one note) and noterefs fall back to '*' and never attach.
- **U+00AD soft hyphens: `normalize` strips them, the FLOW does not.** So gate 2/9/11
  are blind to 1000+ shipped soft hyphens; a few land at a line join as a visible
  "eso­ terism" space. Strip embedded/seam soft hyphens in `_apply_textfix`; close a
  trailing one in `dehyphenate_join`.
- **Recto/verso binding margins shift the whole text block ~18pt.** Two independent
  detectors keyed off the GLOBAL modal geometry broke on shifted pages: (1)
  `_break_before`'s short-line test flagged full lines (right ~360) as paragraph ends
  vs the modal right edge (381) → scale by the block's own left inset; (2) column-gutter
  detection smeared because verso/recto index gutters differ (x≈227 vs 209) → two specs,
  and skip furniture from the gutter census (running heads span both columns + the
  gutter). Centering detection had the SAME blind spot (user-reported: the `* / * *`
  section breaks centered on recto pages but flush-left on verso). Fixed the same way —
  `ColumnGeometry` carries a per-page shift and `line_pstyle` + gate 14's centering
  witness offset their center/edges by it. The shift is computed ONLY from left-aligned
  prose (>=3 long lines sharing an edge), so a FULLY-CENTERED page (title page, the
  "Books by Frithjof Schuon" list) has no anchor and gets no shift — its centered lines
  still miss `/center`. That residual (the book list) is the one documented FLAG; the
  section breaks, body pages, and the copyright page are fixed.
- **QA `"notes" in href` heuristic is too broad.** Back-matter *sections* titled
  "Editor's Notes"/"Biographical Notes" were classed as the generated endnotes file and
  dropped from the coverage + typography scope. Key on the `epub:type="endnotes"`
  marker (`EpubDoc.is_endnotes()`), not the filename.
- **Coverage after footnote extraction:** the candidate must include the notes file, and
  note excision must run PER SOURCE PAGE (a footnote wrapping p.N→p.N+1 leaves half its
  text on each — the whole-note string matches neither) with a hyphen/space squeeze
  match (flow dehyphenates; poppler keeps 'mer- cantile').
- **Line-end dashes are continuations.** A soft/em/en-dash at a line end signals a
  hyphenation/clause continuation, not a ragged short line (`_CONT_DASHES`); a closed
  em/en-dash across a break joins WITHOUT a space (this book's dash style is closed).

## Semantic block grammar: verse (2026-07-10)

The block ontology gained its first class end-to-end: `blocks.verse` specs
(pages + base/turn pt offsets from the SHIFT-CORRECTED column left, tol,
stanza_gap, note REQUIRED) drive a pre-join classifier in flowbuilder;
classified lines BYPASS `_break_before` entirely (the flow.columns
entry_break precedent) — a stanza is ONE Paragraph, lines joined with
U+2028, no dehyphenation. Emission: consecutive stanzas coalesce into
`<blockquote class="verse" epub:type="z3998:verse">` with `<p class="vs">`
per stanza and `<span class="vl">`/`"vl vt"` per line joined by `<br/>`
(SE poetry pattern; `epub:prefix` for z3998 is REQUIRED in the shell or
epubcheck errors). Gate 23 counts flow verse lines against shipped span.vl
— the ONLY structure-loss witness (a flattened poem loses no chars). The
UNCALIBRATED verse-suspect witness runs on every build (how future books
discover verse); blockshapes.py is the single detector derivation shared
with analyze.

- **Verse has NO font/size signal on this corpus** — Bembo@11 == body.
  Geometry only: base/turn alternation, ragged right edges (justified
  right-edge clusters VETO — `_assign_block_right`), all-short.
- **Two print conventions**: two-level base/turn alternation (M&R body
  9-11/36-38, notes 37.5/50+73.5) and SINGLE-LEVEL ragged inset (I&B's
  Buddhist-scripture quotes at inset 18, `turns: []`). BoK quotes poets at
  single-level 18 too. The suspect witness found REAL uncovered verse in
  I&B (10) and BoK (3) on first corpus contact — the corpus survey's "no
  verse outside M&R" was wrong.
- **Look-alikes that are NOT verse** (render-verified): dialogue set one
  speech per line at the paragraph indent (M&R pp.68/87/126/206/283 —
  single-level runs at base≈para-indent; hence turns required in body
  specs, and the suspect witness demands base inset >= 6pt); centered
  title lists; hanging-indent apparatus.
- **Boundary rules from print evidence**: strict base/turn ALTERNATION
  (consecutive same-level splits the run — sheds note first-lines that
  share the verse base offset, p.370); the short test applies only to
  BOUNDARY base lines (interior/turn lines legitimately run to full
  measure — p.370 turn ends 4.4pt short of col_right; a full-measure base
  line at a boundary is prose — p.165); cross-page stitching BOTH ways
  (accepted verse relaxes next page's base-start; a pending page-bottom
  tail is stamped only when the next page's top run accepts the union).
  Correction verbs `class:verse`/`class:prose`; a spec classifying zero
  groups is stale (SystemExit).
- **Verse-dense pages break the recto/verso shift detector**: on M&R
  p.165 (near-full-page ghazal) the verse BASE INDENT outvotes the prose
  margin for the page-modal left and a long verse line passes the
  width-only full-measure confirm → bogus shift −10 → spec offsets miss.
  Fix: the shift is vetoed when >=3 wide lines SPAN THE GLOBAL COLUMN
  (x0≈col_left AND x1≈col_right — presence of true full-measure prose).
  Corpus diff: M&R loses all 49 (all bogus), BoK/HU/sufism unchanged, I&B
  loses 7 with byte-identical output. Width alone is NOT full measure.

## Phase F corpus re-ship (2026-07-10) — the readers audit the pipeline

Re-judging the four stale books through blind-reader rounds surfaced
pipeline defects no gate had seen; each became a shared-code fix:

- **Per-page body anchors, everywhere.** The verse pass still used the
  modal-column shift frame; on inset-dominated versos the shift detector
  keys off the verse itself (I&B p.86: modal left = the verse lines,
  shift -18, every offset wrong). Verse now anchors like quotes do.
- **Cluster witnesses need coverage AND locality.** justified_rights
  fired on ANY chance pair (a 13-line ragged poem vetoed by two edges
  0.9pt apart → margins need ceil(0.4n) coverage); body_anchors' right
  edge paired a couplet base with an intro's short end 1pt apart →
  witnessed only by lines STARTING at the left anchor; the verse veto
  counted couplets clustering on themselves (Jami pair 0.33pt apart,
  100pt short of the margin) → a justified cluster must sit within 45pt
  of the page right edge; single-level acceptance admits equal-length
  pairs ending >=40pt short (justified prose clusters AT its margin).
- **Everything that reads print text must probe through the CMap
  repair.** _note_start/_note_marker read raw shifted bytes: the I&B
  Yusuf essay's footnotes fused into one note per page and their body
  markers stayed bare digits ('surah2'). Notes went 199 -> 240+.
- **Mixed-encoding shifted runs**: real ASCII glyphs inside a
  detected-shifted run corrupt under the uniform shift — space -> '='
  (dozens of seams), line-end hyphen -> 'J' ('conJ stantly' x10); a
  trailing 0x2D is ALWAYS a real hyphen. Both repair deterministically;
  genuine shifted 'J' (al-Juzjani) is never followed by a space. The
  groundtruth's disputed-page detection keyed on the '=' garble the
  repair now heals — a page carrying ANY shifted-run line is disputed
  by construction (same 8 pages excluded either way).
- **A marked page-bottom region is a footnote at ANY length**: the
  20-char guard leaked '15. Ibid., p. 51.'-class notes into prose,
  twice splitting sentences around them.
- **Quote runs extend to shapes the cluster misses**: indented first
  lines of quote paragraphs (dialogue turns inside quotations) join via
  neighbor candidacy; page-top continuation tails qualify without a
  cluster when the previous page ended mid-quote.
- **Noterefs sit flush** after the preceding text (print convention;
  the ' [n]' gap was flagged by every blind reader in every book).
- **Chain-tail connectors** for dehyphenation gained the/in/of —
  interior hyphens required, so 'seeds-in-the-/flesh' keeps its hyphen
  while plain 'the-/ories', 'love-/liness', 'in-/terpretation' still
  join (corpus survey: every plain-prefix hit is a syllable break).
- **HU's fused-bookmark gate-6 lesson**: the byline pstyle mapped to h1,
  so the PDF's own fused outline title ('by Liu Zhi The Exposition…')
  matched the byline heading on the wrong page — a role:p override on
  the byline let the outline match the true title. The 28pt/18pt '·'
  lines are placeholder glyphs of the untranslated Chinese title (drop
  overrides); HU's book-wide soft-hyphen 'prin- ciple' seams healed
  uniformly (verified by packet diffs across all 60+ chapters).
- Handoffs that remain by design: I&B honorific-glyph drops leaving
  spaces before punctuation on the disputed pages (needs per-glyph
  render verification); 'love-/compassion' (geometrically
  indistinguishable from 'love-/liness'); the I&B pp.138-145
  Arabic-script garbles (engine-disputed, render-review queue).

### Round 3 (2026-07-10): 34 readers over the four re-judged books

Every accepted finding traced to a shared-code root; five more pipeline
fixes fell out:

- **Marker probing is per-RUN, like the repair itself.** _note_start's
  line-level probe garbled a CLEAN line whose only 'shifted' evidence
  was the lone \x0e honorific dingbat run (is_shifted_run fires on any
  marker char): '1.' became garbage, first_marked moved, and
  region[first_marked:] dumped the I&B essay's note 1 into the body as
  9pt paragraphs. The flow's own repair was always per-run — the probe
  now matches its granularity. Notes 224 -> 229, plus the '3.The
  Dhammapada' digit-abuts-capital marker shape (the LIST_MARKERS
  decimal lesson, mirrored).
- **class: overrides beat the geometric vetoes.** The justified
  right-edge veto silently unwound class:verse forces whose full-measure
  poem lines chanced into the body-right cluster (BoK p.220: four of six
  forces vanished, caught only because the round-2 reader re-read the
  packet). An explicit render-verified judgment now wins over blocked=.
  Corollary: verse-lines in the build log is the assertion to check
  after recording forces — 47 shipped where 51 were recorded.
- **blocks.lists marker: hang** — the marker-less hanging apparatus
  (I&B bibliography, entries at the column edge, turnovers +18):
  stops = x0 clusters left of min+hang, entry = any line at a stop.
  It dodges the garble problem entirely (no marker regex to fail on
  shifted bytes). M&R's 'Abbreviations and Works Cited' (pp.334-336a,
  same shape, ~250 entries) is now a one-spec follow-up — deliberately
  deferred: its packet loop is closed and reopening costs a reader round.
- **CJK seams join CLOSED** (textfix.dehyphenate_join): both-CJK and
  bracket-CJK line-wrap seams take no space ('天方至/圣实录'); Latin-CJK
  seams keep theirs. ~25 reader-flagged sites in HU's foreword, one rule.
  The CJK-only ArialUnicodeMS lines still pstyle-break their sentence —
  per-line joins ('一斋).', '十一年马福祥刻本).').
- **PUA glyph advances extract as literal spaces before punctuation**
  ('God\xa0<glyph> . But'): collapsed at the substitution site, including
  across run boundaries (the glyph usually IS its own run) — 13 seams in
  BoK; 'wrong-script lookalike' Ᾱ->Ā before Latin lowercase (the PDF's
  own ToUnicode, 8 sites); 'wa' joined the Arabic-article keep-set
  ('wa al-/nihal').
- **Census before mapping.** BoK's Minion@12 mapped role p since JP; the
  round-3 reader flagged ONE split subtitle, and the corpus census showed
  every Minion@12 line is a heading — wide two-line subtitles lose
  /center and shipped half-as-body on four chapters. One mapping line
  (h2) + four joins healed what per-page overrides would have chased.
- **The indent rule and prev_short only serve the BODY pstyle** — 9pt
  display lists (sufism's 'Books by' page) neither break nor join by
  those rules; the indent-join fused neighbours whose x0 steps sit under
  the threshold. Per-line breaks are the honest fix (37 overrides, each
  one title per print line).

## Semantic block grammar: quotes (2026-07-10, Phase B)

`blocks.quotes` classifies JUSTIFIED inset blocks — the right-edge cluster
that vetoes ragged verse IS the quote witness (one derivation:
blockshapes.justified_rights now backs both flowbuilder.block_right and the
quote detectors). Spec: `{pages, left_inset, right_inset (0 = body edge),
tol, note}`. Lessons that shaped it:

- **Insets anchor to the page's OWN body edges, never the modal column.**
  I&B's modal column [72,363] is a recto-left/verso-right CHIMERA (rectos
  set body at 63..362.8, versos 72..371.8), and on quote-heavy rectos the
  shift detector keys off the quote inset itself (22 quote lines at x0=81
  outvote 10 body lines: shift(51) = -9, exactly wrong).
  blockshapes.body_anchors: smallest shared x0 / largest shared x1 of
  body-size lines; right edge falls back to the widest line STARTING at the
  left anchor (quote-heavy pages often keep only one full body line).
- **Class entry/exit is a paragraph boundary; interior joins stay
  geometric.** The plan said "join decisions untouched", and the spec alone
  does hold that for interior lines — but the acceptance evidence showed 38
  I&B boundaries where the geometric joiner FUSED quote and prose: italic
  scripture quotes after an intro colon (the ps-twin rule eats the style
  change, the indent-break rule wants the ROMAN body ps, the gap sits under
  threshold). Those are real print-structure defects in the SHIPPED
  artifact; blind readers never flagged them because an inline italic quote
  after a colon reads linguistically fine. Boundary breaks healed all 38
  (+2 anchor shifts): I&B flow 881 -> 921 blocks, interior joins identical.
- **The body's first-line indent shares the quote's left offset** (I&B
  indents 18pt = the quote inset) — a lone indented line is a run of ONE
  and never earns block_right; that asymmetry is the whole discriminator.
  Corollary: a 2-line quote paragraph standing alone (one full + one short
  line) has NO cluster witness and is intrinsically confusable with a
  single-level verse couplet at the same inset. Precision wins: it stays
  prose; `class:quote` is the recorded-judgment path.
- **Drop-cap wrap lines are the left-only look-alike** (BoK: a wide 32pt
  'A'/'K'/'G' pushes 2-4 wrap lines to exactly the 36pt quote inset,
  justified to the body right — pp.9/50/163/294 all fired). Veto: a line
  whose vertical extent overlaps an oversized 1-2 letter line AND whose x0
  sits at that letter's right edge (±6pt). The x0 condition matters: BoK
  p.259's real quote OPENS under the initial's descender box 8.5pt right
  of the letter edge and must stay classifiable.
- **Full-quote pages have no anchors of their own** (BoK p.260: one body
  line among thirty quote lines — the apparent "body left" IS the quote
  target). The flow pass detects that shape (own left ≈ carried left +
  left_inset) and substitutes the previous spec page's carried anchors;
  the p259->261 hadith then ships as ONE blockquote per print paragraph
  with the page anchor inline inside p.bq.
- **Footnote turnovers poison the uncalibrated evidence** (BoK's 8.5pt
  notes fired 45 bogus 14/1pt "quote" runs): the suspects now require
  body_size-2 < size <= body_size+1. The flow never saw them (footnotes
  split first) — this was report-draft quality only.
- Mixed paragraphs (quote + prose lines) are now only reachable via an
  explicit `join` override or dropcap glue; they demote to prose silently
  (a recorded judgment needs no warning). The quote-seam warnqueue code
  from the first iteration was removed with the boundary-break design.
- Emission mirrors verse: consecutive quote paragraphs (+ interleaved page
  anchors) coalesce into `<blockquote class="quote">` with `<p class="bq">`
  per paragraph (gate 17's 1-to-1 held); proofread packets render them as
  `> ` paragraphs via the existing in-blockquote path; PROTOCOL teaches
  the do-not-flag rule.
- Phase F queue additions found during acceptance: I&B p151 bottom's
  footnote "30. Glasse, 302." LEAKS into the body flow as a 9pt paragraph
  (pre-existing in the shipped artifact — it splits the al-Jūzjānī quote's
  blockquote in half); I&B "Trustworthy =persons =have" interpunct garble
  on p151 (pre-existing shifted-CMap highmap residue).
- Judged specs: I&B `{pages: ["11-160"], left_inset: 18, right_inset: 18}`
  (86 detector runs / 61 pages; render-verified pp.51/151); BoK
  `{pages: [56, 193, 220, 227, "259-261"], left_inset: 36}` (render-verified
  pp.193/220/259-261). Artifacts NOT re-shipped here — both books carry
  open verse-suspects that gate 22 rightly blocks until the Phase F
  verse re-judge; the tracked EPUBs stay at their shipped state.

## Semantic block grammar: lists (2026-07-10, Phase L)

`blocks.lists` classifies marker lists — the one class where the SIGNAL is
textual (a marker regex) anchored by geometry (the entry stop). Spec:
`{pages, marker: decimal|bullet, hang, tol, note}`. Lessons:

- **Entry stops derive PER SPEC, not per page** (the flow.columns gutter
  precedent): cluster the marker lines' x0 across the spec's pages, keep
  clusters >= max(2, 25% of the top). Recto/verso binding shifts yield two
  stops (HU/I&B bullets at 81/90); a wrapped bibliography line opening
  with "1983." sits at the hang column in a sub-threshold cluster and
  never becomes an entry. Per-page anchors are hopeless here: on
  bullet-dominated pages the smallest shared x0 IS the bullet stop
  (HU p.16), and on hang-dominated pages it is the hang column
  (M&R long notes).
- **Entry lines always break; hang-column turnovers always join; sub-lemma
  paragraphs keep the geometric rules.** That triple heals BOTH shipped
  M&R apparatus damage classes at once (first-line splits: the turnover's
  indent-break fires because the entry sits at the column edge; fusions:
  a note ending on a FULL turnover gave the joiner nothing to break on)
  while keeping the within-item paragraph structure (sub-lemmas at +36
  with their own 9pt first-line indent, e.g. p.340's "Those people
  destroy the souls").
- **Marker regexes carry the corpus's three decimal habits**: "148. The"
  (space), "43.Necessary" (prepress lost the space), "1.·The" (BoK's
  interpunct); a trailing capital/open-quote lookahead keeps years-in-
  prose out. Kept IN the text on emission (never-rewrite; exact coverage)
  with list-style:none.
- **Emission**: consecutive list paragraphs -> real `<ol>/<ul
  class="plist">`; each entry paragraph opens `<li class="li1">` holding
  `<p class="lp">`, continuation paragraphs add `<p class="lp lpc">`
  (1 flow-Paragraph = 1 emitted <p>, gate 17 held). An ol may only
  contain li children: page anchors emit as pagebreak SPANS inside the
  nearest li. A ghazal quoted inside a note nests as its verse blockquote
  within the li (41 nested poems in M&R's notes file). The li is a
  CONTAINER everywhere downstream: proofread's walker, qa_pageslice, and
  runner._doc_text all skip an li with p children or the text doubles.
- **Precedence**: verse > lists > quotes. I&B's bulleted scripture sits at
  the same 18pt inset as its quotes spec — the marker is the stronger
  signal; and a bullet list of short ragged epithets (I&B pp.39/57) is
  verse-SHAPED, so the verse-suspect witness now skips any line covered
  by a recorded blocks: judgment.
- `list-marker-gap` (ADVISORY): decimal numbering must increase; a
  restart marks a chapter's notes section (M&R fires exactly 2, its two
  chapter boundaries) — a DECREASE mid-section would be a misread marker.
- **The blind re-read of the healed packets found the classifier's own
  blind spots** (round 2): the notes START mid-p.336 after the
  bibliography (printed 309 = physical 336 — the spec's first page was
  one short, leaving the old split damage on notes 4-17), the notes END
  on p.374, and grouped-passage entries use RANGE markers ("19-22. I
  have placed passages 19-22…", "102-103. Ibrahim Adham") the regex now
  accepts (\d{1,3}(-\d{1,3})?[.)]; four-digit years still can't match).
- **The apparatus has an INSET BLOCK level below the hang column** (M&R:
  entry 71/73, hang 98/100, inset 107/109, and inset paragraphs carry
  their OWN first-line indents at 125/127). Pure depth cannot decide
  breaks: stepping INTO the inset from the entry/hang level is a
  paragraph boundary (heals 20+ lemma glosses fused after full-width
  lines — geometry verified every reader claim at once: each lemma
  starts its own raw line at the inset), but WITHIN the inset the
  geometric rules hold — a per-line break shattered note 244's quoted
  anecdote into one paragraph per print line and stranded a kept
  'serv-'/'ice' hyphen across two blocks.
- **Hang-column lines join UNLESS the previous line visibly ended its
  paragraph** (_prev_short — the bare ragged-end signal without the
  indent rules): the round-1 split damage came from the indent-break
  rule, but 'Intellect is a veil.' opens a flush continuation paragraph
  at the hang column after a short entry line (p.341) and must break.
- **A page-top verse base line continuing the previous page's poem is
  exempt from the boundary-short trim**: M&R p.371's 'This thirst in our
  souls…' ends 7.3pt short of the column as the SECOND couplet of the
  poem the page turn interrupted — the trim shed it and the couplet
  shipped as two list paragraphs. The page anchor now sits inline at the
  exact verse line seam.
- Print-verified textfix classes closed in the same pass: marker
  abutting a single-capital word ('84.O you', '38.I\u2019ve' — 7 sites),
  semicolon+letter ('2218-51;Attar', 'manyness;it' — the lowercase-
  before guard of the round-1 pattern missed digit/bracket contexts; 54
  sites, renders pp.174/229), digit+comma+capital ('2.41,Shams'),
  closing-quote+period+capital. REFUTED by print: the passage-citation
  seam '\u201d(343)' is set TIGHT (p.35 render) — the pre-existing
  _SPACE_BEFORE_PAREN normalization stands, but no new quote-paren rule.
- **The Arabic article keeps its line-break hyphen when a capitalized or
  diacritical word precedes it** ('Q\u016bt al-/qul\u016bb' — 13 of 14 corpus
  sites; the SHIPPED BoK carried 'alqul\u016bb'-style damage at 12 of them),
  while English syllable breaks still dehyphenate ('teaching al-/lows',
  I&B p.157 — the one collision, discriminated by the plain-lowercase
  preceding word). 'as-/an-/ar-/ad-' must NEVER join a keep-hyphen set:
  the corpus survey showed they are overwhelmingly English syllable
  breaks. seven-/just- joined the closed compound set (M&R onesies).
- Judged specs: M&R `{pages: ["336-374"], marker: decimal, hang: 27}`
  (233 items, 375 list paragraphs; heals round-1 packets 037-040);
  BoK `{pages: ["41-42"], marker: decimal, hang: 22.5}` (the forty books,
  4 <ol>); HU `{pages: ["10-18"], marker: bullet, hang: 9}` (77 chapter
  digests); I&B `{pages: ["38-39", 57], marker: bullet, hang: 0}` (flat).
  M&R re-ships with this phase (qa Overall: PASS); BoK/HU/I&B artifacts
  stay at their shipped state for the Phase F re-judge.
- Handoff: the M&R bibliography ("Abbreviations and Works Cited",
  pp.334-336a) has NO decimal/bullet markers — author-name and sigla
  hanging indents are out of the marker detector's scope; its ~250
  wrong-splits/fusions (incl. 'SPL.W. C. Chittick') stay until a
  hang-only shape is designed (Phase F+). As-printed, verified against
  raw extraction and never repaired: '(M I 638-38)', 'a things',
  'word\u2019s of Iblis', 'His father\u2019 tradition', 'That this a
  commentary', 'is common theme', 'awliya\u2019Allah' (the U+2019+letter
  hamza/ayn class stays permanently unsafe), '(n\u00eest\u00ee )',
  '\u201cbooties\u201d[kafshak]' (tight quote-bracket = the citation
  convention), MSM vs MMS sigla (both exist in print).

## M&R proofread pass (2026-07-10) — prepress space classes closed

38 blind readers over 40 packets, ~700 findings → systematic classes, each
print-verified before repair (the class-level verification the 2026-07-09
deferral demanded):

- **comma+LOWERCASE (`sun,he`) is now repaired** along with five sibling
  prepress classes (punct+opening-quote, closing-”+letter, `[2:36].From`,
  `ease.(641)`, `others.*They`, `4.With`/`M.Thackston`). U+2019+lowercase
  stays UNREPAIRED forever: hamza/ayn transliteration (Sana'i, wa'llah,
  Ruba'iyyat) is indistinguishable from a quote seam.
- **The wrong-side-quote class (`way. ”Then`) was ~1/3 SELF-INFLICTED**:
  _SPACE_AFTER_PUNCT's optional-quote class contained the CLOSING ” and
  inserted the space between punct and quote. Openers only now; a swap
  pattern owns that seam. The rest of the class comes from print putting
  the closing quote at the NEXT line's start — the 'punct SPACE quote'
  shape only exists AFTER the line join inserts its separator, so the
  swap re-runs at close_para (per-line textfix is too early) and the
  seam walker handles both-sided-space variants (which the collapse pass
  would otherwise fuse back into the residual shape). Shipped residuals: 0.
- **Compound CHAINS keep their line-end hyphen**: fragment or continuation
  first-token carrying an interior hyphen ('so-/and-so', 'face-to-/face',
  'hundred-/thousand-year') is lexical, not a break.
- **Section title + passage number fused into one h3** (join_center_lines
  on adjacent centered smallcaps): 22 instances broken by override at the
  number line — found by scanning emitted h3 text for `title + N.` and
  mapping through para_lines provenance.
- **Proofread chunking past 16**: a 130-page chapter splits into 17
  chunks; the suffix alphabet was 15 letters (pre-existing crash).
- **HANDOFF → Phase L (lists)**: the notes apparatus (pp.337-373) and
  bibliography ship with systematic hanging-indent damage — nearly every
  note's FIRST line splits from its body (marker line at col-left is not
  'indented', so the turnover triggers the indent break), and short-ending
  notes FUSE into the next ('…MSM 114. 205. Despite…'). That is the
  blocks.lists shape (marker + hanging turnovers); fixing by override
  would take ~250 entries. Round-1/2 reader findings for packets 037-040
  are the Phase L acceptance evidence; notes packets excluded from round 2
  for this reason.

## Layout witness — optional ML third witness (2026-07-09)

`src/pdf2epub/layoutwitness.py` adds a vision layout model as a THIRD analyze-time
witness (marker/surya-inspired). It runs ONLY at `init` under `--layout`, writes advisory
evidence to `books/<slug>/analysis/layout/` (git-ignored, regenerable), and NEVER touches
`build` — the deterministic build still reads only book.yaml + the pinned PDF, so
byte-reproducibility and never-invent-words hold. It flags structure (figure/table region
rects, columns, footnotes, furniture, headings); the agent verifies each candidate against
the overlay render before pasting into book.yaml. Same "engines witness, never co-author"
boundary as poppler, one rung up (text→structure).

- **Backend is transformers, NOT surya/marker.** Both surya-ocr and marker-pdf pin
  `Pillow<11`; the repo runs Pillow 12 and Pillow 10 has no cp314 wheel (and this box has no
  compiler headers / no alt Python / no uv). So they cannot install here. We load a
  DocLayNet detector (`Aryn/deformable-detr-DocLayNet`, overridable via
  `PDF2EPUB_LAYOUT_MODEL`) in-process through `transformers` — SAME 11-class taxonomy surya
  emits (Table/Figure/Picture/Page-header/Page-footer/Footnote/Section-header/Caption/
  List-item/Text/Title). Install: `pip install torch --index-url .../whl/cpu` THEN
  `transformers`; also `torchvision` from the SAME cpu index (a PyPI torchvision mismatches
  torch → `operator torchvision::nms does not exist`). `timm` is pulled transitively.
- **Heavy imports are lazy** — importing the module costs nothing; torch/transformers load
  only inside `--layout`. `layout_available()` gates; absent backend prints an install hint
  and skips. Tests (`tests/test_layoutwitness.py`) are pure/faked and pass with the backend
  absent.
- **Coordinate map is a pure scale.** Full-page `get_pixmap(dpi=150)` shares the span-bbox
  top-origin CropBox space, so box px → extract-space pt is `px*72/dpi`, no matrix/offset.
  Validated: on BoK p.26 the witness Table `(71.1, 323.4, 361.6, 560.9)` ≈ the hand-authored
  `figure_regions` `[70,319,367,567]` — independent rediscovery.
- **Label bucketing gotcha:** DocLayNet has `Page-header` AND `Section-header`. Bucket
  furniture on `page-header`/`page-footer` ONLY — a bare `header`/`footer` keyword mis-files
  `Section-header` as furniture and drops the heading cross-check.
- **flagged_pages is a capped render queue** — it misses clean text tables (high engine
  agreement, no PUA). structure-suspect widens it (column-suspect, embedded-image,
  tabular-smell, and vector-ruled pages via `get_drawings()`); the report always states
  scanned-vs-not so a miss is never silent. The witness runs by DEFAULT (skill Step 1) with
  evidence-gated `auto` page selection: scan `all` when the book is ≤`AUTO_ALL_MAX_PAGES` (300),
  its TOC lists tables/figures (`toc_has_figure_list`), or it has vector-ruled pages; else the
  subset. `--layout-pages flagged|all|<spec>` overrides. Column detection is the weak signal
  (the model boxes a multi-col region partially); rely on `column_suspect_pages`, not the
  witness, for columns.
- **Benchmark baseline** (`scripts/bench_layout.py`, BoK, torch 2.13.0+cpu, transformers
  5.13, Python 3.14, CPU-only): median **2.12 s/page** (p95 2.43, render ~0.03 + predict
  ~2.08), model load ~1.4 s cached (~5 s first ever), peak RSS ~2.0 GB. Projections: 100p
  ~3.5 min, 300p ~10.6 min, 500p ~17.6 min. **Decision:** the witness runs once at init (not
  per build), so `all` is a bounded one-time cost — hence the evidence-gated `auto` default
  scans `all` for most books (≤300pp / TOC figure-list / vector-ruled) and the subset only for
  large books with no table/figure signal. Page-level parallelism does NOT help on CPU (a
  single page already saturates cores via torch intra-op threads; batching/more-workers give
  ≤1.15×) — the lever is fewer pages or a GPU. Re-run this bench after a torch/transformers
  upgrade.

## Code-review response — review #455 (2026-07-10)

A consolidated 17-job review of the Phase F commit surfaced 12 findings. Triaged against
the code AND the corpus; 8 applied, 4 refuted (the refutations matter as much as the
fixes — several proposed changes would have regressed test-pinned behavior or added
speculative repairs the project's no-lexicon doctrine forbids). All five main books stayed
byte-identical; every fix is test-pinned (`pytest -q` 264 green).

- **Carried-anchor / list-item resets** (flowbuilder verse/quote/list passes). `vcarried`,
  the quote `carried`, and `carried_open` survived non-spec pages, page-range GAPS, and
  spec-index changes — so a later sparse page could anchor to an unrelated earlier page's
  body edges. Now all three reset on leaving the spec, on a gap, and on a spec change.
  Byte-neutral on the corpus (BoK's non-contiguous quote pages [56,193,220,…] and I&B's
  gapped list spec [38-39],57 exercise the reset), but it closes a latent mis-anchor.
- **Forced `class:quote` on an anchorless page** was consumed then dropped (`anchors is
  None → continue`), and the now-empty spec tripped the stale-spec SystemExit. Mirrors the
  verse pass: fall back to the page's shift-corrected column edges when any line is forced.
  Test `test_forced_quote_ships_without_body_anchors` FAILS on HEAD with the SystemExit.
- **Wrong-script repair moved to shared `textfix.repair_wrong_script`** (Greek Ᾱ→Latin Ā).
  It lived only in the flow, so the QA ground truth carried the un-repaired Ᾱ and coverage
  compared repaired-candidate vs raw-witness. Now both sides call the one derivation
  (textfix docstring's own invariant). BoK flow output byte-identical; gt now symmetric.
- **Per-run fallback probe** (`_probe_run`) in the raised/size-down note-marker paths, for
  consistency with the primary per-run probe (no corpus case needs it — belt-and-suspenders
  where shifted bytes could reach the first run).
- **Analyzer per-line vertical filter**: a lone vertical line no longer voids a whole page
  of verse/quote/list evidence — the shape detectors already filter vertical per-line.
- **init `--layout-pages` validation**: a malformed spec (`abc`, `+sample:x`) was swallowed
  by the advisory backend catch as if the backend were missing. Page-spec resolution moved
  OUTSIDE the catch (user-input `ValueError` → `SystemExit`); the layout evidence dir is
  cleared before the run so a failure never leaves stale report.md reading as current.
- **Doc fix**: specs/qa-methodology.md integration point `groundtruth.py`→`qa/groundtruth.py`.

Refuted (verified, not applied):
- **Re-veto far-inset justified verse runs**: BoK & I&B ship single-level verse specs; the
  `x1 ≤ ref_right-40` acceptance exists precisely for the tested equal-length couplet
  (Jami, I&B p.100) which shares the exact signature of the feared false positive. Spec
  page + base level + `class:prose` override already gate it; re-vetoing breaks the pin.
- **Centered-line gap `max(gap_factor·med_lead, 1.35·sz)`**: the current
  `gap_factor·max(med_lead, 1.35·sz)` is test-pinned (copyright break @20.8, two-line 21pt
  title no-split margin 45.4pt). The proposal shrinks that split-defect margin (HU Chapter-55
  shape) to ~2pt for a ≤2pt gain on body-centered lines no corpus page needs.
- **Compound-chain whitelist for `hundred-/thousand-year`**: no corpus instance — the real
  multi-hyphen chains present ('spirit-of-the', 'seeds-in-the', 'View-of-Clinging') are
  connector-based and already preserved. A lexical whitelist is the speculative addition
  the dehyphenate comment explicitly refuses.
- **Narrowing list membership / keeping terminal verse inside a list**: by-design
  continuation capture and the deliberate "trailing verse belongs to what follows the list"
  roll-back; the three list books proofread clean and no corpus item ends in verse.

Bonus (found while verifying, not in the review): the **BoK Arabic variant** had frozen
before Phase F, so `book.arabic.yaml` carried NO `blocks:`, 4 of 41 flow.overrides, a stale
`Minion@12: p`, and no p.245 adjudication — its rebuild FAILED gate 22 (8 open verse-
suspects) and its committed artifact was stale. This is the D6 scenario the verse-suspect
witness is FOR: a re-judged book's structural judgments not mirrored to its variant. Synced
the (geometry-identical) render-verified judgments from `book.yaml`; the variant now builds
to 2799 blocks like the main, gate 22/23 PASS, Overall: PASS. Variant configs must track
the primary's structural judgments — and must be REBUILT for the witness to catch the drift.

## Imprint transforms + Editor's Notes relinking (2026-07-10, Sufism)

World Wisdom scholarly editions carry back-matter **Editor's Notes** keyed to the ORIGINAL
PRINT PAGE NUMBERS with NO marker in the running body text (rubric: "Numbers in bold indicate
pages in the text for which the following … are provided"). Reflow makes "page 4" meaningless,
so the whole apparatus goes dead. This is one publisher's convention, not a general PDF shape —
so it lives behind a gated **imprint** hook, not in the generic flow.

- **Extension point.** `book.yaml` gains a namespaced `imprint:` block; `pdf2epub.imprints`
  owns its sub-schema (`config.py` only routes it). The core calls `apply_imprint(res, cfg,
  doc, say)` ONCE — in `build.py` right after `stage_map` (NOT in `build_flow`: roles are
  applied in the map stage, so a flow-time hook sees `role is None` on every paragraph and can't
  find the h1/h3 headings it keys on). No-op unless `imprint:` is set → the other four books are
  untouched (all still build epubcheck-clean, QA PASS).
- **Links are markup, never words.** New `RunFormat.link` carries a SYMBOLIC target
  (`page:<label>` / `note:<note_id>`); the emitter wraps the run in `<a class="xref">` with a
  `{XREF|…}` placeholder href, and `resolve_crossref_links()` (a second pass modeled on
  `resolve_contents_links`) rewrites it to `<file>#<id>` once every file's `pagebreaks` and the
  global `_note_order` are known. Cross-file targets (`015` → `pg-4` in `007`) REQUIRE this
  second pass — a flow-time literal href can't know the split filename. Unresolvable → unwrap
  the `<a>`, keep the text, advisory-warn. Keeping links on `TextRun` (vs. a new inline type)
  means `Paragraph.text()`, the PUA scan, and every QA text gate see the linked text unchanged.
- **Chapter-aware `Note N` → footnote.** An editor entry `4: Note 2:` annotates the author's
  footnote 2 on print page 4, using the PRINT per-chapter numbering — but the EPUB renumbers
  footnotes GLOBALLY (`fn1..fn170`). So `Note N` resolves via `(norm(chapter), local_k) ->
  note_id`, built by walking the flow and resetting a per-chapter counter at each h1; chapter 2's
  "Note 1" is `fn20`, not `fn1`. The leading bold page number carries forward across an entry's
  continuation paragraphs (reset at each chapter subhead), exactly as it governs them in print.
- **Verification baseline (Sufism).** 99 page-ref links + 61 footnote-ref links, 0 unresolved
  placeholders, epubcheck clean, QA Overall PASS (page-list still 216, notes still 170).
  Cross-checked every note link against where its footnote is actually called: 56/61 exact,
  and all 5 residual are off by exactly ONE page — the footnote marker sits at a page seam
  (e.g. `fnref29` renders immediately before the `pg-24` span, ending page 23; the editor
  counts it as page 24). The LINK still points to the correct footnote in all 61 — the ±1 is a
  callout-page measurement artifact at boundaries, not a mapping error. Regression: me-and-rumi
  builds clean + QA PASS; the only shared-output change is one inert `a.xref` CSS rule.
- **Deferred:** `body_backlinks` (a body-side marker at the annotated passage) is parsed but
  rejected as unimplemented — v1 keys off print-page anchors only, no body mutation. Intra-notes
  cross-refs ("see editor's note for Preface, p. 4") ship as plain text.

## Proofread pass: back-matter page-top fusions + TOC part-dividers (2026-07-11, Sufism)

First full `/proofread-epub` pass on Sufism (29 blind readers / 31 packets, 15 clean; 24
findings, almost all pre-existing). Two fix classes worth generalizing:

- **Back-matter entries that begin at a page TOP fuse into the previous page's last entry.**
  Blank-line-separated entries (editor's notes, glossary, selections) give the join pass a gap
  signal mid-page, but across a page boundary there is none, so the first entry of a page
  continues the prior paragraph. Detect them ALL (not just what readers sample) with a
  pagebreak-anchor + entry-label scan of the shipped back matter — `<span pg-N …></span>` NOT at
  block start, immediately followed by a `Note N:` / `Selection N:` / `Headword (Lang):` label.
  On Sufism this found EXACTLY the 4 the readers flagged. Fix = `flow.overrides` `break` at each
  (page, line 1). Bonus: breaking a fused `Note N` entry also un-suppresses its World-Wisdom
  footnote link — the imprint linker only fires "Note N" detection at a paragraph START, so a
  mid-paragraph fused label was never linked (imprint count 61→62 after the fix).
- **A printed-TOC part-divider label carries no folio** ("Appendix" above "Selections from
  Letters… 133"). The rebuild treated it as a wrapped-title continuation and fused it onto the
  entry above. New `toc.standalone_lines` (render-verified per book) makes such a line its own
  entry. Gate 6 (reading order) then had nothing to page-verify it against, so it now SKIPS
  folio-less entries as info — correct scope, not a weakening (only the opt-in knob produces an
  empty label; every normal entry still carries its folio).

Everything else was routed to a documented handoff queue (CONVERSIONS.md 2026-07-11), the biggest
theme being `dehyphenate: lower-only` over-stripping real compound hyphens (`religion-quintessence`,
`karma-yoga`, `prayer-niche`…) — the keep-hyphen lexicon the project deliberately refuses — and
spurious in-line spaces after a hyphen/dash (`al- Bātin`) that are SOURCE-PDF extraction artifacts,
not join bugs (verified: they sit inside a single raw extracted line).

## Nav nesting by ancestor-count + per-book keep-hyphens (2026-07-11, Sufism)

- **`nav._nest` nests by strictly-shallower-ancestor COUNT, not raw level.** The old
  `min(level, stack[-1]+1)` clamp collapsed an `h1->h3` jump so the first h3 landed at depth 1
  and the NEXT h3 was allowed one deeper — nesting same-level siblings under the first (Sufism's
  Editor's Notes chapter subheads under `Preface`). The rewrite computes each heading's depth as
  `len(stack of strictly-shallower open levels)`, so headings sharing the same shallower ancestors
  are siblings regardless of the level gap. Two invariants keep the nav valid: depth rises by at
  most one per step, and every `<li>` gets at most one child `<ol>` (a second `<ol>` in one `<li>`
  — what a naive "reopen a child after popping" produces for `h1>h3…>h2` — fails epubcheck).
- **`flow.keep_hyphens`** — a per-book, render-verified list of compounds whose hyphen must
  survive a line-break split, threaded into `dehyphenate_join(prev, nxt, mode, keep)` and matched
  on the reconstructed `lastword-nextword` (case-insensitive). This is the sanctioned per-book
  escape hatch for `dehyphenate: lower-only` over-stripping (`religion-quintessence`), analogous
  to `qa_lost_space_allow` — an explicit agent judgment, NOT the automatic global lexicon the
  dehyphenate doctrine refuses. Unused entries are inert (no stale-fail), so it's safe to list
  a compound that only sometimes breaks at its hyphen.

## Linked index locators + Kindle output (2026-07-11)

Two `specs/commercial-parity.md` roadmap items, both pure reuse of existing machinery.

- **Linked index locators** (`src/pdf2epub/index_locators.py`, a generic map-stage transform
  hooked in `build.py` right after the imprint hook). Back-of-book index page numbers were dead
  text; DAISY wants each locator hyperlinked. The transform reuses the imprint's `RunFormat.link
  -> {XREF|page:<label>} -> resolve_crossref_links` chain wholesale: it stamps
  `fmt.link="page:<label>"` on each locator's char range via the now-shared `core/runlinks.py`
  `apply_link` (factored out of `world_wisdom._apply_link` — the imprint imports it back, so the
  Sufism EPUB is byte-identical). **Opt-in, never guesses:** fires only on a `flow.columns[].index:
  true` block or the new `index` role, so every other book is byte-identical. A number links ONLY
  when its `pg-<label>` anchor exists (guarded against the label set), so a **broken index link is
  structurally impossible** — and gate 4 (navigation) already validates every href, so no new gate
  was needed. Unresolved numeric locators ship plain + an advisory `index-locator-unlinked` count.
- **Container.** Index paragraphs (except the section's own `h1` title) get `block_class="index"`,
  which the emitter gathers into ONE `<section epub:type="index" role="doc-index">` — the exact
  verse/quote/list gather-and-wrap pattern (letter-group heads are h2/h3, below `split.at_roles`,
  so the section never crosses a file split). `block_class` is set only when currently `None`, so
  a real verse/quote/list classification is never clobbered.
- **Tokenizer** `(?<![:\w.])(\d+)(?:[–—-]\d+)?(?![:\w])`: the `\w`/`:`  guards skip `S:V` Qurʾānic
  citations (`35:8`), `189n.4` note suffixes, and digits inside words (`20th`); a range links to
  its FIRST page. Gate 19 parses via `itertext()`, which walks INTO the `<a>`, so wrapping numbers
  is transparent to it (pinned by a `test_quran.py` regression). **BoK is the proof:** both index
  blocks flagged `index: true` -> 3770 locators linked in 873 entries, epubcheck clean, gate 4 +
  gate 19 + Overall PASS. aria-label on ranges + roman-numeral fm locators are deferred non-goals.
- **Kindle output** (`src/pdf2epub/kindle.py`, `pdf2epub kindle <epub> [--out]`). A thin
  post-process — no pipeline change; the EPUB is the source of truth. Shells to Calibre
  `ebook-convert` (found via `PDF2EPUB_EBOOK_CONVERT` or PATH; wrapped in `try/except OSError` so a
  bad override fails cleanly, not with a traceback), emits `<slug>.azw3` (KF8), reports size +
  converter warnings. Missing tool is a hard error (the artifact was explicitly requested), unlike
  the optional-tool skip. Documented warn-only in `bootstrap.sh` (chrome precedent). The `.azw3` is
  gitignored (only `.epub` is tracked). BoK -> a real "Mobipocket E-book … version 8" AZW3.

## Gate 24: per-page regression assertions (2026-07-11)

qa-methodology.md item 1, shipped. Every print-verified defect we fixed becomes a cell in a
per-book `books/<slug>/qa_assertions.yaml` so a future change that re-breaks it fails LOUDLY,
naming the spot — the gate-level FIRE matrices only prove a gate fires *somewhere*.
QA-only: no build-path change, so shipped `.epub` bytes are untouched (git shows no `.epub`
modified). Design lessons that the implementation forced:

- **The fixture is NOT book.yaml.** It is a tracked TEST artifact, located at
  `cfg.path.parent / qa_assertions.yaml` (variant configs: `qa_assertions.<stem>.yaml`, the
  `warnings.<stem>.md` rule), loaded by `qa/assertions.py` — never through `load_config`
  (`_check_keys` would reject it, and the build must stay a pure function of book.yaml). Keeps
  the build byte-reproducible and book.yaml a clean record of judgments while the test corpus
  grows every proofread.
- **Matching is on the shipped per-page slice, normalized through the SAME
  `core.textnorm.normalize` both QA sides use.** This decides expressibility: `normalize`
  folds curly/straight quotes, en/em-dash→hyphen, soft-hyphen/BOM (deleted), and collapses
  whitespace runs. So punctuation-SHAPE, EXTRA-space, and soft-hyphen fixes are
  NON-discriminable (a reverted fix normalizes identically) and are excluded from seeding —
  they belong to gates 9/10/11/20. A *missing* space IS expressible (`Now,however` survives
  normalize); an *extra* space is not. Structure loss (paragraph split/merge, blockquote
  flatten) is invisible to per-page concatenation and stays with gates 23/6; the `block_present`
  type covers the narrow "must stay one block" case (the al-Jūzjānī hadith, I&B p126).
- **Prefer `present`-of-correct-form over `absent`-of-broken.** Present also catches "glyph
  dropped entirely" (absent cannot) and reads as a positive guard. Operands are copied from the
  SHIPPED normalized text, not the poppler ground truth (GT strips PUA readings differently), and
  case is preserved (never lowercase).
- **Boundary matching** (`re.search(r"(?<!\w)…(?!\w)")`, default ON for `order`) keeps a
  citation token like `35:8` from matching inside `135:8`/`35:80` without a tokenizer.
- **Fail loudly, never silently pass.** Missing fixture → PASS; malformed fixture → FAIL (the
  worst QA failure mode is a bad fixture that silently drops every check); slicing failure
  (`SliceResult.ok == False`) → advisory-skip (the pagebreak gate owns that, don't double-fail);
  unresolvable/ambiguous label, non-contiguous range, or empty page slice → stale/FAIL (the
  lost_space / adjudication staleness doctrine).

### Verification baseline (revert acceptance test)
Seeded ~26 render-verified cells across the five books (MR 10, BoK 3, I&B 4, HU 3, Sufism 4 +
the two-book totals); every book ends `24 assertions: PASS`, `Overall: PASS`. The discrimination
proof: rebuild me-and-rumi with `flow.restore_spaces: false` (reintroduces the 3054 lost-space
fusions) to a scratch workspace carrying a copy of `qa_assertions.yaml`, then `qa` the regressed
EPUB → gate 24 flips to **FAIL, 10/10 lost-space cells naming their notes** (9 `absent` fusions
back, 1 `present` semicolon-fix gone), alongside gate 11 firing 2701 patterns. Two candidate MR
cells (`84.O you` p83, `M.Thackston` p308) did NOT flip — their period-space is in the source,
not a `restore_spaces` repair, so the `absent` form can't recur — and were DROPPED as
non-discriminating (the plan's rule: a cell that can't flip is inert). Runtime cost < 1s/book;
`slice_pages` is currently recomputed in the gate (typography already calls it — candidate hoist).

## External implementation review + roadmap re-rank (2026-07-12)

An outside reviewer read the code and ran focused experiments; all eight code findings were
independently re-verified here before acting (line cites in `specs/reliability-hardening.md`
and `specs/qa-methodology.md §3`). Confirmed: (1) gate-2 coverage is recall-only and passes
**reordered and duplicated** books at 100% — its comment delegates order to gate 6, but gate 6
checks only TOC/heading placement, not body order; (2) engine-disputed pages drop 66612 (I&B) /
27661 (BoK) / 13604 (Sufism) chars from the coverage denominator, defended by ~1 assertion cell
across 24 pages; (3) FILL-ME-IN unenforced (`initcmd.py:5` promises it fails the build; 3/5
`book.draft.yaml` load with `title: FILL-ME-IN`); (4) tests non-hermetic (`test_lang.py:35`
imports the sibling repo; `test_cdp.py` skips only on Chrome *absence*) + no CI/lockfile/linter;
(5) builds non-transactional (zip written straight to `{slug}.epub`; invalid EPUB left on
epubcheck fail; no provenance manifest — though the source-sha256 pin already exists); (6) seven
dead config fields (incl. `output.include_ncx`, ignored — packager hardwires the NCX); (7)
slug-only UUID fallback + `dcterms:modified` from the print year.

Two review claims were narrowed on verification: finding #8's Chrome/CDP path is **already**
bounded (DEVNULL output, per-op deadlines, 600×≤3000px clip) — only the three `subprocess.run`
sites (poppler/epubcheck/Calibre) are unbounded; and the review's "cheap pathology census" and
"verified-ocr mode" were **already** spec'd (`ocr-witness.md` step 1 and `source.text_layer`).

Roadmap outcome (single merged ranking in `specs/commercial-parity.md`): the reliability/QA
substrate is interleaved ahead of most features. Divergences from the reviewer's order, argued
in-spec: kept a11y high (external EAA forcing + ~80% done) rather than demoting it, but adopted
its correct refinement that `dcterms:conformsTo` needs a recorded *manual* certification, not a
green Ace run; ranked process limits low (threat-model-conditional; trusted-PDF workflow today);
promoted the FILL-ME-IN/dead-field fixes to Tier-0 cheap-correctness. New hand-off docs:
`specs/reliability-hardening.md`; `specs/qa-methodology.md §3` (page-aligned fidelity gate). No
code changed in this pass — spec/roadmap only.

## Reliability roadmap Tier 0 + Tier 1 SHIPPED (2026-07-12)

Implemented the above roadmap in seven phases (a second review of the plan caught real design
flaws — all incorporated; see the plan's "corrections incorporated" section).

- **Config integrity** (`config.py`): a shared `load_config(require_complete=)` validator now
  enforces FILL-ME-IN rejection (recursive over the raw dict), required metadata (presence
  checked on the raw dict — `language` defaults to `en`), and a strict-int `schema_version`
  (rejects YAML `true`); `build` and the new `pdf2epub validate` both call it. Dead fields
  removed (`furniture.bottom_band`, `images.alt`, `images.decorative`); `output.include_ncx`
  implemented (respects the flag + unlinks a stale `toc.ncx`, since the packager zips all of
  oebps); `pages.front/body/back` given structural validation (the folio cross-check is noisy —
  I&B declares body.first 25 but folio "1" lands on p.26 — so shipped OFF).
- **Transactional builds** (`build.py`, `packager.py`, `provenance.py`): package to a unique
  `tempfile.mkstemp` temp; ALL fallible work (epubcheck, input recheck, manifest generation +
  temp write) happens BEFORE promotion; the EPUB is then committed by a SINGLE atomic
  `os.replace` and the manifest is an atomically-written sidecar — a failed build leaves the
  prior `.epub` untouched (verified). Input hashes are snapshotted before processing (book.yaml's
  hash is of the EXACT bytes `load_config` parsed — `cfg.config_sha256`, not a re-read) and
  rechecked before promotion, so a mid-build change to book.yaml or the PDF aborts rather than
  shipping an EPUB mislabelled with the changed input's hash. Immutable
  `build/<slug>.manifest.json` (gitignored): book.yaml + source-PDF paths and sha256, epub
  sha256, **tri-state** epubcheck (`ok`/`skipped`, never conflated), tool+dep versions, git rev +
  **dirty flag**, release epoch — no wall-clock, byte-stable across rebuilds. `pdf2epub verify`
  checks the EPUB↔manifest hash AND book.yaml/source-PDF drift-or-absence (a recorded input now
  missing or changed is a failure, not a silent skip). **Reviews #1–#5 refined this**: an initial
  two-rename-with-rollback design was replaced by the single-commit + sidecar model after the
  rollback logic proved to have more failure modes than it closed; the sole residual is a
  process-kill BETWEEN the two same-dir renames (EPUB then manifest), which `verify` detects —
  true joint atomicity would need directory indirection, which conflicts with the git-tracked
  fixed EPUB path.
- **Gate 25 page fidelity** (`qa/fidelity.py`): see qa-methodology.md §3 for the shipped design
  (char-level anchor slicer, ±1-page window, rapidfuzz LCS, Rabin-Karp duplication). Thresholds
  from mutation-vs-corpus margin. **The first draft's alignment math was unsound** (window_start
  is a search-window start; `matched` sums non-contiguous blocks) — the corrected version
  compares page-local and uses real coordinates only for order. All six books PASS with margin;
  a real injected dup and a real anchor corruption FAIL end-to-end.
- **Gate 26 a11y readiness** (`qa/a11y.py`, `qa/ace.py`): alt + metadata + Ace (pinned in
  `tools/ace/`, absence-skips-but-crash-FAILS). The Ace baseline caught a real **serious**
  `epub-pagesource` on every page-numbered book → fixed with `<meta property="pageBreakSource">`
  + `printPageNumbers`. 3 moderate `heading-order` findings remain (non-gating). No `conformsTo`
  (manual cert deferred).
- **CI/tooling**: pytest markers (only `test_cdp` is non-hermetic — everything else mocks/
  synthesizes); removed the sibling-repo `class_hint` test; Chrome skip env-gated so the browser
  CI tier still catches launch/protocol regressions; `websocket-client` promoted to a real dep;
  hashed `requirements.lock` (pip-compile, Python 3.14); ruff E4/E7/E9/F/I clean (E741/E731
  ignored as established style); mypy advisory; portable GitHub Actions (unit/locked-install/
  browser/corpus, epubcheck downloaded+sha256-verified).
- **Identity + corpus reship**: `metadata.identifier` (validated UUID/urn) + `metadata.released`
  (validated YYYY-MM-DD → `dcterms:modified`). The 4 UUID-flagged books + a **distinct** UUID for
  the BoK arabic variant (the two BoK EPUBs no longer share `urn:isbn:9781941610213`). All six
  rebuilt; every one epubcheck-clean, gates 25/26 PASS, `Overall: PASS`.

Verification baseline: `pytest -q` 361 passed; `ruff check` clean; six-book corpus all
`Overall: PASS`; two clean builds byte-identical (epub + manifest). Deferred (documented):
reliability-hardening §5 (process limits) + §6 (maintainability); a11y manual certification.

## Form & Substance conversion — 6 corpus-general fixes (2026-07-13)

New Schuon/World Wisdom book (`form-and-substance-in-the-religions`); see
CONVERSIONS.md for the full log. Six pipeline fixes it surfaced, all with unit
tests and all 5 reference books re-QA `Overall: PASS`:

- **Note-region scan must stop at a large vertical gap.** A copyright page set
  wholly sub-body-size let the bottom-region walk swallow the LCCN + colophon
  from its `1.`-marker line down, then DROP it (no in-body ref). `flowbuilder`
  note walk now breaks when `region[-1].y0 - L.y1 > 2.5*max_sz` — a real note
  block is contiguous. Content-loss class; the reason gate 2 exists.
- **`_ps_root` must fold `Roman` as well as `Italic`.** Fonts named
  `Family-Roman`/`Family-Italic` (not just an italic-suffix on a shared name)
  didn't share a root, so a full-line inline italic gloss split the paragraph
  (lowercase-initial blocks). One-line fix; watch for this whenever a book's
  body face carries an explicit `-Roman` style token.
- **Closed em-dash at a line seam often arrives as its OWN run** (an italic word
  then a roman `—`), so `dehyphenate_join` sees a bare `"—"`. Guard is now
  `(?<!\s)[—–]$` (covers bare-dash and quote-before-dash), not `[letter][—]$`.
- **Indent detection must shift-correct `col_left`.** `_break_before`'s absolute
  first-line-indent test used the global `col_left`; a verso binding shift slid
  the block left so a real ~16pt indent read ~5pt and short citation paragraphs
  fused. `eff_left = col_left - geo.shift(pno)` — the same page shift the
  verse/quote passes already apply. LATENT corpus-wide (also un-fused ~105
  paragraphs in sufism). The one fix most worth remembering.
- **TOC rebuild** handles a numbered entry whose folio wrapped to the turnover
  line (marker line → pending entry; number-less folio line completes it).
- **`strip_stray_grave`** drops a lone ToUnicode `` ` `` not followed by a
  letter (shared flow/ground-truth); ʿayn graves (letter-following) survive.

Also: `flow.keep_hyphens` now the standard channel for dropped compounds AND
lowercase transliterated Arabic articles (`al-malakût` etc. — the arabic-article
keeper only protects Upper/non-ASCII forms). Centered book-list pages (varying
x0, role p) need explicit break(title)/join(turnover) overrides — the geometric
joiner cannot read a short centered turnover as a continuation.

Verification baseline: `pytest -q` **370 passed**; `ruff check` clean; six-book
corpus (+ F&S) all `Overall: PASS`.

## Keys to the Beyond — a calibre PDF whose own boxes and encoding lied (2026-07-14)

Six defects here were INVISIBLE to all 26 gates and surfaced only from a blind
reader or a render. Both witnesses read the same broken ToUnicode, so the
engine-disagreement score and gate 2 saw two agreeing witnesses; gate 2 is
recall-only, so leaked furniture and mis-scoped notes cost it nothing. **When a
book's own encoding is wrong, only the RENDER is ground truth.**

- **A CropBox outside the MediaBox slides the TrimBox off its own text.**
  MuPDF's `transformation_matrix` is MediaBox-referenced, but text coordinates
  live in `page.rect` = the CROPBOX normalized to origin 0. They agree only
  while CropBox == MediaBox. Calibre wrote CropBox y0=9 ABOVE MediaBox y0=24,
  so the stored trim sat 24pt below the text it bounds; every chapter-opening
  DROP FOLIO fell outside the 50pt bottom folio band, went unstripped, and —
  being 10pt, below the 9pt note region — broke the note-region walk on its
  FIRST line. All 12 chapter openings shipped their footnotes as body prose
  with a bare folio and an unlinked marker. `trim_in_text_space()` re-anchors
  on the CropBox; a no-op for a conventional PDF. **Highest-value fix here:
  check `p.trim` against `page.rect` on any new producer.**
- **Dot diacritics can be encoded as a bare period.** Keys draws Ṣ/ḥ/ṛ/ṅ as base
  glyph + a dot glyph whose ToUnicode says U+002E, so the text layer reads
  `S.ah.īh.` where print sets `Ṣaḥīḥ`. Neither engine can see it (both read the
  same map) and gate 20 sees no U+FFFD. Discriminator is geometric and exact:
  the dot is drawn OFF the baseline and INSIDE the base's advance; a real period
  sits ON the baseline after it. 28 hits in Keys, **0 across the other six books'
  ~450k spans**. Scan per LINE — a raised dot gets its own span. Which side the
  dot falls on is the PRINT's call (`Muṡṭafā` takes a dot-above where the
  standard sets it below): ship what is drawn.
- **NFC-normalize ONLY what you repaired.** A blanket `normalize("NFC")` on every
  span silently re-encoded BoK (which stores `ḥ` pre-decomposed as h+U+0323 and
  has always shipped it that way). Whether the corpus should ship NFC is a real
  question — but not a text repair's to decide.
- **A space the LAYOUT cancelled is not a printed space.** Keys stores
  `non- Buddhist` for a page that prints `non-Buddhist`: the next glyph is drawn
  at/before the space's own start, so the space took no room. sufism p.125 really
  does set `(al- Bātin)` — identical in TEXT, opposite in geometry (there the
  next glyph clears the space). Text alone cannot tell them apart, so the repair
  belongs in the extractor, scoped to the hyphen seam (a general phantom-space
  rule would also eat BoK's 1195 kerned post-period spaces).
- **`_ps_root` again: Adobe abbreviates the style token.** `-It` for italic and
  `-Regular` for upright means neither `Italic` nor `Roman` appears, so the twins
  never folded and every wrap line an italic term happened to dominate broke its
  paragraph and stranded a hyphen. Strip a SEPARATOR-anchored trailing style
  token too (`SemiboldIt` must not fold into the upright). This is the second
  time this helper has cost a corpus-wide defect — **check `_ps_root` against a
  new book's cluster list**.
- **The cross-run hyphen repair needs the line break's SPACE.** Runs that ABUT
  are a real compound whose hyphen merely coincides with a style change
  (`Krishna-` roman + `līlā` italic). Across the whole corpus the pattern occurs
  4 times and ALL 4 are compounds — the rule had never once done its intended
  job, and had shipped `nodharma` in I&B through that book's own proofread.
- **Note markers RUN ON.** A bare page-citation turnover (`130.` closing
  `…nn. 22,`) is marker-shaped, and the phantom note it forged BLOCKED the
  page-ordered ref queue for every real note behind it — 2 turnovers cost 11
  unmatched markers. Geometry cannot see this (a note's last line may legitimately
  fill the measure — p.22 note 21) and neither can the text pattern: only the
  sequence. Also: a CENTERED page-bottom line is never a note (the printer's key
  `10 9 8 7…` dragged the whole copyright page in).
- **`indent_threshold` must sit BETWEEN the book's indent scales, not on one.**
  The init proposal derives it from the BODY histogram alone; Keys' index
  turnover column sits at exactly 18pt, so the proposed 18.0 made
  `entry_break` (`x0 < col_left + threshold`) a knife-edge — turnovers measuring
  77.36 vs 77.38 fell on opposite sides and ~42 index entries lost their
  locators to a phantom break. Check the proposal against the INDEX/list stops.
- **Index sub-entry levels are a 9pt ladder and `flow.columns` flattens them**
  (KNOWN LIMITATION, same as sufism). Keys marks a sub-entry base with a leading
  WIDE SPACE (line x0 stays at the column left, first GLYPH is +9), so level 2
  breaks correctly — but level 3's base and level 2's turnover share x0 exactly,
  and no flat rule separates them. Text, order and locator links are all intact;
  only the sub-entry line structure inside a top-level entry runs on.
- **A scholarly book quotes itself.** Gate 25's duplicated-span witness assumes a
  >=400-char verbatim repeat is pipeline damage; Laude prints the same Schuon
  paragraph in two chapters' notes. New `qa.duplicate_allow` (snippet + note,
  stale entries FAIL) — the `qa.lost_space_allow` pattern.
- **The GT furniture strip must reassemble a head poppler SPLIT.** poppler emits
  a recto head as `Title` / `|` / `267` where MuPDF fuses it, so no single line
  matched the template and the head survived into the witness — where, being
  identical to the chapter TITLE, it anchored the page-probe on the chapter
  OPENING and forged a gate-25 reorder. Match the leading/trailing RUN; joining
  is what keeps a chapter-opening title (bare of folio and separator) safe.

Verification baseline: `pytest -q` **391 passed**; seven-book corpus all
`Overall: PASS`. Only I&B's EPUB changed (the `no-dharma` fix, print-verified).
