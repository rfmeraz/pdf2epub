"""Deterministic evidence gathering: PdfDoc -> Analysis (analysis/analysis.json).

Nothing here decides anything about the book — it computes the evidence the
conversion agent uses to write book.yaml, with proposals + confidence so the
draft config is reviewable. All agent decisions must trace back to a number
or sample in this file's output.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from rapidfuzz import fuzz

from .core.textnorm import is_folio_line, normalize
from .pdfmodel import PdfDoc, PdfLine, PdfPage

_ROMAN = re.compile(r"^[ivxlcdm]+$", re.I)
_EOL_HYPHEN = re.compile(r"[A-Za-z]-$")
_LOST_SPACE = re.compile(r"[a-z][.!?,;:][\"”’]?[A-Z“\"]")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
_RTL = re.compile(r"[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]")
_PUA = re.compile(r"[\ue000-\uf8ff]")

CENTER_TOL = 10.0   # pt: |line center - column center| below this = centered
CENTER_INSET = 10.0  # pt: centered lines start/end clear of both column edges
FULL_MEASURE_TOL = 10.0  # pt: a line within this of the column WIDTH is full-
                         # measure (left-aligned prose) — anchors a page shift


# ------------------------------------------------------------------ pstyles

@dataclass(slots=True)
class ColumnGeometry:
    """Modal edges of the justified text column (NOT the trim box — a book's
    text column is itself centered on the page, so trim-relative centering
    calls every full body line 'centered'; verified on Book of Knowledge)."""
    col_left: float
    col_right: float
    body_size: float = 0.0  # dominant font size (chars-weighted)
    # page -> how far the page's body block sits LEFT of the modal column
    # (recto/verso binding margins slide the whole block sideways ~18pt); the
    # centering test offsets its edges/center by this so a page-centered line
    # on a shifted page is still /center. Only meaningful shifts are recorded.
    page_shifts: dict[int, float] = field(default_factory=dict)

    @property
    def center(self) -> float:
        return (self.col_left + self.col_right) / 2

    def shift(self, page_no: int) -> float:
        return self.page_shifts.get(page_no, 0.0)


def column_geometry(doc: PdfDoc) -> ColumnGeometry:
    """Modal x0/x1 of long lines = the column edges. Shared by analyze and flow
    so pstyles derived in both places are identical."""
    widths = [ln.x1 - ln.x0 for p in doc.pages for ln in p.lines]
    if not widths:
        return ColumnGeometry(0.0, 1.0)
    wmax = max(widths)
    lefts: Counter[int] = Counter()
    rights: Counter[int] = Counter()
    for p in doc.pages:
        for ln in p.lines:
            if (ln.x1 - ln.x0) >= 0.55 * wmax:
                lefts[round(ln.x0)] += 1
                rights[round(ln.x1)] += 1
    col_left = float(lefts.most_common(1)[0][0]) if lefts else 0.0
    col_right = float(rights.most_common(1)[0][0]) if rights else wmax
    size_chars: Counter[float] = Counter()
    for p in doc.pages:
        for ln in p.lines:
            f = doc.fonts.get(ln.dominant_font())
            if f:
                size_chars[f.size] += len(ln.text())
    body_size = size_chars.most_common(1)[0][0] if size_chars else 0.0
    # per-page binding-margin shift: the page's own modal left edge vs the
    # global modal col_left (recto/verso pages slide sideways). Only a
    # LEFT-ALIGNED column establishes a margin: take the modal x0 of the wide
    # lines (>=3 sharing it), then CONFIRM it is a real left edge by requiring
    # at least one line there to be full-measure (width ~ col_w — shift-
    # invariant, and something a centered inset line never is). A stack of
    # same-width centered display lines (a title page, a book list) is inset,
    # never full-measure, so it yields no bogus shift and stays centered.
    col_w = col_right - col_left
    page_shifts: dict[int, float] = {}
    for p in doc.pages:
        wide = [ln for ln in p.lines if (ln.x1 - ln.x0) >= 0.55 * wmax]
        plefts = Counter(round(ln.x0) for ln in wide)
        if not plefts:
            continue
        edge, support = plefts.most_common(1)[0]
        full_here = any(round(ln.x0) == edge
                        and (ln.x1 - ln.x0) >= col_w - FULL_MEASURE_TOL
                        for ln in wide)
        # a shift means the WHOLE block slid: on a genuinely shifted page
        # no line spans the GLOBAL column (col_left to col_right). On a
        # verse-dense page (M&R p.165, a near-full-page ghazal) the verse
        # BASE INDENT outvotes the prose margin for the page-modal left
        # while full-measure prose anchors still span the global column —
        # their presence vetoes the bogus shift, keeping the page's true
        # offsets for the blocks.verse classifier. The x1 requirement keeps
        # the veto off shifted pages whose INSET content (a quote at
        # shift == inset, sufism verso) happens to stand at col_left.
        at_col_left = sum(1 for ln in wide
                          if abs(ln.x0 - col_left) <= 2.0
                          and ln.x1 >= col_right - FULL_MEASURE_TOL)
        shift = col_left - edge
        if support >= 3 and full_here and abs(shift) >= 6.0 \
                and at_col_left < 3:
            page_shifts[p.number] = float(shift)
    return ColumnGeometry(col_left, col_right, body_size, page_shifts)


def continues_justified_block(ln: PdfLine, prev: PdfLine | None,
                              size: float, geo: ColumnGeometry,
                              page_shift: float = 0.0) -> bool:
    """True when ``ln`` visually continues a justified block: the previous
    raw line shares its left edge, reaches the right margin, and sits one
    normal leading above. Such a line is a paragraph's LAST line whatever
    its midpoint says — the shape of every false-centering report so far
    (quote-block last lines, drop-cap wrap last lines)."""
    return (prev is not None
            and abs(prev.x0 - ln.x0) <= 2.0
            and prev.x1 >= (geo.col_right - page_shift) - 6.0
            and 0 < ln.y0 - prev.y0 <= 2.0 * max(size, 8.0))


def line_pstyle(ln: PdfLine, doc: PdfDoc, geo: ColumnGeometry,
                prev: PdfLine | None = None, page_shift: float = 0.0) -> str:
    """Cluster key for a line: DominantFamily@size[/center]. Centered means
    visually centered WITHIN the text column: inset from BOTH edges by at
    least 12% of the column width. A line starting at the body first-line
    indent whose length lands its midpoint near center is a PARAGRAPH, not a
    centered line ('This should suffice…', BoK p.206: x0 = indent, |center
    offset| = 1.6pt — print shows an ordinary indented paragraph). The same
    accident inside an INSET justified block (quote indent, drop-cap wrap:
    BoK p.193 'be the first of your people…', p.185 'may be categorized…')
    clears any inset floor, so a body-size line continuing a justified block
    (``prev``: same x0, full-right, normal leading) is never /center."""
    fid = ln.dominant_font()
    f = doc.fonts.get(fid)
    if f is None:
        return "?@0"
    base = f"{f.family}@{f.size:g}"
    line_c = (ln.x0 + ln.x1) / 2
    col_w = geo.col_right - geo.col_left
    # recto/verso binding shift: slide the modal edges/center to THIS page's
    # block so a page-centered line on a shifted page still reads as centered
    eff_left = geo.col_left - page_shift
    eff_right = geo.col_right - page_shift
    eff_center = geo.center - page_shift
    # the deep-inset requirement targets BODY-SIZE false positives only;
    # display-size heads legitimately span most of the column
    if geo.body_size and f.size <= geo.body_size + 1.0:
        inset = max(CENTER_INSET, 0.12 * col_w)
        if continues_justified_block(ln, prev, f.size, geo, page_shift):
            return base
    else:
        inset = CENTER_INSET
    if (abs(line_c - eff_center) <= CENTER_TOL
            and ln.x0 >= eff_left + inset
            and ln.x1 <= eff_right - inset):
        return base + "/center"
    return base


@dataclass(slots=True)
class Cluster:
    pstyle: str
    family: str
    size: float
    n_lines: int = 0
    n_chars: int = 0
    n_pages: int = 0
    first_page: int = 0
    samples: list[str] = field(default_factory=list)
    role: str = "p"
    confidence: str = "low"
    reason: str = ""


@dataclass(slots=True)
class Analysis:
    body_pstyle: str = ""
    body_size: float = 0.0
    clusters: list[Cluster] = field(default_factory=list)
    # furniture
    repeated_lines: list[dict] = field(default_factory=list)  # {text, count, pages, band}
    top_band: float = 0.0
    bottom_band: float = 0.0
    # folio / labels
    folio_agreement_pct: float | None = None
    folio_mismatches: list[dict] = field(default_factory=list)
    label_source_proposal: str = "pdf-page-labels"
    printed_folios: dict[int, str] = field(default_factory=dict)
    # headings & TOC witnesses
    headings: list[dict] = field(default_factory=list)  # {page, pstyle, text}
    toc_pages: list[int] = field(default_factory=list)
    toc_entries: list[dict] = field(default_factory=list)  # {page, text, label, target}
    toc_witness_table: list[dict] = field(default_factory=list)
    toc_source_proposal: str = "outline"
    # footnotes
    footnote_pages: list[int] = field(default_factory=list)
    footnote_marker_census: dict[str, int] = field(default_factory=dict)
    footnote_samples: list[dict] = field(default_factory=list)
    footnote_policy_proposal: str = "none"
    footnote_marker_proposal: str = "digits"
    # joining stats
    median_leading: float = 0.0
    indent_histogram: dict[str, int] = field(default_factory=dict)
    indent_threshold_proposal: float = 9.0
    eol_hyphen_count: int = 0
    lost_space_count: int = 0
    restore_spaces_proposal: bool = False
    dropcap_pages: list[int] = field(default_factory=list)
    # glyphs / languages
    pua_census: list[dict] = field(default_factory=list)
    cjk_pages: list[dict] = field(default_factory=list)   # {page, chars, vertical_lines}
    figure_pages_proposal: list[int] = field(default_factory=list)
    rtl_chars: int = 0
    # semantic block shapes (evidence for the blocks: judgment)
    verse_suspect_pages: list[dict] = field(default_factory=list)
    quote_suspect_pages: list[dict] = field(default_factory=list)
    list_marker_pages: list[dict] = field(default_factory=list)
    # layout anomalies
    column_suspect_pages: list[int] = field(default_factory=list)
    low_agreement_pages: list[dict] = field(default_factory=list)
    image_only_pages: list[int] = field(default_factory=list)
    # cover
    cover_proposal: dict = field(default_factory=dict)
    # render queue for the agent
    flagged_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ helpers

def _band_stats(doc: PdfDoc) -> tuple[float, float]:
    """Propose top/bottom furniture bands from where isolated first/last lines sit."""
    firsts, lasts = [], []
    for p in doc.pages:
        if len(p.lines) < 3:
            continue
        ys = sorted(ln.y0 for ln in p.lines)
        firsts.append(ys[0])
        gap_to_body = ys[1] - ys[0]
        if gap_to_body < 6:
            firsts.pop()  # first line flows straight into body: no head band here
        lasts.append(max(ln.y1 for ln in p.lines))
    # a head band exists when many pages have a detached first line
    top = 0.0
    if len(firsts) >= max(3, len(doc.pages) // 10):
        firsts.sort()
        top = firsts[int(len(firsts) * 0.8)] + 4  # cover 80% of detached heads
    return round(top, 1), 0.0


def furniture_template(text: str) -> str:
    """Normalize a candidate furniture line into its repeat-template.

    Folio digits vary page-to-page and are often FUSED to the head text
    ('14book of knowledge', 'Others13' — BoK), so template every digit run;
    roman folios only at the line edges ('civil' is all roman letters)."""
    t = normalize(text)
    t = re.sub(r"\d+", "#", t)
    # edge roman folios fuse to the head text too ('viiibook of knowledge',
    # 'Contentsix' — BoK front matter), so no \b on the outer side
    return re.sub(r"^[ivxlcdm]+|[ivxlcdm]+$", "#", t, flags=re.I).strip()


def detect_furniture(doc: PdfDoc, in_flow: list[PdfPage], min_pages: int = 3):
    """Repeated running-head candidates. TOP band only, plus folio-only last
    lines — scanning generic bottom lines drags footnote citations in
    (verified on Book of Knowledge: 'Abū Ṭālib al-Makkī' x18 templated).
    Shared with flowbuilder so the strip set is derived identically."""
    counter: Counter[str] = Counter()
    where: dict[str, list[int]] = defaultdict(list)
    band: dict[str, str] = {}
    for p in in_flow:
        cands = [("top", ln) for ln in p.lines[:2]]
        if p.lines and is_folio_line(normalize(p.lines[-1].text())):
            cands.append(("bottom", p.lines[-1]))
        for pos, ln in cands:
            t_tpl = furniture_template(ln.text())
            if not t_tpl or len(t_tpl) > 60:
                continue
            counter[t_tpl] += 1
            if p.number not in where[t_tpl]:
                where[t_tpl].append(p.number)
            band.setdefault(t_tpl, pos)
    out = []
    for t, c in counter.most_common():
        if c >= min_pages and t != "#":
            out.append({"text": t, "count": c, "pages": where[t][:8], "band": band[t]})
    return out


_FOLIO_BAND = 50.0  # pt from trim top/bottom: printed folios live here


def _plausible_folio(t: str) -> bool:
    if t.isdigit():
        return 0 < int(t) < 1000  # '2015' on a copyright page is not a folio
    return bool(_ROMAN.match(t)) and len(t) <= 8


def _printed_folio(p: PdfPage) -> str | None:
    """Folio printed on the page: a folio-only line, or a folio run at the
    edge of a running-head line — but only within the top/bottom bands
    (a chapter-opener's big '1' sits mid-page and is NOT a folio; BoK)."""
    if not p.lines:
        return None
    for ln in (p.lines[0], p.lines[-1]):
        in_band = (ln.y0 <= p.trim[1] + _FOLIO_BAND) or (ln.y1 >= p.trim[3] - _FOLIO_BAND)
        if not in_band:
            continue
        t = ln.text().strip()
        if is_folio_line(t) and _plausible_folio(t):
            return t
        if len(ln.runs) > 1:
            for r in (ln.runs[0], ln.runs[-1]):
                rt = r.text.strip()
                if rt and _plausible_folio(rt) and (rt.isdigit() or _ROMAN.match(rt)):
                    return rt
        # fused folio: leading/trailing digits glued to the head text
        m = re.match(r"^(\d{1,3})\D", t) or re.search(r"\D(\d{1,3})$", t)
        if m and _plausible_folio(m.group(1)):
            return m.group(1)
    return None


_TOC_LINE = re.compile(
    r"^(?P<title>.*?[^\s.·․])\s*(?:[.·․](?:\s*[.·․])+|\s{2,})\s*"
    r"(?P<folio>\d{1,4}|[ivxlcdm]{1,8})\s*$", re.I)


def _trailing_folio_entry(ln: PdfLine) -> tuple[str, str] | None:
    """(title, label) for a printed-TOC line.

    Two shapes in the wild: folio separated by leader dots INSIDE a shared
    span ('Foreword . . . . x' — BoK), or folio as its own gap-separated run
    with no leaders (Me and Rumi)."""
    text = ln.text().strip()
    m = _TOC_LINE.match(text)
    if m and len(m.group("title")) >= 2:
        return m.group("title"), m.group("folio").lower()
    if len(ln.runs) >= 2:
        last = ln.runs[-1]
        lt = last.text.strip().rstrip(".")
        if lt and (lt.isdigit() or _ROMAN.match(lt)) and _plausible_folio(lt):
            body = "".join(r.text for r in ln.runs[:-1]).strip()
            body = re.sub(r"[.․·\s]+$", "", body)
            if len(body) >= 2 and last.x0 - ln.runs[-2].x1 >= 6:
                return body, lt.lower()
    return None


# ------------------------------------------------------------------ analyze

def analyze(doc: PdfDoc, min_repeat_pages: int = 3) -> Analysis:
    a = Analysis()
    n = doc.n_pages
    in_flow = [p for p in doc.pages if p.lines]
    geo = column_geometry(doc)

    # ---- clusters
    clusters: dict[str, Cluster] = {}
    page_seen: dict[str, set[int]] = defaultdict(set)
    for p in in_flow:
        for i, ln in enumerate(p.lines):
            ps = line_pstyle(ln, doc, geo, p.lines[i - 1] if i else None,
                             page_shift=geo.shift(p.number))
            fid = ln.dominant_font()
            f = doc.fonts.get(fid)
            c = clusters.get(ps)
            if c is None:
                c = clusters[ps] = Cluster(pstyle=ps, family=f.family if f else "?",
                                           size=f.size if f else 0.0, first_page=p.number)
            c.n_lines += 1
            c.n_chars += len(ln.text())
            page_seen[ps].add(p.number)
            if len(c.samples) < 3 and 15 < len(ln.text()) < 90:
                c.samples.append(ln.text().strip())
    for ps, c in clusters.items():
        c.n_pages = len(page_seen[ps])
    body = max(clusters.values(), key=lambda c: c.n_chars, default=None)
    if body is None:
        a.warnings.append("no text clusters found — is this a scanned PDF?")
        return a
    a.body_pstyle = body.pstyle
    a.body_size = body.size

    # role guesses
    for c in sorted(clusters.values(), key=lambda c: -c.n_chars):
        ratio = c.size / body.size if body.size else 1.0
        centered = c.pstyle.endswith("/center")
        if c.pstyle == body.pstyle:
            c.role, c.confidence, c.reason = "p", "high", "dominant text cluster"
        elif ratio >= 1.8:
            c.role, c.confidence, c.reason = "title-page", "medium", f"size {c.size}pt >= 1.8x body"
        elif ratio >= 1.35:
            c.role, c.confidence, c.reason = "h1", "medium", f"size {c.size}pt >= 1.35x body"
        elif ratio >= 1.03 and centered:
            c.role, c.confidence, c.reason = "h2", "medium", f"{c.size}pt centered"
        elif centered and ratio >= 0.97:
            c.role, c.confidence, c.reason = "h3", "low", "centered, body-sized"
        elif ratio <= 0.85 and c.n_lines >= 10:
            c.role, c.confidence, c.reason = "footnote", "low", f"small ({c.size}pt), frequent"
        elif ratio < 0.97:
            c.role, c.confidence, c.reason = "p", "low", f"smaller than body ({c.size}pt)"
        else:
            c.role, c.confidence, c.reason = "p", "low", "body-like"
        a.clusters.append(c)

    # ---- furniture
    a.top_band, a.bottom_band = _band_stats(doc)
    a.repeated_lines = detect_furniture(doc, in_flow, min_repeat_pages)

    # ---- printed folios vs /PageLabels
    agree = 0
    total = 0
    for p in in_flow:
        pf = _printed_folio(p)
        if pf:
            a.printed_folios[p.number] = pf
            if p.label is not None:
                total += 1
                if normalize(pf).lower() == normalize(p.label).lower():
                    agree += 1
                elif len(a.folio_mismatches) < 20:
                    a.folio_mismatches.append({"page": p.number, "printed": pf,
                                               "label": p.label})
    if total:
        a.folio_agreement_pct = round(100 * agree / total, 1)
        if a.folio_agreement_pct >= 97:
            a.label_source_proposal = "pdf-page-labels"
        elif len(a.printed_folios) >= n // 3:
            a.label_source_proposal = "printed-folios"
        else:
            a.label_source_proposal = "synthetic"
    elif a.printed_folios:
        a.label_source_proposal = "printed-folios"
    else:
        a.label_source_proposal = "pdf-page-labels" if any(p.label for p in doc.pages) else "synthetic"

    # ---- headings timeline
    heading_pstyles = {c.pstyle for c in a.clusters if c.role in ("h1", "h2", "h3", "title-page")}
    for p in in_flow:
        for i, ln in enumerate(p.lines):
            ps = line_pstyle(ln, doc, geo, p.lines[i - 1] if i else None,
                             page_shift=geo.shift(p.number))
            if ps in heading_pstyles:
                t = ln.text().strip()
                if t and not is_folio_line(t):
                    a.headings.append({"page": p.number, "pstyle": ps, "text": t[:90]})

    # ---- printed-TOC detection + parse
    link_pages = Counter(l.page for l in doc.links)
    for p in in_flow[:40]:  # contents lives in front matter
        entries = [e for e in (_trailing_folio_entry(ln) for ln in p.lines) if e]
        has_contents_head = any("contents" in normalize(ln.text()).lower()
                                for ln in p.lines[:6])
        if len(entries) >= 5 or (has_contents_head and len(entries) >= 2) \
                or (link_pages.get(p.number, 0) >= 5):
            a.toc_pages.append(p.number)
            for title, label in entries:
                # target filled by the geometric link pairing pass below
                a.toc_entries.append({"page": p.number, "text": title,
                                      "label": label, "target": None})
    # geometric link pairing: entry line y-center inside link rect
    if a.toc_pages and doc.links:
        by_page: dict[int, list] = defaultdict(list)
        for l in doc.links:
            by_page[l.page].append(l)
        for p in doc.pages:
            if p.number not in a.toc_pages:
                continue
            ents = [e for e in a.toc_entries if e["page"] == p.number]
            lns = [ln for ln in p.lines if _trailing_folio_entry(ln)]
            for e, ln in zip(ents, lns):
                yc = (ln.y0 + ln.y1) / 2
                for l in by_page.get(p.number, []):
                    if l.rect[1] - 2 <= yc <= l.rect[3] + 2:
                        e["target"] = l.target_page
                        break

    # ---- three-way witness table (outline | printed entry | heading on target page)
    heads_by_page: dict[int, list[str]] = defaultdict(list)
    for h in a.headings:
        heads_by_page[h["page"]].append(h["text"])
    for o in doc.outline:
        printed = next((e for e in a.toc_entries
                        if fuzz.partial_ratio(normalize(e["text"]).lower(),
                                              normalize(o.title).lower()) >= 85), None)
        cands = heads_by_page.get(o.target_page, []) + heads_by_page.get(o.target_page + 1, [])
        head_score = max((fuzz.partial_ratio(normalize(o.title).lower(), normalize(c).lower())
                          for c in cands), default=0)
        a.toc_witness_table.append({
            "outline": o.title, "level": o.level, "target": o.target_page,
            "printed": printed["text"] if printed else None,
            "heading_on_target": head_score >= 80,
        })
    if len(doc.outline) >= 10:
        a.toc_source_proposal = "outline"
    elif a.toc_entries:
        a.toc_source_proposal = "printed"
    elif doc.links:
        a.toc_source_proposal = "links"
    else:
        a.toc_source_proposal = "printed"
        a.warnings.append("no outline, no links, no printed-TOC parse — TOC needs agent attention")

    # ---- footnotes
    marker_census: Counter[str] = Counter()
    region_starts: Counter[str] = Counter()
    for p in in_flow:
        # bottom region: trailing small-font lines — but skip past the folio /
        # bottom furniture first (I&B ends every page with a 10pt folio line
        # BELOW the 9pt notes, which otherwise breaks the scan immediately)
        tail = list(reversed(p.lines))
        i = 0
        while i < len(tail) and tail[i].y1 >= p.trim[3] - _FOLIO_BAND and \
                is_folio_line(normalize(tail[i].text())):
            i += 1
        region = []
        for ln in tail[i:]:
            f = doc.fonts.get(ln.dominant_font())
            if f and f.size <= body.size - 1.5 and not ln.vertical:
                region.append(ln)
            else:
                break
        region.reverse()
        text = " ".join(ln.text() for ln in region).strip()
        if region and len(text) > 30:
            a.footnote_pages.append(p.number)
            if len(a.footnote_samples) < 5:
                a.footnote_samples.append({"page": p.number, "text": text[:150]})
            m = re.match(r"^(\d{1,3})[.)]\s|^([*†‡])", text)
            if m:
                region_starts["digit" if m.group(1) else "*"] += 1
        for ln in p.lines:
            for r in ln.runs:
                t = r.text.strip()
                if r.superscript and (t.isdigit() or t in ("*", "†", "‡")):
                    marker_census["*" if t in ("*", "†", "‡") else "digit"] += 1
                elif t == "*" and len(t) == len(r.text.strip()):
                    marker_census["*-inline"] += 1
    a.footnote_marker_census = dict(marker_census)
    if len(a.footnote_pages) >= 5:
        a.footnote_policy_proposal = "markers"
        # note-body leading pattern beats the superscript census: old PDFs
        # (I&B 2010) carry no superscript flags at all
        if region_starts:
            a.footnote_marker_proposal = region_starts.most_common(1)[0][0]
            if a.footnote_marker_proposal == "*":
                a.footnote_marker_proposal = "asterisk"
        else:
            digit = marker_census.get("digit", 0)
            star = marker_census.get("*", 0) + marker_census.get("*-inline", 0)
            a.footnote_marker_proposal = "digits" if digit >= star else "asterisk"
        if a.footnote_marker_proposal == "digit":
            a.footnote_marker_proposal = "digits"

    # ---- joining stats
    leadings: list[float] = []
    indents: Counter[int] = Counter()
    body_left: Counter[float] = Counter()
    for p in in_flow:
        body_lines = [ln for i, ln in enumerate(p.lines)
                      if line_pstyle(ln, doc, geo,
                                     p.lines[i - 1] if i else None,
                                     page_shift=geo.shift(p.number))
                      == body.pstyle]
        for prev, cur in zip(body_lines, body_lines[1:]):
            d = cur.y0 - prev.y0
            if 5 < d < 40:
                leadings.append(d)
        for ln in body_lines:
            body_left[round(ln.x0)] += 1
    base_left = body_left.most_common(1)[0][0] if body_left else 0
    for p in in_flow:
        for i, ln in enumerate(p.lines):
            if line_pstyle(ln, doc, geo,
                           p.lines[i - 1] if i else None,
                           page_shift=geo.shift(p.number)) == body.pstyle:
                off = round(ln.x0) - base_left
                if 2 < off < 60:
                    indents[off] += 1
                t = ln.text().rstrip()
                if _EOL_HYPHEN.search(t):
                    a.eol_hyphen_count += 1
                a.lost_space_count += len(_LOST_SPACE.findall(t))
    if leadings:
        leadings.sort()
        a.median_leading = round(leadings[len(leadings) // 2], 1)
    a.indent_histogram = {str(k): v for k, v in sorted(indents.items())}
    if indents:
        common = [k for k, v in indents.items() if v >= max(indents.values()) * 0.5]
        if common:
            a.indent_threshold_proposal = round(min(common) * 0.75, 1)
    a.restore_spaces_proposal = a.lost_space_count > n  # ~1 defect/page = systemic

    # drop caps: oversized 1-2 char line starting a page/paragraph
    for p in in_flow:
        for ln in p.lines:
            f = doc.fonts.get(ln.dominant_font())
            t = ln.text().strip()
            if f and body.size and f.size >= 2 * body.size and 1 <= len(t) <= 2 and t.isalpha():
                a.dropcap_pages.append(p.number)
                break

    # ---- PUA + languages
    pua: dict[str, dict] = {}
    for p in in_flow:
        cjk_chars = 0
        vert = 0
        for ln in p.lines:
            txt = ln.text()
            cjk_chars += len(_CJK.findall(txt))
            a.rtl_chars += len(_RTL.findall(txt))
            if ln.vertical:
                vert += 1
            for ch in _PUA.findall(txt):
                rec = pua.setdefault(ch, {"char": ch, "hex": f"U+{ord(ch):04X}",
                                          "count": 0, "families": set(), "pages": []})
                rec["count"] += 1
                fid = ln.dominant_font()
                for r in ln.runs:
                    if ch in r.text:
                        fid = r.font_id
                        break
                f = doc.fonts.get(fid)
                if f:
                    rec["families"].add(f.family)
                if len(rec["pages"]) < 5 and p.number not in rec["pages"]:
                    rec["pages"].append(p.number)
        if cjk_chars:
            a.cjk_pages.append({"page": p.number, "chars": cjk_chars, "vertical_lines": vert})
            if vert >= 3 and cjk_chars > 50:
                a.figure_pages_proposal.append(p.number)
    a.pua_census = [{**r, "families": sorted(r["families"])} for r in pua.values()]

    # ---- layout anomalies
    for p in in_flow:
        mids = [ln for ln in p.lines if p.trim[1] + 60 < ln.y0 < p.trim[3] - 60]
        if len(mids) >= 12:
            lefts = sorted(ln.x0 for ln in mids)
            col_w = p.trim[2] - p.trim[0]
            split = p.trim[0] + col_w / 2
            left_col = sum(1 for x in lefts if x < split - col_w * 0.1)
            right_col = sum(1 for x in lefts if x > split + col_w * 0.05)
            if left_col >= 6 and right_col >= 6 and not any(ln.vertical for ln in mids):
                # two clusters of line-starts -> suspect columns
                starts_right = [x for x in lefts if x > split]
                if starts_right and min(starts_right) - max(
                        [x for x in lefts if x <= split] or [p.trim[0]]) > 30:
                    a.column_suspect_pages.append(p.number)
    a.image_only_pages = [p.number for p in doc.pages if p.image_only]
    a.low_agreement_pages = [{"page": p.number, "score": p.engine_agreement}
                             for p in doc.pages
                             if p.engine_agreement is not None and p.engine_agreement < 90]

    # ---- verse-shaped blocks (same detector the build's verse-suspect
    # witness runs — one derivation, see blockshapes). Raw-line evidence at
    # init (no furniture strip yet), so the BUILD warning stays the
    # authoritative witness; this section exists to seed the blocks.verse
    # judgment with measured base/turn offsets per page range.
    from .blockshapes import (LIST_MARKERS, body_anchors,
                              quote_shape_suspects, verse_shape_suspects)

    med = a.median_leading or geo.body_size * 1.3 or 13.0
    for p in in_flow:
        if p.number in a.column_suspect_pages:
            continue
        shift = geo.shift(p.number)
        # a lone vertical line (a rotated caption/marginale) no longer voids
        # the whole page: the shape detectors filter vertical lines per-line
        # (blockshapes.verse_shape_suspects / body_anchors), so mask them and
        # keep scanning the horizontal body for verse/quote/list evidence
        vmask = [getattr(ln, "vertical", False) for ln in p.lines]

        def _sz(ln):
            f = doc.fonts.get(ln.dominant_font())
            return f.size if f else None

        centered = []
        for i, ln in enumerate(p.lines):
            ps = line_pstyle(ln, doc, geo, p.lines[i - 1] if i else None,
                             page_shift=shift)
            centered.append("/center" in ps)
        vskip = [c or v for c, v in zip(centered, vmask)]
        for g in verse_shape_suspects(
                p.lines, geo.col_left - shift, geo.col_right - shift,
                geo.body_size, med, size_of=_sz, centered=centered):
            a.verse_suspect_pages.append({
                "page": p.number, "lines": [g.start, g.end - 1],
                "n_lines": g.end - g.start,
                "base": g.base_offsets, "turns": g.turn_offsets,
                "first": p.lines[g.start].text()[:60]})
        for q in quote_shape_suspects(p.lines, geo.body_size, size_of=_sz,
                                      skip=vskip):
            a.quote_suspect_pages.append({
                "page": p.number, "lines": [q.start, q.end - 1],
                "n_lines": q.end - q.start,
                "left_inset": q.left_offset, "right_inset": q.right_offset,
                "first": p.lines[q.start].text()[:60]})
        pl_anchors = body_anchors(p.lines, geo.body_size, size_of=_sz,
                                  skip=vskip)
        if pl_anchors is not None:
            for mk, rx in LIST_MARKERS.items():
                hits = [(i, ln) for i, ln in enumerate(p.lines)
                        if not vskip[i] and rx.match(ln.text())
                        and (sz := _sz(ln)) is not None
                        and abs(sz - geo.body_size) <= 1.5]
                # a list needs >=2 marker lines at ONE shared entry stop
                stops: dict[float, list[int]] = {}
                for i, ln in hits:
                    off = round(ln.x0 - pl_anchors[0], 1)
                    key = next((s for s in stops if abs(s - off) <= 3.0),
                               off)
                    stops.setdefault(key, []).append(i)
                for off, idxs in stops.items():
                    if len(idxs) >= 2:
                        a.list_marker_pages.append({
                            "page": p.number, "marker": mk,
                            "left": off, "n_items": len(idxs),
                            "first": p.lines[idxs[0]].text()[:60]})

    # ---- cover proposal
    p1 = doc.pages[0]
    if p1.image_only or (p1.n_images > 0 and p1.n_chars < 200):
        a.cover_proposal = {"mode": "render", "page": 1, "reason":
                            f"page 1 is image-dominated ({p1.n_images} image(s), {p1.n_chars} chars)"}
    else:
        a.cover_proposal = {"mode": "synthesize", "reason":
                            f"page 1 is text ({p1.n_chars} chars, {p1.n_images} images) — no cover in PDF"}

    # ---- agent render queue
    flagged = set(a.toc_pages) | set(a.figure_pages_proposal[:5]) | \
        set(p["page"] for p in a.low_agreement_pages[:10]) | \
        set(x["pages"][0] for x in a.pua_census if x["pages"]) | \
        set(a.footnote_pages[:2]) | set(a.column_suspect_pages[:4]) | \
        set(a.dropcap_pages[:2]) | {1} | set(a.image_only_pages[:4]) | \
        set(v["page"] for v in a.verse_suspect_pages[:3])
    body_start = next((p.number for p in in_flow
                       if a.printed_folios.get(p.number, "").isdigit()), None)
    if body_start:
        flagged.add(body_start)
    a.flagged_pages = sorted(x for x in flagged if 1 <= x <= n)
    return a


def analysis_to_dict(a: Analysis) -> dict:
    d = asdict(a)
    return d
