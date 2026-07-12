---
name: proofread-epub
description: Adversarial reading QA for a built EPUB. Emit deterministic review packets from the shipped file (pdf2epub proofread), fan out one blind reader subagent per packet under the generated PROTOCOL.md, verify every finding against print renders, and fix accepted findings via book.yaml/flow.overrides/code — never by editing text. Use when asked to proofread an EPUB, review a conversion's reading quality, or as convert-pdf Step 4.5.
---

You are the review orchestrator. Subagents read; the PRINT decides; fixes go
through book.yaml or code with a unit test — the build stays a pure function
of (PDF, book.yaml). The gates prove the words arrived and still look right;
this flow proves the book READS right: fused/split paragraphs, seam spaces,
garble, fused headings — reader-level defects derived joins can't see.

## Step 1 — Build the desk

- `~/pyenv/bin/pdf2epub proofread books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml`
- Read `build/proofread/manifest.json`: packet list (ids, word counts, page
  ranges, per-packet sha256), the ordinal `anchors` list (label → physical
  page; labels COLLIDE across roman/arabic — always resolve within the
  packet's `anchor_k` range), and the whitelist facts.

## Step 2 — Fan out blind readers

- One subagent per packet (batch packets under ~500 words together). Prompt:
  "Read <abs path>/build/proofread/PROTOCOL.md fully, then read
  <abs packet path>. Apply the protocol exactly. Your ENTIRE final message
  must be the JSON object it specifies." Nothing else — readers are BLIND:
  no known defects, no other packets' findings, no book history.
- Parse each reply (tolerate a ```json fence). A reply that fails to parse:
  re-run that packet once, then record reader-error. Assign finding ids
  `NNN-01…`; write the aggregate to `build/proofread/findings.json` with
  `verdict/fix_layer/fix` set to null.

## Step 3 — Verify every finding against print

- Resolve the finding's `page` label to the physical page via
  manifest.anchors within the packet's anchor_k range; then
  `~/pyenv/bin/pdf2epub lines books/<slug>/book.yaml <phys> --render`
  (add <phys>+1 when the quote sits near a `{p.N}` boundary — markers are
  paragraph-granular).
- One VERIFIER subagent per finding (batch findings on the same page): give
  it the finding JSON, the `lines` dump, and the render path to Read.
  Instruction: "The print is ground truth. Refute anything the print itself
  shows (author's own dashes, printed hyphens, sic). If confirmed, name the
  fix layer and, for flow fixes, the exact RAW line index from the lines
  dump." Verdict JSON: `{"id", "verdict": "confirm|refute|unsure",
  "fix_layer", "fix": {page, line, action, note} | null, "reason"}`.
- Merge verdicts into findings.json. `unsure` → look at the render yourself;
  still unsure → escalate (hard stop). Recurring refutation patterns are
  PROTOCOL whitelist candidates — record them in NOTES.md.

## Step 4 — Fix, rebuild, re-review (≤3 rounds)

Fix layer by defect class:

| class | typical fix |
|---|---|
| fused-paragraphs | `flow.overrides` `break` at the RAW line starting the new paragraph |
| wrong-split | `flow.overrides` `join` at the line wrongly starting a paragraph |
| seam-space | code (join/emit seam) + unit test; never a text patch |
| bad-dehyphenation | `join` override / dehyphenate doctrine (code) |
| garble | glyphs.pua_map / shifted_cmap_highmap, verified on renders; unidentifiable = HARD STOP |
| fused-heading | `break` at the title's RAW line (+ `role:` overrides as needed) |
| quote-boundary | `break` (+ pstyle_map/role review for the quote cluster) |
| stray-furniture | `furniture.extra` or `drop` override |
| noteref-anomaly | code (_attach_noterefs) or `break`; re-check gate 3 |
| structure-loss | `role:` overrides / pstyle_map |
| duplicated-text / truncated-text | flow/emit bug hunt: code fix + unit test |

- NEVER edit emitted XHTML or the book's words; every fix is a book.yaml
  entry (stale-override hard-fail self-validates them) or code + unit test.
- After a fix confirms, land a **gate-24 assertion cell** in
  `books/<slug>/qa_assertions.yaml` (a tracked TEST fixture, NOT book.yaml)
  so the fixed site can never silently regress: `absent` the broken form or
  (preferred) `present` the correct one, on the finding's page label. This is
  the book-level analog of "misfire → code fix + unit test" for defects a unit
  test can't reach. Only seed classes that survive `normalize` (see
  qa/assertions.py: NOT quote/dash shape, extra-space, or soft-hyphen) and
  copy the operand from the SHIPPED text.
- Rebuild (`epubcheck: clean`), `qa` must end `Overall: PASS`, re-run
  `proofread`, re-read ONLY packets whose sha256 changed in the manifest.
  Stop at zero new confirmed findings or after 3 rounds — remaining
  confirmed-but-unfixed items go to the handoff report.

## Step 5 — Record

- Append to CONVERSIONS.md: date, rounds, findings by class with
  confirmed/refuted counts, fixes applied. Generic lessons → NOTES.md.

## Hard stops (never decide alone)

The convert-pdf list, plus: never "fix" a finding by rewriting text; a
confirmed garble with no deterministic repair; a confirmed truncation whose
missing text cannot be located in the flow.
