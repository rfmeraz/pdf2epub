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
sampled visual QA can BOTH pass a build that reads as damaged. The 23 gates and
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
