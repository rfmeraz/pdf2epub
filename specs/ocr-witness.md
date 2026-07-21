# OCR as a third text witness — legacy-PDF readiness

Status: spec'd, not implemented. Trigger: the first book whose PDF has no usable text
layer (scanned), or whose text layer lies badly enough that the two current engines
agree on wrong text (identically-broken ToUnicode). Do not build this speculatively —
the detection machinery below already tells us when the day arrives.

## Problem

The pipeline is wholly dependent on the PDF's embedded text layer. PyMuPDF extracts,
poppler cross-witnesses, and disagreement flags a page for render review — but there is
no recovery path when the layer is absent or corrupt beyond the hand-authored per-book
repairs (`shifted_cmap_repair`, `glyphs.fffd_repairs`). Current policy (NOTES.md "Open
items"): image-only pages ship as figure pages when the agent can verify content from
renders, else escalate. That policy caps out fast on a fully-scanned backlist title.

The corpus makes this a *when*, not an *if*: Fons Vitae and World Wisdom backlists span
decades of production. Modern InDesign exports carry ToUnicode CMaps; 1990s–2000s
books were typically printed to PostScript and run through Acrobat Distiller — a purely
visual path ("concerned ONLY with visible entities",
https://community.adobe.com/questions-18/missing-tounicode-after-distillation-594428).

## Legacy pathology catalog (what to expect, with sources)

- **Missing/wrong ToUnicode**: text renders correctly but extracts as garbage; a
  wrong-but-present map is undetectable by validators — OCR is the only verification
  (https://blog.pdf-tools.com/2014/01/why-is-extraction-of-text-from-pdf.html). We have
  already met the shifted-CMap variant (I&B, repaired deterministically; see NOTES.md
  2026-07-09 closure). The next book's map may be arbitrary, not shifted.
- **Type 3 / custom-encoded Type 1 subsets**: TeX-era Type 3 bitmap fonts have
  meaningless encoding vectors (https://texfaq.org/FAQ-cpy-srchpdf); the bigger
  small-press risk is Type 1 subsets with custom encodings extracting as
  *wrong-but-plausible* Latin that passes eyeball checks.
- **Diacritics**: pre-Unicode scholarly fonts put diacritic glyphs in arbitrary Latin
  slots (U Chicago MEDOC: https://mamluk.uchicago.edu/unicode.html); TeX `\accent`
  extracts as split base+accent pairs; expect wrong-char remaps (deterministic per-font
  table once diagnosed), split overstrikes (seam-aware normalization), and OCR that
  misreads under-dots/macrons (treat OCR as witness, never ground truth, on these).
- **Lost spaces**: justified Distiller-era text encodes inter-word space as TJ kerning
  offsets; extractors legitimately disagree on space placement (PDF Association:
  https://github.com/pdf-association/pdf-issues/issues/564). Root cause of the M&R
  lost-space class and of the mid-word-gap defects shipping in World Wisdom's existing
  Kindle books (Amazon reviews of *Art of Islam*).
- **Scan + OCR-underlay hybrids**: backlist reprints are often a scan with a vendor OCR
  text layer. Detect by GlyphLessFont / invisible render mode 3 / one-font-covers-all
  signatures (https://archive.org/developers/ocr.html); treat that text layer as
  OCR-grade, not author-grade.

## Design sketch

Doctrine unchanged: **engines witness, never co-author**. OCR becomes a third witness,
consulted only on pages the existing signals dispute — it votes to *flag*, and its text
is used for *verification and evidence*, never merged into the flow.

1. **Era/pathology census at extract time** (cheap, always-on): per-book evidence in
   `analysis/` — producer/creator strings, per-font type + ToUnicode presence +
   encoding class, GlyphLessFont/render-mode-3 signature, image-only page list. This
   is pure metadata reading (extract/mupdf.py already walks fonts and flags
   `image_only`); it turns "different times, by different processes" into a recorded
   fact the converting agent sees on page one of the structure report.
2. **OCR witness on disputed pages only** (new, gated by config `ocr.witness: true` +
   availability check, layoutwitness.py's lazy-import pattern): for pages with
   engine agreement < threshold, image-only pages, and OCR-underlay pages, render at
   300dpi and OCR. Backend order of preference: PyMuPDF's integrated Tesseract
   (`page.get_textpage_ocr`, already a dependency-adjacent path —
   https://pymupdf.readthedocs.io/en/latest/recipes-common-issues-and-their-solutions.html);
   olmOCR (Apache-2.0, anchored VLM, https://github.com/allenai/olmocr) as the
   heavyweight option if Tesseract's diacritic accuracy proves insufficient on this
   corpus. Output goes to `analysis/ocr/` as advisory evidence (git-ignored,
   regenerable) — the same contract as the layout witness.
3. **Three-way adjudication evidence**: the structure report gains a per-disputed-page
   three-column diff (MuPDF | poppler | OCR). The agent's existing judgment verbs
   already cover the outcomes: `shifted_cmap_repair`-style deterministic map (when the
   corruption is systematic), `figure_pages` (when the page should ship as image),
   exclusion, or escalation. A NEW judgment may be warranted for fully-scanned books:
   `source.text_layer: ocr` — declaring the embedded layer OCR-grade so coverage
   thresholds and gate-11 zero-tolerance are re-based accordingly (design decision for
   implementation time; do not silently relax gates).
4. **QA**: no gate consumes OCR text (non-deterministic across tesseract versions —
   would break byte-reproducibility of *verdicts*). Gate 2's ground truth stays
   poppler. OCR is analyze/adjudication-time only.

## Integration points

- `src/pdf2epub/extract/mupdf.py` (font census, render-mode/GlyphLess signature,
  image_only already at :227), `extract/__init__.py` (era census into evidence).
- `src/pdf2epub/analyze.py` + `report.py` (census section, three-way diff rendering).
- New `src/pdf2epub/ocrwitness.py` modeled on `layoutwitness.py` (lazy imports,
  `ocr_available()`, advisory output dir, never touches build).
- `config.py`: `ocr:` section (witness flag, dpi, backend), maybe
  `source.text_layer`.
- `warnqueue.py`: `ocr-witness-dispute` ADVISORY code (the existing
  `engine-agreement-low` CONTENT_RISK stays the gating signal).
- `.claude/skills/convert-pdf/SKILL.md`: hard-stop list amendment — "image-only pages
  whose content you cannot verify from renders" gains "…or from the OCR witness".

## Acceptance criteria

- On the tracked corpus (`pdf2epub corpus`): census runs, OCR witness never fires (no
  disputed pages beyond the already-adjudicated ones), builds byte-identical.
- On a deliberately-degraded fixture (strip ToUnicode from a test PDF with `pikepdf` or
  render pages to images): census names the pathology; witness produces per-page text;
  structure report shows the three-way diff; build without judgments fails loudly
  (existing image-only/agreement warnings), never silently.
- Tesseract absent → clean skip with install hint (layoutwitness precedent).

## Two related notes from the 2026-07-12 implementation review

**The era/pathology census (step 1) is the review's "cheap PDF-era/font/ToUnicode pathology
census" — already spec'd here.** It is pure metadata reading (producer strings, per-font
type + ToUnicode presence + encoding class, GlyphLess/render-mode-3 signature, image-only
list), always-on, and de-risks the whole legacy-backlist question for near-zero cost. It does
NOT require the OCR witness (steps 2-4) to ship — pull step 1 forward as an independent,
cheap win; it turns "different times, different processes" into a fact on page one of the
structure report.

**`source.text_layer: verified-ocr` — a controlled source mode, not just a witness.** The
review pushed back (fairly) on "OCR never enters the flow" as a permanent policy: for a
genuinely-scanned backlist title, witness-only is a hard product limitation. Step 3 above
already sketches `source.text_layer: ocr`; promote it to a *guarded* mode when a fully-scanned
title actually arrives, with these mandatory guardrails so it never becomes silent ML
authorship:
- **Version-locked** OCR engine + language data, recorded in book.yaml and the §2 build
  manifest ([reliability-hardening.md §2](reliability-hardening.md)) — otherwise verdicts stop
  being byte-reproducible.
- **Per-word/page provenance + confidence** retained as evidence; no silent mixing of OCR and
  embedded-PDF text on the same page (a page is one source or the other, declared).
- **Mandatory** gate-24 assertions + visual review on every OCR-sourced page (coverage
  thresholds and gate-11 zero-tolerance re-based, never silently relaxed).
- **Explicit disclosure** in metadata that OCR is the textual source (a `dc:source`/summary
  note), so downstream readers know the provenance.
This stays a documented non-goal until a scanned title demands it — but it is the *right*
escalation of the witness, not a replacement of the deterministic doctrine.

## Non-goals

- OCR text entering the flow SILENTLY, or as anything other than the explicitly-declared,
  guarded `verified-ocr` source mode above. The default flow's words come from the PDF text
  layer or from a human-verified deterministic repair — never an unlabelled OCR merge.
- Automatic ToUnicode repair inference (the I&B lesson: font-scoped repair was proved
  IMPOSSIBLE on identical font names; per-book render-verified maps only).
- RTL/Arabic OCR (compounds two unsolved problems; escalate those books).
