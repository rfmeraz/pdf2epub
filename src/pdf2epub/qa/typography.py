"""Typographic fidelity checks (gates 13-17).

The text gates prove the words arrived; these prove they still LOOK like the
book: cluster sizes survive into the shipped CSS (13), every centered claim
has centered source geometry (14), emphasis is conserved (15), headings are
typographically real (16), and each page's block-level signature matches (17).

EPUB side reads the SHIPPED artifact (styles.css + markup through
qa_cssresolve/qa_pageslice); PDF side reads raw extract-IR geometry through
the flow's line provenance (FlowResult.para_lines). The centering witness is
deliberately different in kind from analyze.line_pstyle (the historically
buggy rule): block-level, stop-veto, midpoint-agreement — and one-directional,
verifying claims only (gate 14), never asserting centering where none was
claimed.

All five land informational; names added to GATING gate for real after the
regression-corpus matrix (NOTES.md) is clean.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from rapidfuzz import fuzz

from ..analyze import ColumnGeometry, column_geometry, continues_justified_block
from ..core.emit_css import _css_class
from ..core.model import Paragraph
from ..core.qa_cssresolve import effective_font_size_em, parse_stylesheet, resolve_block
from ..core.qa_pageslice import slice_pages
from ..core.roles import StyleRule, apply_roles
from ..core.textnorm import is_folio_line, normalize
from .pdfchecks import _fold

_PUA_RE = re.compile("[\\ue000-\\uf8ff]")
_ITALIC_FAM = re.compile(r"italic|oblique", re.I)
_BOLD_FAM = re.compile(r"bold|heavy|black", re.I)

# one dial per check — tuned against the regression corpus (NOTES.md)
SIZE_TOL_EM = 0.06        # gate 13: |resolved em - expected em|
MID_TOL = 12.0            # pt: |line midpoint - column center|
DEEP_INSET_MIN = 18.0     # pt: single body-size line inset floor
DEEP_INSET_FRAC = 0.10    # of column width, ditto
STOP_TOL = 2.0            # pt: x0-at-a-known-left-stop veto
MID_AGREE = 2.0           # pt: multi-line midpoint agreement
WIDTH_SPREAD = 6.0        # pt: widths must differ for midpoint agreement to count
FULL_EDGE_TOL = 6.0       # pt: line flush at BOTH edges = center-indistinguishable
EMPH_FRAC_TOL = 0.15      # gate 15 page finding
EMPH_CHAR_TOL = 40
EMPH_BOOK_TOL = 0.03      # gate 15 book-level aggregate
BUCKET_DELTA = 1.5        # pt around body size: small | body | display
HEAD_SENT_LEN = 55        # gate 16 audit: sentence-like heading length
# gate 17 compares STRUCTURE (size bucket, centering) only — per-paragraph
# italic fractions are irreducibly noisy across the two witnesses (PUA
# readings without lang tags, seam chars) and any threshold knife-edges on
# mixed paragraphs (I&B bibliography ~50%, BoK Qurʾān quotes ~0.75); graded
# emphasis is gate 15's job, and test_styles_synth pins the class-italic rule

DESIGN_CENTER = {"caption", "titletext", "toc-entry", "contents-head"}
# roles whose EPUB rendering is identifiable (and skipped) by a design class;
# 'footnote' is NOT here — footnote-role paragraphs that stay in the body
# render as plain small p's, so both sides must compare them (small vs small)
SIG_SKIP_ROLES = {"caption", "half-title", "title-page", "toc-entry", "drop"}
_H_TAGS = {"h1", "h2", "h3"}
_SENT_END = ".!?;:,…"

# promotion switch: gate names listed here report their real verdict.
# Promoted 2026-07-08 after the regression matrix (NOTES.md): old pre-fix
# EPUBs fire 14/16/17 on all four books (15 on the three with italic
# clusters); current builds are silent on all five. Gate 15 stays
# informational by design (graded emphasis; page-level noise floor).
GATING: frozenset[str] = frozenset({
    "13 typo size fidelity", "14 typo centered witness",
    "16 typo heading census", "17 typo signature diff"})


@dataclass(slots=True)
class GateOut:
    name: str
    ok: bool
    lines: list[str]


@dataclass(slots=True)
class PdfParaGeo:
    """One flow paragraph with geometry recomputed from the extract IR."""
    start_page: int
    role: str
    style: str
    lines: list                      # PdfLine
    size_pt: float = 0.0             # chars-weighted dominant size
    letters: int = 0
    italic_letters: int = 0
    bold_letters: int = 0
    sc_letters: int = 0
    text: str = ""


def apply_qa_roles(flow, res, cfg) -> None:
    """Replicate mapping.stage_map's role assignment (QA never runs the map
    stage): pstyle_map + page/line role overrides + drop-cap class re-add.
    Language tagging / RTL census are emit concerns and stay out."""
    style_map = dict(cfg.pstyle_map)
    style_map.setdefault("__toc__", StyleRule(role="toc-entry"))
    style_map.setdefault("__note__", StyleRule(role="p"))
    apply_roles(flow.blocks, style_map, cfg.unmapped_role)
    for note in flow.notes.values():
        apply_roles(note.paragraphs, style_map, "p")
    for ro in cfg.role_overrides:
        sid = f"p{ro.page:04d}"
        for b in flow.blocks:
            if isinstance(b, Paragraph) and b.src.story_id == sid:
                b.role = ro.role
                if ro.class_ and ro.class_ not in b.classes:
                    b.classes.append(ro.class_)
    for (page, line), role in res.role_overrides_by_line.items():
        sid = f"p{page:04d}"
        for b in flow.blocks:
            if isinstance(b, Paragraph) and b.src.story_id == sid \
                    and b.src.psr_index == line:
                b.role = role
    for b in flow.blocks:
        if isinstance(b, Paragraph) and \
                (b.src.story_id, b.src.psr_index) in res.dropcap_srcs and \
                "first-dropcap" not in b.classes:
            b.classes.append("first-dropcap")


def _fam_root(family: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "",
                  family.replace("Italic", "").replace("Oblique", ""))


def build_para_geo(doc, res, flow, cfg) -> list[PdfParaGeo]:
    out: list[PdfParaGeo] = []
    smallcaps_fams = {f for f, fl in cfg.charstyles.items() if fl.smallcaps}
    for b in flow.blocks:
        if not isinstance(b, Paragraph):
            continue
        prov = res.para_lines.get((b.src.story_id, b.src.psr_index), [])
        lines = []
        for pg, idx in prov:
            pls = doc.page(pg).lines
            if 0 <= idx < len(pls):
                lines.append(pls[idx])
        g = PdfParaGeo(start_page=int(b.src.story_id[1:]), role=b.role or "p",
                       style=b.style, lines=lines, text=b.text())
        size_w: Counter[float] = Counter()
        for ln in lines:
            for r in ln.runs:
                if r.superscript:
                    continue
                f = doc.fonts.get(r.font_id)
                if f is None:
                    continue
                size_w[f.size] += len(r.text)
                # emphasis censuses count LATIN-side alpha only: the EPUB
                # wraps CJK/Arabic in lang spans it excludes, so Han here
                # would skew the fractions asymmetrically
                n = sum(1 for c in r.text if c.isalpha() and ord(c) < 0x2E80)
                if not n:
                    continue
                g.letters += n
                if r.italic or _ITALIC_FAM.search(f.family):
                    g.italic_letters += n
                if r.bold or _BOLD_FAM.search(f.family):
                    g.bold_letters += n
                if f.family in smallcaps_fams:
                    g.sc_letters += n
        if size_w:
            g.size_pt = sorted(size_w.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        out.append(g)
    return out


# ------------------------------------------------------ centering witness

def left_stops(doc, geo: ColumnGeometry, in_flow: list[int]) -> tuple[float, ...]:
    """Attested left edges of PARAGRAPH geometry: x0 values that full-right
    lines (x1 at the column's right edge — never centered shorts) use >= 3
    times. Capped below the deep-inset accept region so the veto can never
    bite geometry the inset floor accepts."""
    col_w = geo.col_right - geo.col_left
    cap = geo.col_left + max(DEEP_INSET_MIN, DEEP_INSET_FRAC * col_w) - STOP_TOL
    cnt: Counter[int] = Counter()
    for pno in in_flow:
        # normalize each recto/verso page into the modal frame (x0 + its shift)
        # so a verso margin and the recto margin count as the same stop, and
        # the full-right test uses the page's OWN (shifted) right edge
        s = geo.shift(pno)
        for ln in doc.page(pno).lines:
            if ln.x1 >= (geo.col_right - s) - 6.0 and (ln.x0 + s) < cap:
                cnt[round(ln.x0 + s)] += 1
    return tuple(sorted(float(x) for x, n in cnt.items() if n >= 3))


def genuinely_centered(pairs, doc, geo: ColumnGeometry, stops: tuple[float, ...],
                       body_famroot: str, page_shift: float = 0.0
                       ) -> tuple[bool, str]:
    """Verify a centering CLAIM against raw source geometry (gate 14 only —
    one-directional; column-filling lines are neutral, never positive
    evidence). ``pairs`` are (line, raw predecessor on its page). Neutral
    means flush at BOTH edges — a wide line that starts at the paragraph
    indent is exactly the BoK p.206 bug shape and must stay informative, so
    width alone never exonerates. A line CONTINUING a justified block (prev
    same x0, full-right — quote-indent/drop-cap-wrap last lines, BoK p.193 &
    p.185) is a paragraph line regardless of its midpoint. ``page_shift``
    slides the modal edges/center to a recto/verso-shifted page's own block."""
    col_w = geo.col_right - geo.col_left
    eff_left = geo.col_left - page_shift
    eff_right = geo.col_right - page_shift
    eff_center = geo.center - page_shift
    informative = [(ln, prev) for ln, prev in pairs
                   if ln.x0 - eff_left > FULL_EDGE_TOL
                   or eff_right - ln.x1 > FULL_EDGE_TOL]
    if not informative:
        return True, "all lines column-filling (center-indistinguishable)"
    body = geo.body_size
    strict = []
    for ln, prev in informative:
        f = doc.fonts.get(ln.dominant_font())
        size = f.size if f else 0.0
        fam = f.family if f else ""
        mid = (ln.x0 + ln.x1) / 2
        if size >= body + 1.0 or _fam_root(fam) != body_famroot:
            # display type: wide heads are real; midpoint alone decides
            if abs(mid - eff_center) > MID_TOL:
                return False, (f"display line mid offset "
                               f"{abs(mid - eff_center):.1f}pt > {MID_TOL:g}pt")
        else:
            if continues_justified_block(ln, prev, size, geo, page_shift):
                return False, ("continues a justified block (prev line same "
                               "x0, full-right) — a paragraph's last line")
            strict.append(ln)
    if len(strict) >= 2:
        mids = [(ln.x0 + ln.x1) / 2 for ln in strict]
        widths = [ln.x1 - ln.x0 for ln in strict]
        if max(widths) - min(widths) >= WIDTH_SPREAD and \
                max(mids) - min(mids) <= MID_AGREE and \
                abs(sum(mids) / len(mids) - eff_center) <= MID_TOL:
            return True, "midpoints of varying-width lines agree"
    inset = max(DEEP_INSET_MIN, DEEP_INSET_FRAC * col_w)
    for ln in strict:
        mid = (ln.x0 + ln.x1) / 2
        if abs(mid - eff_center) > MID_TOL:
            return False, f"body line mid offset {abs(mid - eff_center):.1f}pt"
        # stop veto first: "sits at the paragraph indent" is the diagnostic
        # reason (BoK p.206 shape); the inset floor makes it redundant at
        # current thresholds but keeps guarding if the floor is ever tuned down
        # stops live in the modal frame; normalize this line's x0 by the shift
        norm_x0 = ln.x0 + page_shift
        stop = next((s for s in stops if abs(norm_x0 - s) <= STOP_TOL), None)
        if stop is not None:
            return False, (f"x0 at attested left stop {stop:g} "
                           f"(+{stop - geo.col_left:.1f}pt), mid offset "
                           f"{abs(mid - eff_center):.1f}pt")
        if ln.x0 < eff_left + inset or ln.x1 > eff_right - inset:
            return False, (f"body line inset {ln.x0 - eff_left:.1f}/"
                           f"{eff_right - ln.x1:.1f}pt < {inset:.1f}pt floor")
    return True, "insets and midpoints check out"


# ------------------------------------------------------ shared line matcher

def _page_candidates(doc, cache: dict, pno: int,
                     furniture: dict[int, list[str]]) -> list[tuple[str, object]]:
    got = cache.get(pno)
    if got is None:
        got = []
        if 1 <= pno <= doc.n_pages:
            fur = set(furniture.get(pno, []))
            lines = doc.page(pno).lines
            for i, ln in enumerate(lines):
                t = normalize(_PUA_RE.sub("", ln.text()))
                if len(t) >= 4 and not is_folio_line(t) and t not in fur:
                    got.append((t, t.replace(" ", ""), ln,
                                lines[i - 1] if i else None))
        cache[pno] = got
    return got


def match_source_lines(doc, cache: dict, pno: int, block_text: str,
                       furniture: dict[int, list[str]]) -> list:
    """Raw source lines (page and page+1 — spanning paragraphs) whose text is
    contained in the block's. Zero matches must never fire a finding.

    Tiny lines substring-match into everything ('Islam' ⊆ any title naming
    it), so a matched line must carry a meaningful share of the block; the
    flow's own stripped furniture is excluded (a heading's running-head echo
    on the NEXT page — 'Titlexi', head+folio fused — matches its text)."""
    norm_block = normalize(_PUA_RE.sub("", block_text))
    if not norm_block:
        return []
    # space-insensitive form: prepress-lost spaces (MR) make the raw line
    # 'likethis' while the EPUB carries the restored text
    block_ns = norm_block.replace(" ", "")
    min_len = max(8.0, min(16.0, 0.3 * len(norm_block)))
    out = []
    for pg in (pno, pno + 1):
        for t, t_ns, ln, prev in _page_candidates(doc, cache, pg, furniture):
            if len(norm_block) < 8:
                # tiny block (chapter numeral '1'): exact match only —
                # partial_ratio aligns the SHORTER side, so any line
                # containing the digit would score 100
                if t == norm_block:
                    out.append((ln, prev))
                continue
            if len(t) < min_len:
                continue
            if t in norm_block or (len(t_ns) >= 8 and t_ns in block_ns):
                out.append((ln, prev))
            elif len(t) <= len(norm_block) + 12 and \
                    fuzz.partial_ratio(t, norm_block) >= 90:
                # fuzzy only when the line could plausibly fit INSIDE the
                # block (dehyphenation/space-seam slack)
                out.append((ln, prev))
    return out


# ------------------------------------------------------ gate 13

def check_size_fidelity(slices, preamble, rules, doc, body_size):
    class_size: dict[str, float] = {}
    collisions: set[str] = set()
    for f in sorted(doc.fonts.values(), key=lambda f: (f.family, f.size)):
        for suffix in ("", "/center"):
            cls = _css_class(f"{f.family}@{f.size:g}{suffix}")
            if cls in class_size and abs(class_size[cls] - f.size) > 0.05:
                collisions.add(cls)
            class_size[cls] = f.size
    findings: list[str] = []
    n_checked = n_collision = 0
    for page, blocks in [(0, preamble)] + sorted(slices.items()):
        for blk in blocks:
            if blk.tag == "figcaption" or set(blk.classes) & DESIGN_CENTER:
                continue
            ps_cls = next((c for c in blk.classes if c in class_size), None)
            if ps_cls is None:
                continue
            if ps_cls in collisions:
                n_collision += 1
                continue
            n_checked += 1
            anc = (("blockquote", set()),) if blk.in_blockquote else ()
            resolved = effective_font_size_em(rules, blk.tag,
                                              set(blk.classes), anc)
            expected = class_size[ps_cls] / body_size
            if abs(resolved - expected) > SIZE_TOL_EM:
                where = f"p.{page}" if page else "front"
                findings.append(
                    f'{where} <{blk.tag} class="{" ".join(blk.classes)}"> '
                    f"resolved {resolved:.3f}em, source {class_size[ps_cls]:g}pt "
                    f'expects {expected:.3f}em: "{blk.text[:60]}"')
    summary = (f"{n_checked} blocks checked, {len(findings)} size mismatches, "
               f"{n_collision} on collided classes (skipped)")
    return not findings, summary, findings


# ------------------------------------------------------ gate 14

def check_centered_witness(slices, rules, doc, geo, stops, body_famroot,
                           skip_pages, cache, furniture):
    findings: list[str] = []
    n_claims = n_unmatched = 0
    for page in sorted(slices):
        if page in skip_pages:
            continue
        for blk in slices[page]:
            got = resolve_block(rules, blk.tag, set(blk.classes),
                                (("blockquote", set()),) if blk.in_blockquote else ())
            val, src = got.get("text-align", ("", ""))
            if val != "center" or not src.startswith("class:"):
                continue
            if src.split(":", 1)[1] in DESIGN_CENTER:
                continue
            n_claims += 1
            pairs = match_source_lines(doc, cache, page, blk.text, furniture)
            if not pairs:
                n_unmatched += 1
                continue
            ok, why = genuinely_centered(pairs, doc, geo, stops, body_famroot,
                                         geo.shift(page))
            if not ok and len(pairs) > 1:
                # the same text can print TWICE at different geometry (MR
                # p.70: a verse line AND a centered aphorism head) — the
                # claim stands if any single full-coverage instance is
                # genuinely centered
                blk_len = len(normalize(_PUA_RE.sub("", blk.text)))
                for ln, prev in pairs:
                    t = normalize(_PUA_RE.sub("", ln.text()))
                    if len(t) >= 0.6 * blk_len and \
                            genuinely_centered([(ln, prev)], doc, geo, stops,
                                               body_famroot, geo.shift(page))[0]:
                        ok = True
                        break
            if not ok:
                findings.append(f'p.{page} <{blk.tag}> centered by {src} but '
                                f'{why}: "{blk.text[:60]}"')
    summary = (f"{n_claims} class-centered blocks, {len(findings)} without "
               f"centered source geometry, {n_unmatched} unmatched (skipped)")
    return not findings, summary, findings


# ------------------------------------------------------ gate 15

def check_emphasis(slices, paras, rules, pages_scope):
    pdf = {p: [0, 0, 0, 0] for p in pages_scope}   # letters, ital, bold, sc
    for g in paras:
        # mirror the EPUB side's DESIGN_CENTER skip: design blocks
        # (title pages, captions, rebuilt TOC) are out on both sides
        if g.role in SIG_SKIP_ROLES or g.style.startswith("__"):
            continue
        if g.start_page in pdf:
            row = pdf[g.start_page]
            row[0] += g.letters
            row[1] += g.italic_letters
            row[2] += g.bold_letters
            row[3] += g.sc_letters
    epub = {p: [0, 0, 0, 0] for p in pages_scope}
    for page in pages_scope:
        for blk in slices.get(page, []):
            if blk.tag == "figcaption" or set(blk.classes) & DESIGN_CENTER:
                continue
            got = resolve_block(rules, blk.tag, set(blk.classes),
                                (("blockquote", set()),) if blk.in_blockquote else ())
            css_italic = got.get("font-style", ("", ""))[0] == "italic"
            css_sc = got.get("font-variant", ("", ""))[0] == "small-caps"
            row = epub[page]
            row[0] += blk.letters
            row[1] += blk.letters if css_italic else blk.italic_letters
            row[2] += blk.bold_letters
            row[3] += blk.letters if css_sc else blk.sc_letters
    findings: list[str] = []
    tot_pdf = [0, 0, 0, 0]
    tot_epub = [0, 0, 0, 0]
    for page in sorted(pages_scope):
        a, b = pdf[page], epub[page]
        for i in range(4):
            tot_pdf[i] += a[i]
            tot_epub[i] += b[i]
        for i, ch in ((1, "italic"), (2, "bold"), (3, "smallcaps")):
            if not a[0] and not b[0]:
                continue
            fa = a[i] / a[0] if a[0] else 0.0
            fb = b[i] / b[0] if b[0] else 0.0
            if abs(fa - fb) > EMPH_FRAC_TOL and abs(a[i] - b[i]) > EMPH_CHAR_TOL:
                findings.append(f"p.{page} {ch}: pdf {a[i]}/{a[0]} "
                                f"vs epub {b[i]}/{b[0]}")
    deltas = []
    for i, ch in ((1, "italic"), (2, "bold"), (3, "smallcaps")):
        fa = tot_pdf[i] / tot_pdf[0] if tot_pdf[0] else 0.0
        fb = tot_epub[i] / tot_epub[0] if tot_epub[0] else 0.0
        deltas.append((ch, fa, fb))
    book_bad = [f"{ch} {fa:.3f}->{fb:.3f}" for ch, fa, fb in deltas
                if abs(fa - fb) > EMPH_BOOK_TOL]
    # >=2 page findings advises would-FAIL: with gate 17 structure-only, this
    # is the data-level net for whole-block emphasis drift (old BoK's
    # italic-class defect showed exactly 2 page findings)
    ok = len(findings) < 2 and not book_bad
    summary = ("book fractions pdf->epub: "
               + ", ".join(f"{ch} {fa:.3f}->{fb:.3f}" for ch, fa, fb in deltas)
               + f"; {len(findings)} page findings")
    return ok, summary, findings


# ------------------------------------------------------ gate 16

# print part labels that legitimately precede a title on the same PRINTED
# page but must never be fused INTO the title's heading element
_NUMWORD = (r"\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|"
            r"ten|eleven|twelve")
_PART_LABEL = re.compile(
    rf"(?:part|book|chapter|section|volume)\s+(?:{_NUMWORD})"
    r"|[ivxlcdm]+|\d+")
# raw-text form: keyword label + what follows it (group 2 starting with an
# alnum char = NO separator punctuation between label and title)
_PART_RAW = re.compile(
    rf"^((?:part|book|chapter|section|volume)\s+(?:{_NUMWORD}))\s+(\S.*)$",
    re.I)


def _foldn(s: str) -> str:
    """_fold + whitespace collapse: removing a separator dash leaves a double
    space behind, which must not defeat equality checks."""
    return " ".join(_fold(s).split())


def check_heading_census(slices, doc, geo, body_famroot, smallcaps_fams,
                         source_titles, skip_pages, cache, paras, body_size,
                         furniture):
    findings: list[str] = []
    audit: list[str] = []
    info: list[str] = []
    n_heads = n_unmatched = 0
    folded_titles = [_foldn(t) for t in source_titles]
    folded_pairs = [(f, t) for f, t in zip(folded_titles, source_titles)
                    if len(f) >= 8]
    for page in sorted(slices):
        for blk in slices[page]:
            if blk.tag not in _H_TAGS:
                continue
            text = blk.text.strip()
            # sentence audit (h3 gates; h1/h2 informational)
            body_txt = text.rstrip("\"”')’")
            if len(text) > HEAD_SENT_LEN and body_txt and body_txt[-1] in _SENT_END:
                line = f'p.{page} <{blk.tag}> sentence-like heading: "{text[:70]}"'
                (audit if blk.tag == "h3" else info).append(line)
            # fused-heading: heading text = <leading words> + a full TOC
            # title ('Part Two Oneness: …') — part-label leads gate, short
            # generic leads are informational (text-shape check, geometry-free)
            fh = _foldn(text)
            for ft, orig in folded_pairs:
                if fh != ft and fh.endswith(" " + ft):
                    lead = fh[: -len(ft)].strip()
                    if _PART_LABEL.fullmatch(lead):
                        audit.append(
                            f'p.{page} <{blk.tag}> heading fused with part '
                            f'label: "{text[:60]}" (TOC title: "{orig[:40]}")')
                    elif len(lead.split()) <= 4:
                        info.append(f'p.{page} <{blk.tag}> heading extends a '
                                    f'TOC title: "{text[:60]}"')
                    break
            else:
                # equal-but-unseparated: the TOC writes 'Part Two — Title'
                # (fold strips the dash, so folds are EQUAL) while the
                # heading glues label to title with nothing between — the
                # print stacks them as two display lines
                m = _PART_RAW.match(text)
                if m and m.group(2)[0].isalnum():
                    rest_f = _foldn(m.group(2))
                    if any(ft in (fh, rest_f) for ft, _ in folded_pairs):
                        audit.append(
                            f'p.{page} <{blk.tag}> part label fused into '
                            f'title without separator: "{text[:60]}"')
            if page in skip_pages:
                continue
            n_heads += 1
            pairs = match_source_lines(doc, cache, page, blk.text, furniture)
            if not pairs:
                n_unmatched += 1
                continue
            evidence = False
            for ln, _ in pairs:
                f = doc.fonts.get(ln.dominant_font())
                if f and (f.size >= geo.body_size + 1.0
                          or _fam_root(f.family) != body_famroot
                          or f.family in smallcaps_fams):
                    evidence = True
                    break
            if evidence:
                continue
            want = _fold(text)
            if want and any(fuzz.partial_ratio(want, t) >= 85
                            for t in folded_titles):
                continue  # TOC-corroborated flush-left head (by design)
            findings.append(f'p.{page} <{blk.tag}> body-type heading without '
                            f'TOC corroboration: "{text[:60]}"')
    # demotion direction: informational count only (ornament display numerals
    # are legitimately role p)
    heads_pages = {p for p in slices if any(b.tag in _H_TAGS for b in slices[p])}
    n_demote = sum(1 for g in paras
                   if g.role not in SIG_SKIP_ROLES and g.role not in _H_TAGS
                   and g.size_pt >= body_size + 4.0 and g.letters >= 3
                   and g.start_page not in heads_pages
                   and g.start_page not in skip_pages)
    ok = not findings and not audit
    summary = (f"{n_heads} headings checked, {len(findings)} promotion "
               f"suspects, {len(audit)} audit hits (h3 sentences / fused "
               f"part labels), {n_unmatched} unmatched; info: {len(info)} "
               f"long-h1/h2 or title-extending, "
               f"{n_demote} display-size non-heading paragraphs")
    return ok, summary, findings + audit + [f"info: {ln}" for ln in info[:3]]


# ------------------------------------------------------ gate 17

def _bucket(size_pt: float, body_size: float) -> str:
    if size_pt <= body_size - BUCKET_DELTA:
        return "small"
    if size_pt >= body_size + BUCKET_DELTA:
        return "display"
    return "body"


def _sig_fmt(sig) -> str:
    return "[" + ", ".join(b + ("·ctr" if c else "") for b, c in sig) + "]"


def _rle(tuples, snippets):
    out_t, out_s = [], []
    for t, s in zip(tuples, snippets):
        if not out_t or out_t[-1] != t:
            out_t.append(t)
            out_s.append(s)
    return out_t, out_s


def check_signature_diff(slices, paras, rules, body_size, pages_scope):
    by_page: dict[int, list[PdfParaGeo]] = {}
    for g in paras:
        if g.role in SIG_SKIP_ROLES or g.style.startswith("__") or not g.lines:
            continue
        by_page.setdefault(g.start_page, []).append(g)
    findings: list[str] = []
    n_pages = 0
    for page in sorted(pages_scope):
        pdf_t, pdf_s = [], []
        for g in by_page.get(page, []):
            pdf_t.append((_bucket(g.size_pt, body_size), "/center" in g.style))
            pdf_s.append(g.text[:50])
        ep_t, ep_s = [], []
        for blk in slices.get(page, []):
            if blk.tag == "figcaption" or set(blk.classes) & DESIGN_CENTER:
                continue
            anc = (("blockquote", set()),) if blk.in_blockquote else ()
            got = resolve_block(rules, blk.tag, set(blk.classes), anc)
            em = effective_font_size_em(rules, blk.tag, set(blk.classes), anc)
            val, src = got.get("text-align", ("", ""))
            centered = val == "center" and src.startswith("class:")
            ep_t.append((_bucket(em * body_size, body_size), centered))
            ep_s.append(blk.text[:50])
        if not pdf_t and not ep_t:
            continue
        n_pages += 1
        a, a_s = _rle(pdf_t, pdf_s)
        b, b_s = _rle(ep_t, ep_s)
        sm = SequenceMatcher(None, a, b, autojunk=False)
        ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
        if ops:
            tag, i1, i2, j1, j2 = ops[0]
            near = (a_s[i1] if i1 < len(a_s) else
                    (b_s[j1] if j1 < len(b_s) else ""))
            findings.append(f"p.{page}: pdf {_sig_fmt(a)} vs epub {_sig_fmt(b)} "
                            f'near "{near}"')
    summary = f"{n_pages} pages compared, {len(findings)} signature mismatches"
    return not findings, summary, findings


# ------------------------------------------------------ orchestrator

_NAMES = ("13 typo size fidelity", "14 typo centered witness",
          "15 typo emphasis", "16 typo heading census",
          "17 typo signature diff")


def run_typography_checks(*, doc, res, flow, cfg, labels, in_flow, body_docs,
                          css_text, source_entries) -> list[GateOut]:
    apply_qa_roles(flow, res, cfg)
    rules = parse_stylesheet(css_text)
    sl = slice_pages(body_docs, in_flow, labels)
    if not sl.ok:
        return [GateOut(n, True, [f"skipped — anchor slicing failed: {sl.detail}"])
                for n in _NAMES]

    geo = column_geometry(doc)
    body_family, _, rest = cfg.body_pstyle.partition("@")
    try:
        body_size = float(rest.split("/", 1)[0])
    except ValueError:
        body_size = geo.body_size or 11.0
    body_famroot = _fam_root(body_family)
    smallcaps_fams = {f for f, fl in cfg.charstyles.items() if fl.smallcaps}
    stops = left_stops(doc, geo, in_flow)
    paras = build_para_geo(doc, res, flow, cfg)
    disputed = {p.number for p in doc.pages
                if p.engine_agreement is not None and p.engine_agreement < 90}
    fig_pages = {p for fp in cfg.figure_pages for p in fp.pages}
    design_pages = set(cfg.toc_printed_pages) | fig_pages
    scope = [p for p in in_flow if p not in design_pages]
    scope_no_dispute = [p for p in scope if p not in disputed]
    cache: dict = {}

    results = [
        check_size_fidelity(sl.slices, sl.preamble, rules, doc, body_size),
        check_centered_witness(sl.slices, rules, doc, geo, stops, body_famroot,
                               design_pages | disputed, cache,
                               res.furniture_texts),
        check_emphasis(sl.slices, paras, rules, scope_no_dispute),
        check_heading_census(sl.slices, doc, geo, body_famroot, smallcaps_fams,
                             [t for t, _ in source_entries],
                             design_pages | disputed, cache, paras, body_size,
                             res.furniture_texts),
        check_signature_diff(sl.slices, paras, rules, body_size, scope),
    ]
    gates: list[GateOut] = []
    for name, (ok, summary, findings) in zip(_NAMES, results):
        lines = [("would-PASS — " if ok else "would-FAIL — ") + summary]
        lines += findings[:10]
        if len(findings) > 10:
            lines.append(f"… and {len(findings) - 10} more")
        gates.append(GateOut(name, ok, lines))
    return gates
