# Arabic-variant font upgrade

Status: spec'd, not implemented. Trigger: the first book needing a Unicode 14
honorific (U+FD40–4F), or opportunistically at the next arabic-variant build.

## Problem

`book.arabic.yaml` variants (BoK precedent, NOTES.md 2026-07-09) embed OFL **Amiri**
for Arabic runs. Verified against the installed binaries with fontTools (2026-07-09):
Amiri 1.003 covers U+FDFA/FDFB/FDFD but **lacks the Unicode 14 honorifics block
U+FD40–U+FD4F** (raḍiya Allāhu ʿanhu series, ʿalayhi al-salām series, quddisa sirruhū,
etc.) and **lacks combining U+0323** (dot below — IJMES transliteration must be
NFC-normalized before shaping with it). The corpus's PUA census routinely surfaces
exactly these honorifics (BoK's Honorifics font → U+F048 ﷺ); the moment a book needs
"raḍiya Allāhu ʿanhu" as a glyph, Amiri cannot ship it.

Unicode background: U+FD40–4F were added in Unicode 14 (2021) from proposal
L2/19-289R, which documents that publishers had been "using hacked fonts or images" —
i.e. PUA-encoded honorifics in print PDFs are expected, and mapping them to FD40–4F is
the durable substitution. SIL warns the new codepoints can mis-order in RTL context and
recommends U+200F RLM after the ligature (https://software.sil.org/scheherazade/honorifics/).

## Verified coverage matrix (fontTools cmap checks, 2026-07-09)

| Font | License | Arabic | FDFA/FDFB/FDFD | FD40–4F | IJMES Latin |
|---|---|---|---|---|---|
| Scheherazade New | OFL | full incl. Extended-B | yes | **yes** (v3.200+) | no (CP1252 only) |
| Amiri 1.003 | OFL | full core, no Ext-B | yes | **no** | precomposed + 02BE/02BF yes; combining 0323 **no** |
| Noto Naskh Arabic 2.020 | OFL | full incl. Ext-B | yes | **yes** | **zero Latin** |
| Gentium Plus / Charis (SIL) | OFL | none | — | — | **full** (Latin Ext. Additional, 02BE/02BF, combining 0300–033F) |
| Noto Serif | OFL | none | — | — | full incl. combining |
| Brill | proprietary | none | — | — | excellent, **unusable** |

**Brill is contractually unusable** (fetched https://brill.com/page/resources_fontseula):
non-commercial only, "Embedding the Font in HTML web pages is not allowed", no
modification (→ no subsetting), no redistribution. EPUB is HTML + @font-face. Do not
revisit.

**OFL embedding is explicitly compliant**: OFL FAQ Q1.12 permits document embedding of
full or subset fonts without Reserved-Font-Name renaming
(https://openfontlicense.org/ofl-faq/). Renaming subsets stays good hygiene (we already
subset via core/fonts.py with SOURCE_DATE_EPOCH pinned).

## Design

- **Arabic face**: switch arabic-variant embeds from Amiri to **Scheherazade New**
  (full honorifics + Ext-B). Alternative if its Naskh look is rejected against renders:
  Noto Naskh Arabic (same coverage). Record the choice per book in `fonts.embed` with a
  render-verified note, as today.
- **Latin diacritics**: no change needed while system fallbacks render IJMES Latin
  correctly in QA renders — but if a book's Latin face lacks Latin Extended Additional
  in readers (tofu risk: Kindle's fallback symbol font covers 351 chars), embed
  **Gentium Plus** or **Charis** for body Latin. Decide per book from gate-18 glyph
  pairs, not globally.
- **Substitution doctrine update**: when the PUA census maps an honorific that Unicode
  14 encodes, prefer the FD40–4F codepoint over a spelled-out phrase, append U+200F
  (RLM) after the ligature per SIL guidance, tag `lang: ar` as today. Requires the
  embedded face to cover FD40–4F — hence the font switch first.
- **NFC caveat** (why it matters even with full-coverage fonts): `normalize()` already
  NFC-normalizes QA text; the FLOW text must also be NFC where combining 0323 sequences
  appear, or run-level rendering may differ from QA's view. Add a targeted check if a
  book surfaces decomposed sequences (era census in specs/ocr-witness.md will say).

## Integration points

- `scripts/bootstrap.sh` (font fetch/verify list), `core/fonts.py` (family map +
  subset), per-book `book.arabic.yaml` `fonts.embed` + `glyphs.pua_map` entries,
  NOTES.md field-notes entry, gate 18 glyph-pair verification per switched book.

## Acceptance criteria

- Rebuilt BoK-arabic: every pua_map char renders in gate-18 glyph pairs with the new
  face (shaping-approximate caveat noted for multi-char ligatures — Pillow lacks
  libraqm; verify in Chrome contact sheets instead); subset size logged (Amiri subset
  was 48KB; Scheherazade subset should be same order); epubcheck clean; QA PASS.
- A synthetic fixture exercising U+FD40–4F + U+200F ships and renders (Chrome slice).

## Non-goals

- RTL paragraph flow (hard stop unchanged). Inline strong-RTL runs inside LTR
  paragraphs remain the supported shape.
- KFGQPC/Qurʾān-specialist faces (no-modification licenses → cannot subset).
- Changing the non-variant (Latin honorific-substitution) builds.
