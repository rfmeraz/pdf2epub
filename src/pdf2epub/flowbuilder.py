"""Apply the recorded judgments: PdfDoc + book.yaml -> FlowDoc (core/model).

Deterministic passes, each consulting flow.overrides addressed by RAW extract
line index (stable across config changes): keep/drop during the furniture
strip, join/break during the paragraph join, role:<r> collected for the map
stage. Ambiguity WARNs (never silently drops); every warning also lands in
build/warnings.md with a ready-to-paste override snippet.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .analyze import (
    ColumnGeometry,
    _FOLIO_BAND,
    _printed_folio,
    _trailing_folio_entry,
    column_geometry,
    detect_furniture,
    furniture_template,
    line_pstyle,
)
from .blockshapes import (
    LIST_MARKERS,
    body_anchors,
    justified_rights,
    quote_shape_runs,
    verse_shape_groups,
    verse_shape_suspects,
)
from .config import PdfBookConfig
from .core.model import (
    Figure,
    FlowDoc,
    InlinePageBreak,
    Note,
    NoteRef,
    PageAnchor,
    Paragraph,
    RunFormat,
    SourceRef,
    TextRun,
)
from .core.textnorm import int_to_roman, is_folio_line, normalize
from .pdfmodel import PdfDoc, PdfLine, PdfRun
from .textfix import (
    dehyphenate_join,
    expand_ligatures,
    probe_text,
    restore_space_seam,
    restore_spaces,
    swap_quote_sides,
)

_PUA_RE = re.compile(r"[\ue000-\uf8ff]")
# note bodies start '9. text' (I&B), '9) text', or '1<TAB>text' (BoK)
_NOTE_START_DIGIT = re.compile(r"^\s*(\d{1,3})(?:[.)]\s+|\t+| {2,})")
_NOTE_START_STAR = re.compile(r"^\s*([*†‡])\s*")

# dashes that, at a line end, signal a hyphenation/clause continuation rather
# than a paragraph-ending ragged-short line: ASCII/soft/unicode hyphens and
# en/em dashes (the closed-dash style breaks lines after '—' mid-sentence).
_CONT_DASHES = ("-", "­", "‐", "‑", "–", "—")


def _note_start(L: "_L", marker: str, doc: PdfDoc) -> bool:
    """True when a footnote-region line opens a new note. A marker set at note
    size and separated by punctuation/tab/2-spaces is caught by the text
    pattern; a marker RAISED or set one size down (this book prints '8' at 7pt
    over 9pt note text, so 'digit + single space' never matches the pattern)
    is caught by the head-run test: a superscript, or a smaller-font, leading
    digit/asterisk."""
    txt = L.ln.text()
    if marker == "digits":
        if _NOTE_START_DIGIT.match(txt):
            return True
    elif _NOTE_START_STAR.match(txt):
        return True
    runs = [r for r in L.ln.runs if r.text.strip()]
    if not runs:
        return False
    r0 = runs[0]
    line_f = doc.fonts.get(L.ln.dominant_font())
    r0_f = doc.fonts.get(r0.font_id)
    raised = bool(r0.superscript) or (
        line_f is not None and r0_f is not None
        and r0_f.size <= line_f.size - 0.5)
    if not raised:
        return False
    head = r0.text.strip()
    if marker == "digits":
        return head.rstrip(".)").isdigit()
    return bool(head) and head[0] in "*†‡"


def _note_marker(L: "_L", marker: str) -> str:
    """The marker STRING of a note-region line (for in-body ref matching):
    the leading digit(s) or asterisk. Mirrors _note_start so a marker set one
    size down ('8 Let…', where the digit+delimiter text pattern misses) is
    still captured instead of falling back to '*'."""
    txt = L.ln.text()
    if marker == "digits":
        m = _NOTE_START_DIGIT.match(txt)
        if m:
            return m.group(1)
    else:
        m = _NOTE_START_STAR.match(txt)
        if m:
            return m.group(1)
    runs = [r for r in L.ln.runs if r.text.strip()]
    head = runs[0].text.strip() if runs else ""
    if marker == "digits":
        d = re.match(r"\d{1,3}", head)
        return d.group(0) if d else "*"
    return head[0] if head and head[0] in "*†‡" else "*"


@dataclass(slots=True)
class _Warn:
    msg: str
    page: int = 0
    line: int = -1
    snippet: str = ""  # ready-to-paste book.yaml override
    code: str = ""     # warnqueue.CODES key ("" -> flow-uncoded, fail-safe)


@dataclass(slots=True)
class FlowResult:
    flow: FlowDoc
    warns: list[_Warn] = field(default_factory=list)
    role_overrides_by_line: dict[tuple[int, int], str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    # (story_id, psr_index) of drop-cap paragraphs: the map stage re-applies
    # the first-dropcap class AFTER apply_roles rebuilds Paragraph.classes
    dropcap_srcs: set[tuple[str, int]] = field(default_factory=set)
    # note_id -> printed marker ('7', '*') — QA strips these tokens from
    # ground truth (the EPUB renumbers its noterefs)
    note_markers: dict[str, str] = field(default_factory=dict)
    # page -> [(marker, RAW note text on that page)] that physically SITS on
    # the page; the QA ground truth excises per source page (a footnote
    # wrapping p.N->p.N+1 keeps half its text on each, so the whole-note string
    # matches neither). marker is set only on the note's first page.
    note_raw_by_page: dict[int, list[tuple[str, str]]] = \
        field(default_factory=dict)
    # page -> normalized texts of furniture lines the flow stripped; the QA
    # ground truth excises exactly these (template sets diverge between the
    # engines for short-lived heads)
    furniture_texts: dict[int, list[str]] = field(default_factory=dict)
    # (story_id, psr_index) -> RAW (page, line idx) of every line the paragraph
    # consumed — Paragraph.src keeps only the first line; QA re-derives
    # per-paragraph geometry (sizes, insets, emphasis) from the extract IR
    para_lines: dict[tuple[str, int], list[tuple[int, int]]] = \
        field(default_factory=dict)
    # page -> normalized texts (whole lines AND their runs) of lines that
    # left the flow inside a figure_regions rect; the QA ground truth
    # excises exactly these (runs too: poppler splits what MuPDF fuses)
    region_texts: dict[int, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class _L:
    page: int
    idx: int  # RAW extract line index within the page
    ln: PdfLine
    ps: str
    # flow.columns pages only: 0-based column this (re-split) line belongs
    # to, -1 for full-width spanner lines and every non-columned page
    colno: int = -1
    # columned lines join by INDENT, not by _break_before: a column-left
    # line starts its own entry, a hanging-indent turnover continues one
    entry_break: bool = True
    # index into cfg.figure_regions when the line sits inside a region rect
    # (its text ships as a cropped raster, not as flowed text); -1 otherwise
    region: int = -1
    # justified right margin of this line's inset block (a block quote is inset
    # on BOTH sides, so its measure is narrower than the body column), or None
    # when the line is not in a tight-clustered justified run — see
    # _assign_block_right. The paragraph-join 'short line' test measures against
    # this instead of the body column, so a full line of an indented quote is
    # not misread as a ragged paragraph end.
    block_right: float | None = None
    # semantic block class stamped by the pre-join classifier (blocks.verse
    # specs): verse lines bypass _break_before entirely — their line breaks
    # are content, and the prose rules (ragged-short-line, _CONT_DASHES)
    # demonstrably fused printed couplets (M&R pp.35/46/165)
    block_class: str | None = None
    verse_turn: bool = False          # line sits at a deeper (turn) level
    verse_stanza_start: bool = False  # stanza gap opens a new stanza here
    list_entry: bool = False          # marker line opening a list item
    list_hang: bool = False           # line at the item's hang column
    list_sub: bool = False            # first-line indent WITHIN the item


def build_flow(doc: PdfDoc, cfg: PdfBookConfig, say=print) -> FlowResult:
    res = FlowResult(flow=FlowDoc(blocks=[], notes={}, style_usage=Counter(),
                                  text_dests={}, warnings=[]))
    warns = res.warns
    counts = Counter()
    geo = column_geometry(doc)
    body_ps = cfg.body_pstyle
    if not body_ps:
        raise SystemExit("styles.body_pstyle is required (see analysis report)")
    try:
        body_size = float(body_ps.split("@", 1)[1].split("/", 1)[0])
    except (IndexError, ValueError):
        body_size = 11.0

    # ---- overrides index (consumed-tracking: stale overrides fail the build)
    ov: dict[tuple[int, int], str] = {}
    for o in cfg.flow_overrides:
        ov[(o.page, o.line)] = o.action
    consumed: set[tuple[int, int]] = set()

    def override(page: int, idx: int) -> str | None:
        a = ov.get((page, idx))
        if a is not None:
            consumed.add((page, idx))
        return a

    # ---- furniture template set
    in_flow_nums = set(cfg.in_flow_pages(doc.n_pages))
    in_flow = [p for p in doc.pages if p.number in in_flow_nums]
    fur = {r["text"] for r in detect_furniture(doc, in_flow, cfg.repeat_min_pages)}
    fur |= {furniture_template(t) for t in cfg.furniture_extra}
    fur -= {furniture_template(t) for t in cfg.furniture_keep}
    top_band = cfg.top_band or 0.0

    # running-head baseline: template-matched heads sit at one very consistent
    # y0; a top line AT that baseline carrying a folio is furniture even when
    # its section is too short to hit repeat_min_pages (BoK recto heads)
    head_y0s: Counter[float] = Counter()
    for p in in_flow:
        for ln in p.lines[:2]:
            if furniture_template(ln.text()) in fur:
                head_y0s[round(ln.y0)] += 1
    head_base = head_y0s.most_common(1)[0][0] if sum(head_y0s.values()) >= 5 else None

    # ---- flow.columns: gutters are computed per SPEC (the whole columned
    # section), then applied per page
    col_splits_by_page: dict[int, list[float]] = {}
    _skip_head = lambda ln: (furniture_template(ln.text()) in fur
                             or (head_base is not None
                                 and round(ln.y0) == head_base))
    for cs in cfg.flow_columns:
        spec_pages = [doc.page(cp) for cp in cs.pages if cp in in_flow_nums]
        splits = _column_splits(spec_pages, cs.count, skip=_skip_head)
        if splits is None:
            warns.append(_Warn(
                f"flow.columns pages {cs.pages[0]}-{cs.pages[-1]}: expected "
                f"{cs.count} columns but the gutters were not found — pages "
                "left in y-sorted order (interleaving risk; fix the spec or "
                "exclude the pages)", cs.pages[0],
                code="columns-gutter-missing"))
            continue
        for cp in cs.pages:
            col_splits_by_page[cp] = splits

    # ---- per-page: strip furniture, split footnotes, collect body lines
    pages_lines: dict[int, list[_L]] = {}
    page_notes: dict[int, list[list[_L]]] = {}  # page -> list of note line-groups
    prev_had_notes = False
    for p in in_flow:
        regions_here = [(k, fr) for k, fr in enumerate(cfg.figure_regions)
                        if fr.page == p.number]
        kept: list[_L] = []
        for idx, ln in enumerate(p.lines):
            act = override(p.number, idx)
            if act == "drop":
                counts["override-drop"] += 1
                continue
            L = _L(p.number, idx, ln,
                   line_pstyle(ln, doc, geo, p.lines[idx - 1] if idx else None,
                               page_shift=geo.shift(p.number)))
            cx, cy = (ln.x0 + ln.x1) / 2, (ln.y0 + ln.y1) / 2
            for k, fr in regions_here:
                if fr.rect[0] <= cx <= fr.rect[2] and \
                        fr.rect[1] <= cy <= fr.rect[3]:
                    # the line ships inside the region's raster; record its
                    # text (and per-run fragments — poppler splits what
                    # MuPDF fuses) for the QA ground-truth excision
                    L.region = k
                    texts = res.region_texts.setdefault(p.number, [])
                    texts.append(normalize(ln.text()))
                    texts.extend(t for r in ln.runs
                                 if len(t := normalize(r.text)) >= 3)
                    counts["region-lines"] += 1
                    break
            if L.region >= 0:
                kept.append(L)
                continue
            if act == "keep":
                counts["override-keep"] += 1
                kept.append(L)
                continue
            near_top = ln.y0 <= p.trim[1] + max(top_band, _FOLIO_BAND)
            near_bot = ln.y1 >= p.trim[3] - _FOLIO_BAND
            first_or_last = idx <= 1 or idx >= len(p.lines) - 2
            t_norm = normalize(ln.text())
            if first_or_last and (near_top or near_bot):
                tpl = furniture_template(ln.text())
                # a shifted-CMap folio arrives as control bytes; probe the
                # REPAIRED text so it is recognized (and stripped) as a folio
                folio_norm = normalize(probe_text(
                    ln.text(), cfg.shifted_cmap_repair, cfg.shifted_cmap_highmap))
                if is_folio_line(folio_norm):
                    counts["furniture-folio"] += 1
                    res.furniture_texts.setdefault(p.number, []).append(folio_norm)
                    continue
                if tpl in fur:
                    counts["furniture-head"] += 1
                    res.furniture_texts.setdefault(p.number, []).append(t_norm)
                    continue
                if (head_base is not None and abs(ln.y0 - head_base) <= 3
                        and re.search(r"^#|#$", tpl)):
                    counts["furniture-baseline"] += 1
                    res.furniture_texts.setdefault(p.number, []).append(t_norm)
                    continue
                if near_top and top_band and ln.y0 <= p.trim[1] + top_band:
                    warns.append(_Warn(
                        f"p.{p.number} line {idx}: unrecognized top-band line kept: "
                        f"{ln.text()[:60]!r}", p.number, idx,
                        f"{{page: {p.number}, line: {idx}, action: drop, note: FILL}}",
                        code="top-band-kept"))
            kept.append(L)

        if p.number in col_splits_by_page and kept:
            kept = _column_resplit(kept, col_splits_by_page[p.number], doc,
                                   cfg, geo, counts)

        # footnote region split (bottom small-font block); flow.columns pages
        # are tabular back matter and carry no footnote apparatus — their
        # all-small-font body would otherwise read as one huge note region
        notes_here: list[list[_L]] = []
        if cfg.footnote_policy == "markers" and kept \
                and p.number not in col_splits_by_page:
            max_sz = cfg.footnote_region_max_size or (body_size - 1.5)
            region: list[_L] = []
            for L in reversed(kept):
                f = doc.fonts.get(L.ln.dominant_font())
                if L.region < 0 and f and f.size <= max_sz and not L.ln.vertical:
                    region.append(L)
                else:
                    break
            region.reverse()
            # the length guard keeps stray small-font page-bottom fragments
            # in the body, but a region carrying a note MARKER is a note at
            # ANY length — '15. Ibid., p. 51.' is 17 chars, and the guard
            # left it (and notes 16/17/30) leaking into I&B's prose, twice
            # SPLITTING a sentence mid-flow
            if region and (
                    len(" ".join(x.ln.text() for x in region)) > 20
                    or any(_note_start(L, cfg.footnote_marker, doc)
                           for L in region)):
                # small font is NOT sufficient — 9pt block quotes sit at page
                # bottoms too (BoK p.186). The note region starts at the FIRST
                # marker line; small-font lines above it stay body.
                # A region with no marker at all is body — unless it
                # continues the previous page's notes (merge pass below).
                first_marked = next((i for i, L in enumerate(region)
                                     if _note_start(L, cfg.footnote_marker, doc)),
                                    None)
                prev_page_had_notes = prev_had_notes
                if first_marked is None and not prev_page_had_notes:
                    region = []
                elif first_marked and first_marked > 0 and not prev_page_had_notes:
                    region = region[first_marked:]
                if region:
                    kept = kept[:len(kept) - len(region)]
                    cur: list[_L] = []
                    for L in region:
                        if _note_start(L, cfg.footnote_marker, doc) and cur:
                            notes_here.append(cur)
                            cur = []
                        cur.append(L)
                    if cur:
                        notes_here.append(cur)
        pages_lines[p.number] = kept
        page_notes[p.number] = notes_here
        prev_had_notes = bool(notes_here)

    # ---- footnotes wrapping across pages: a region whose first chunk has no
    # marker prefix continues the PREVIOUS page's last note (BoK p.56->57)
    if cfg.footnote_policy == "markers":
        prev_last_group: list[_L] | None = None
        for pno in sorted(page_notes):
            groups = page_notes[pno]
            if groups and prev_last_group is not None and \
                    not _note_start(groups[0][0], cfg.footnote_marker, doc):
                prev_last_group.extend(groups.pop(0))
                counts["note-continuation"] += 1
            if groups:
                prev_last_group = groups[-1]

    # ---- printed-TOC pages -> toc-entry paragraphs
    toc_paras: dict[int, list[Paragraph]] = {}
    if cfg.toc_handling == "rebuild":
        for pno in cfg.toc_printed_pages:
            paras: list[Paragraph] = []
            last_entry: Paragraph | None = None
            toc_lines = pages_lines.get(pno, [])
            skip_idx: set[int] = set()
            for ti, L in enumerate(toc_lines):
                if ti in skip_idx:
                    continue
                ent = _trailing_folio_entry(L.ln)
                if not ent and ti + 1 < len(toc_lines):
                    # a PART title carries its folio as a separate bare line
                    # at the right edge on (almost) the same baseline (M&R:
                    # 'My Years without Mawlana' + '1'); without this pairing
                    # the part line fused into the previous entry as a fake
                    # wrapped-title continuation
                    nl = toc_lines[ti + 1].ln
                    nt = nl.text().strip().rstrip(".")
                    if nt and len(nt) <= 5 and \
                            (nt.isdigit() or re.fullmatch(
                                r"[ivxlc]+", nt, re.I)) and \
                            nl.x0 > (geo.col_left + geo.col_right) / 2 and \
                            abs(nl.y0 - L.ln.y0) <= 6.0 and \
                            len(L.ln.text().strip()) >= 2:
                        ent = (L.ln.text().strip(), nt.lower())
                        skip_idx.add(ti + 1)
                if ent:
                    title, label = ent
                    fixed = _apply_textfix([TextRun(f"{title}\t{label}", RunFormat())],
                                           cfg, counts, L.page)
                    text = "".join(r.text for r in fixed if isinstance(r, TextRun))
                    last_entry = Paragraph(
                        style="__toc__",
                        items=[TextRun(text, RunFormat())],
                        src=SourceRef(f"p{L.page:04d}", L.idx))
                    paras.append(last_entry)
                elif L.ps != body_ps and "center" in L.ps:
                    paras.append(Paragraph(
                        style=L.ps,
                        items=_apply_textfix(_mk_runs(L.ln, cfg, doc), cfg, counts,
                                             L.page),
                        src=SourceRef(f"p{L.page:04d}", L.idx)))
                elif last_entry is not None:
                    # continuation of a wrapped entry title
                    t = last_entry.items[0].text
                    title, _, label = t.rpartition("\t")
                    cont = L.ln.text().strip()
                    last_entry.items[0].text = f"{title} {cont}\t{label}"
                    counts["toc-continuation"] += 1
                else:
                    warns.append(_Warn(
                        f"p.{pno} line {L.idx}: unparsed TOC-page line kept as text: "
                        f"{L.ln.text()[:50]!r}", pno, L.idx,
                        code="toc-line-unparsed"))
                    paras.append(Paragraph(
                        style=L.ps,
                        items=_apply_textfix(_mk_runs(L.ln, cfg, doc), cfg, counts,
                                             L.page),
                        src=SourceRef(f"p{L.page:04d}", L.idx)))
            toc_paras[pno] = paras
    elif cfg.toc_handling == "drop":
        for pno in cfg.toc_printed_pages:
            toc_paras[pno] = []

    # ---- labels
    labels = _page_labels(doc, cfg, warns)

    # ---- median leading for the gap rule
    leadings: list[float] = []
    for pno, lines in pages_lines.items():
        blines = [L for L in lines if L.ps == body_ps]
        for a, b in zip(blines, blines[1:]):
            d = b.ln.y0 - a.ln.y0
            if 5 < d < 40:
                leadings.append(d)
    leadings.sort()
    med_lead = leadings[len(leadings) // 2] if leadings else body_size * 1.3

    # ---- per-page inset-block right margins (block quotes measure narrower
    # than the body column; see _assign_block_right and _break_before)
    for lines in pages_lines.values():
        _assign_block_right(lines)

    # ---- semantic block classification: verse, per blocks.verse specs.
    # Runs BEFORE the join loop; classified lines bypass _break_before (the
    # flow.columns entry_break precedent). class:verse/class:prose overrides
    # correct the geometry; a spec that classifies nothing is stale (config
    # bug). The uncalibrated suspect witness runs on EVERY book afterwards —
    # that is how a future book's verse is discovered.
    class_applied: set[tuple[int, int]] = set()
    verse_spec_by_page: dict[int, int] = {}
    for si, vs in enumerate(cfg.blocks_verse):
        for pg in vs.pages:
            verse_spec_by_page.setdefault(pg, si)
    spec_groups = Counter()
    if cfg.blocks_verse:

        def _stamp(lines, g, si):
            spec_groups[si] += 1
            counts["verse-groups"] += 1
            for pos, x in enumerate(range(g.start, g.end)):
                L = lines[x]
                L.block_class = "verse"
                L.verse_turn = g.levels[pos] == "turn"
                L.verse_stanza_start = g.stanza_starts[pos]
                # verse lines whose midpoint chanced near column center
                # were mislabeled /center (the false-center trap); the
                # class supersedes the guess
                L.ps = L.ps.replace("/center", "")
                counts["verse-lines"] += 1

        prev_page_ends_verse = False
        # a candidate run touching a page bottom that could not be accepted
        # alone (a couplet's base line before the page turn) is held PENDING
        # and stamped only if the next spec page's top run accepts the union
        pending: tuple[list, "object", int] | None = None  # (lines, tail, si)
        vcarried: tuple[float, float] | None = None
        for pno in sorted(pages_lines):
            si = verse_spec_by_page.get(pno)
            lines = pages_lines[pno]
            if si is None or not lines:
                prev_page_ends_verse = False
                pending = None
                continue
            vs = cfg.blocks_verse[si]
            blocked, forced = [], []
            for L in lines:
                act = ov.get((L.page, L.idx))
                if act in ("class:verse", "class:prose"):
                    consumed.add((L.page, L.idx))
                    class_applied.add((L.page, L.idx))
                blocked.append(L.region >= 0 or L.block_right is not None
                               or act == "class:prose")
                forced.append(act == "class:verse")

            def _size(ln):
                f = doc.fonts.get(ln.dominant_font())
                return f.size if f else None

            # offsets anchor to the page's OWN body edges, never the
            # modal-column shift frame: on inset-dominated pages the shift
            # detector keys off the verse inset itself (I&B verso p.86:
            # modal left 90 = the verse lines, shift -18, every offset
            # wrong). Same doctrine as the quote pass; the carried
            # substitution covers verse-dominated pages whose apparent
            # body-left IS the verse base.
            v_anchors = body_anchors(
                [L.ln for L in lines], body_size, size_of=_size,
                skip=[L.region >= 0 for L in lines])
            if v_anchors is not None and vcarried is not None and vs.base \
                    and abs(v_anchors[0] - (vcarried[0] + vs.base[0])) \
                    <= vs.tol:
                v_anchors = vcarried
            elif v_anchors is not None:
                vcarried = v_anchors
            if v_anchors is None:
                v_anchors = vcarried
            if v_anchors is None:
                shift = geo.shift(pno)
                v_anchors = (geo.col_left - shift, geo.col_right - shift)
            eff_left, ref_right = v_anchors

            groups, tail = verse_shape_groups(
                [L.ln for L in lines], eff_left, ref_right, body_size,
                med_lead, vs.base, vs.turns, tol=vs.tol,
                stanza_gap=vs.stanza_gap, size_of=_size,
                blocked=blocked, forced=forced,
                allow_turn_start=prev_page_ends_verse,
                carry_levels=(pending[1].levels if pending else None))
            if pending and groups and groups[0].start == 0 and \
                    not groups[0].stanza_starts[0]:
                # the union was accepted: stamp the carried tail on ITS page
                # (the join loop runs after the whole classification pass)
                _stamp(pending[0], pending[1], pending[2])
            pending = (lines, tail, si) if tail is not None else None
            for g in groups:
                _stamp(lines, g, si)
            prev_page_ends_verse = bool(lines) and \
                lines[-1].block_class == "verse"
        stale_specs = [i for i in range(len(cfg.blocks_verse))
                       if not spec_groups.get(i)]
        if stale_specs:
            raise SystemExit(
                "stale blocks.verse (classified no groups): entries " +
                ", ".join(f"#{i} pages {cfg.blocks_verse[i].pages[:6]}…"
                          if len(cfg.blocks_verse[i].pages) > 6 else
                          f"#{i} pages {cfg.blocks_verse[i].pages}"
                          for i in stale_specs) +
                " — recalibrate base/turns or remove the spec")

    # ---- semantic block classification: lists, per blocks.lists specs.
    # Marker lines (decimal "43.Necessary" / bullet "• …") at the calibrated
    # entry stop open items; hang-column turnovers always JOIN their item
    # (the M&R apparatus shipped with nearly every note's first line split
    # from its body); lines at other insets — sub-lemma paragraphs with
    # their own first-line indent — keep the geometric rules and stay
    # separate paragraphs INSIDE the item. Verse classified above passes
    # through untouched (a ghazal quoted inside a note nests in its <li>).
    if cfg.blocks_lists:
        list_spec_by_page: dict[int, int] = {}
        for si, ls in enumerate(cfg.blocks_lists):
            for pg in ls.pages:
                list_spec_by_page.setdefault(pg, si)
        lspec_items = Counter()
        # entry stops are a property of the SPEC, not the page (the
        # flow.columns gutter precedent): cluster the marker lines' x0
        # across the spec's pages. Recto/verso binding shifts yield two
        # stops; marker look-alikes (a wrapped line opening with a year at
        # the hang column) fall below the cluster threshold.
        spec_stops: list[list[float]] = []
        for si, ls in enumerate(cfg.blocks_lists):
            rx = LIST_MARKERS[ls.marker]
            xs: list[float] = []
            for pg in ls.pages:
                for L in pages_lines.get(pg, []):
                    if L.region >= 0 or "/center" in L.ps:
                        continue
                    f = doc.fonts.get(L.ln.dominant_font())
                    if f is not None and f.size > body_size + 1.0:
                        continue
                    if rx.match(L.ln.text()):
                        xs.append(L.ln.x0)
            clusters: list[list[float]] = []
            for x in sorted(xs):
                if clusters and x - clusters[-1][-1] <= ls.tol:
                    clusters[-1].append(x)
                else:
                    clusters.append([x])
            top = max((len(c) for c in clusters), default=0)
            stops = sorted(sum(c) / len(c) for c in clusters
                           if len(c) >= max(2, 0.25 * top))
            spec_stops.append(stops)
        carried_open = False   # previous spec page ended inside an item
        last_num: dict[int, int] = {}  # spec -> last decimal marker seen
        prev_spec_page: int | None = None
        for pno in sorted(pages_lines):
            si = list_spec_by_page.get(pno)
            lines = pages_lines[pno]
            if si is None or not lines:
                continue
            if prev_spec_page is not None and pno != prev_spec_page + 1:
                carried_open = False  # a gap in the page range ends the item
            prev_spec_page = pno
            ls = cfg.blocks_lists[si]
            rx = LIST_MARKERS[ls.marker]
            stops = spec_stops[si]
            if not stops:
                continue  # stale check below reports it
            member_floor = min(stops) - ls.tol
            hang_cols = [st + ls.hang for st in stops]
            in_item = carried_open
            for L in lines:
                act = ov.get((L.page, L.idx))
                if act in ("class:list", "class:prose"):
                    consumed.add((L.page, L.idx))
                    class_applied.add((L.page, L.idx))
                if L.region >= 0 or act == "class:prose":
                    in_item = False
                    continue
                if L.block_class == "verse":
                    continue  # a poem inside the item: pass through
                f = doc.fonts.get(L.ln.dominant_font())
                sz = f.size if f else None
                text = L.ln.text()
                is_entry = (rx.match(text) is not None
                            and any(abs(L.ln.x0 - st) <= ls.tol
                                    for st in stops)
                            and "/center" not in L.ps
                            and (sz is None or sz <= body_size + 1.0))
                # a short lemma line at the item's own columns whose
                # midpoint chances near the column center is mislabeled
                # /center (the false-center trap; verse strips it too) —
                # p.371 'He sits in front of me like a son.' split the ol
                # in half. A centered line at an ARBITRARY x0 ('Part 2.'
                # dividers) still ends the item and breaks the list.
                false_center = "/center" in L.ps and L.ln.x0 <= \
                    max(hang_cols) + cfg.indent_threshold + ls.tol
                member = in_item and L.ln.x0 >= member_floor and \
                    ("/center" not in L.ps or false_center) and \
                    (sz is None or sz <= body_size + 1.0)
                if act == "class:list":
                    member = True
                    if not in_item:
                        is_entry = True
                if not is_entry and not member:
                    in_item = False
                    continue
                if member and "/center" in L.ps:
                    L.ps = L.ps.replace("/center", "")
                L.block_class = "list"
                counts["list-lines"] += 1
                if is_entry:
                    L.list_entry = True
                    in_item = True
                    lspec_items[si] += 1
                    counts["list-items"] += 1
                    if ls.marker == "decimal":
                        m = re.match(r"\d{1,3}", text)
                        num = int(m.group(0)) if m else 0
                        if si in last_num and num <= last_num[si]:
                            warns.append(_Warn(
                                f"p.{pno} line {L.idx}: list marker "
                                f"{num} follows {last_num[si]} — numbering "
                                "is not increasing (restart or misread "
                                f"marker): {text[:40]!r}", pno, L.idx,
                                code="list-marker-gap"))
                            counts["list-marker-gap"] += 1
                        last_num[si] = num
                else:
                    L.list_hang = any(abs(L.ln.x0 - hc) <= ls.tol
                                      for hc in hang_cols)
                    if not L.list_hang and ls.hang > 0 and \
                            L.ln.x0 > max(hang_cols) + 3.0:
                        # DEEPER than the hang column = a first-line indent
                        # WITHIN the item: a sub-lemma paragraph opens here
                        # (M&R sets lemma glosses at hang+9; 20+ fused after
                        # full-width lines the geometric rules cannot see —
                        # every one starts its own line in print)
                        L.list_sub = True
            carried_open = bool(lines) and \
                lines[-1].block_class in ("list", "verse") and in_item
        stale_l = [i for i in range(len(cfg.blocks_lists))
                   if not lspec_items.get(i)]
        if stale_l:
            raise SystemExit(
                "stale blocks.lists (classified no items): entries " +
                ", ".join(f"#{i} pages {cfg.blocks_lists[i].pages[:6]}…"
                          if len(cfg.blocks_lists[i].pages) > 6 else
                          f"#{i} pages {cfg.blocks_lists[i].pages}"
                          for i in stale_l) +
                " — recalibrate marker/hang or remove the spec")

    # ---- semantic block classification: quotes, per blocks.quotes specs.
    # The witness is the OPPOSITE of verse: a justified inset block (shared
    # x0 run whose right edges cluster — the same block_right that vetoes
    # verse). Stamps block_class ONLY; join decisions are untouched, so the
    # flow's paragraphs are identical with or without the spec. Insets are
    # measured from the page's OWN body anchors, not the modal column: on
    # quote-heavy pages the shift detector keys off the quote inset itself
    # (I&B rectos: 22 quote lines at x0=81 outvote 10 body lines at 63).
    if cfg.blocks_quotes:
        quote_spec_by_page: dict[int, int] = {}
        for si, qs in enumerate(cfg.blocks_quotes):
            for pg in qs.pages:
                quote_spec_by_page.setdefault(pg, si)
        qspec_runs = Counter()
        carried: tuple[float, float] | None = None
        prev_ends_quote = False
        prev_quote_page: int | None = None
        for pno in sorted(pages_lines):
            si = quote_spec_by_page.get(pno)
            lines = pages_lines[pno]
            if si is None or not lines:
                prev_ends_quote = False
                continue
            if prev_quote_page is not None and pno != prev_quote_page + 1:
                prev_ends_quote = False
            prev_quote_page = pno
            qs = cfg.blocks_quotes[si]
            blocked, forced = [], []
            for L in lines:
                act = ov.get((L.page, L.idx))
                if act in ("class:quote", "class:prose"):
                    consumed.add((L.page, L.idx))
                    class_applied.add((L.page, L.idx))
                blocked.append(L.region >= 0
                               or L.block_class in ("verse", "list")
                               or act == "class:prose")
                forced.append(act == "class:quote")

            def _size(ln):
                f = doc.fonts.get(ln.dominant_font())
                return f.size if f else None

            anchors = body_anchors(
                [L.ln for L in lines], body_size, size_of=_size,
                skip=[L.region >= 0 for L in lines])
            if anchors is not None and carried is not None and \
                    abs(anchors[0] - (carried[0] + qs.left_inset)) <= qs.tol:
                # a page mid-quotation can be almost ALL quote lines (BoK
                # p.260: one body line among thirty) — its apparent 'body
                # left' IS the previous page's quote target, and its right
                # anchor is the quote's own margin. Trust the carried body
                # edges instead.
                anchors = carried
            elif anchors is not None:
                carried = anchors
            if anchors is None:
                anchors = carried
            if anchors is None:
                continue  # sparse/display page: nothing to anchor against
            runs = quote_shape_runs(
                [L.ln for L in lines], anchors[0], anchors[1],
                qs.left_inset, qs.right_inset, body_size, tol=qs.tol,
                size_of=_size, rights=[L.block_right for L in lines],
                blocked=blocked, forced=forced,
                allow_continuation_top=prev_ends_quote)
            for r in runs:
                qspec_runs[si] += 1
                counts["quote-runs"] += 1
                for x in range(r.start, r.end):
                    lines[x].block_class = "quote"
                    counts["quote-lines"] += 1
            prev_ends_quote = bool(lines) and \
                lines[-1].block_class == "quote"
        stale_q = [i for i in range(len(cfg.blocks_quotes))
                   if not qspec_runs.get(i)]
        if stale_q:
            raise SystemExit(
                "stale blocks.quotes (classified no runs): entries " +
                ", ".join(f"#{i} pages {cfg.blocks_quotes[i].pages[:6]}…"
                          if len(cfg.blocks_quotes[i].pages) > 6 else
                          f"#{i} pages {cfg.blocks_quotes[i].pages}"
                          for i in stale_q) +
                " — recalibrate insets or remove the spec")

    # verse-suspect witness (uncalibrated, all books): verse-shaped runs the
    # config does not cover are structure-loss risks — the joiner would shred
    # or fuse them as prose. Precision is kept high by the stricter suspect
    # detector; every firing is a render-verify queue item.
    for pno in sorted(pages_lines):
        if pno in col_splits_by_page or pno in toc_paras or pno in {
                pg for fp in cfg.figure_pages for pg in fp.pages}:
            continue
        lines = pages_lines[pno]
        if len(lines) < 3:
            continue
        shift = geo.shift(pno)
        suspects = verse_shape_suspects(
            [L.ln for L in lines], geo.col_left - shift,
            geo.col_right - shift, body_size, med_lead,
            size_of=lambda ln: (f.size if (f := doc.fonts.get(
                ln.dominant_font())) else None),
            blocked=[L.region >= 0 or L.block_right is not None
                     for L in lines],
            centered=["/center" in L.ps for L in lines])
        for g in suspects:
            if any(lines[x].block_class is not None
                   for x in range(g.start, g.end)):
                # covered by a recorded blocks: judgment (a bullet list of
                # short ragged epithets is verse-SHAPED — I&B pp.39/57)
                continue
            first = lines[g.start]
            warns.append(_Warn(
                f"p.{pno} lines {first.idx}..{lines[g.end - 1].idx}: "
                f"verse-shaped block (base {g.base_offsets}, turns "
                f"{g.turn_offsets} pt off column left) not covered by "
                f"blocks.verse: {first.ln.text()[:50]!r}",
                pno, first.idx,
                f"{{pages: [{pno}], base: {g.base_offsets}, "
                f"turns: {g.turn_offsets}, note: FILL render-verified}}",
                code="verse-suspect"))
            counts["verse-suspect"] += 1

    # ---- join pass, page by page, with cross-page continuation
    open_para: Paragraph | None = None
    open_is_body = False
    prev_L: _L | None = None
    pending_anchors: list[PageAnchor] = []
    para_last_page: dict[tuple[str, int], int] = {}
    note_queue: list[tuple[int, str, str]] = []  # (page, marker target, note_id)
    emitted_regions: set[int] = set()

    def close_para():
        nonlocal open_para, open_is_body
        if open_para is not None and open_para.text().strip():
            if cfg.restore_spaces:
                _restore_cross_run_spaces(open_para, counts)
            _collapse_cross_run_spaces(open_para)
            res.flow.blocks.append(open_para)
        open_para = None
        open_is_body = False

    fig_page_map = {}
    for fp in cfg.figure_pages:
        for pg in fp.pages:
            fig_page_map[pg] = fp

    for pno in sorted(pages_lines):
        anchor = PageAnchor(ordinal=pno, label=labels.get(pno, str(pno)),
                            approximate=False)
        lines = pages_lines[pno]

        if pno in fig_page_map:
            # whole page ships as a figure (JP-P4b); its text does NOT flow
            close_para()
            for a2 in pending_anchors:
                res.flow.blocks.append(a2)
            pending_anchors.clear()
            res.flow.blocks.append(anchor)
            fp = fig_page_map[pno]
            trim = doc.page(pno).trim
            alt = fp.alt_template.replace("{label}", labels.get(pno, str(pno)))
            res.flow.blocks.append(Figure(
                image_key=f"page-{pno:04d}.png",
                source_basename=f"page-{pno:04d}.png", pdf_page=pno,
                page_ordinal=pno, y_pt=trim[1], x_pt=trim[0],
                width_pt=trim[2] - trim[0], height_pt=trim[3] - trim[1],
                role="chinese-page", alt=alt))
            counts["figure-pages"] += 1
            prev_L = None
            if not fp.keep_text or not lines:
                continue
            # keep_text plates fall through: the page's typeset lines (a
            # heading over a facsimile letter) flow normally after the figure

        if pno in toc_paras:
            close_para()
            res.flow.blocks.append(anchor)
            res.flow.blocks.extend(toc_paras[pno])
            prev_L = None
            continue

        if not lines:
            anchor.approximate = True
            pending_anchors.append(anchor)
            continue

        # keep_text figure pages already emitted their anchor above
        anchor_placed = (pno in fig_page_map and fig_page_map[pno].keep_text)
        prev_dropcap = False
        for L in lines:
            if L.region >= 0:
                # the region's text ships as a cropped raster; emit its
                # Figure at the first region line, in flow position
                if L.region not in emitted_regions:
                    emitted_regions.add(L.region)
                    close_para()
                    if not anchor_placed:
                        ins = len(res.flow.blocks)
                        for a2 in pending_anchors:
                            res.flow.blocks.insert(ins, a2)
                            ins += 1
                        res.flow.blocks.insert(ins, anchor)
                        pending_anchors.clear()
                        anchor_placed = True
                    fr = cfg.figure_regions[L.region]
                    res.flow.blocks.append(Figure(
                        image_key=f"region-{fr.page:04d}-{L.region}.png",
                        source_basename=f"region-{fr.page:04d}-{L.region}.png",
                        pdf_page=fr.page, page_ordinal=fr.page,
                        y_pt=fr.rect[1], x_pt=fr.rect[0],
                        width_pt=fr.rect[2] - fr.rect[0],
                        height_pt=fr.rect[3] - fr.rect[1],
                        role="figure", alt=fr.alt))
                    counts["figure-regions"] += 1
                prev_L = None
                prev_dropcap = False
                continue
            act = override(L.page, L.idx)
            # drop-cap: oversized 1-2 letter line glues onto the next line
            f = doc.fonts.get(L.ln.dominant_font())
            is_dropcap = (cfg.reattach_dropcaps and f is not None
                          and f.size >= 2 * body_size
                          and 1 <= len(L.ln.text().strip()) <= 2
                          and L.ln.text().strip().isalpha())

            if prev_dropcap and act != "break":
                brk = False  # the letter's own paragraph continues here
            elif L.block_class == "verse":
                # verse lines bypass the geometric joiner: a stanza is ONE
                # paragraph, its lines joined by U+2028 in _append_line. The
                # prose rules (_CONT_DASHES, ragged-short-line) never apply
                # inside a group — they fused printed couplets (M&R p.46)
                brk = (act == "break") or (act != "join" and (
                    prev_L is None or prev_L.block_class != "verse"
                    or L.verse_stanza_start))
            elif prev_L is not None and prev_L.block_class == "verse":
                # prose resuming after verse always starts its own paragraph
                brk = act != "join"
            elif L.colno >= 0:
                # columned entry lines: indent decides (see _column_resplit)
                brk = (act == "break") or (act != "join" and L.entry_break)
            elif L.block_class == "list":
                if act in ("break", "join"):
                    brk = act == "break"
                elif prev_L is None or \
                        prev_L.block_class not in ("list", "verse"):
                    brk = True   # entering the list is a block boundary
                elif L.list_entry:
                    brk = True   # a marker line opens its own item (heals
                    #              the note-into-next-note fusions)
                elif prev_L.block_class == "verse":
                    brk = True   # apparatus resuming after an in-item poem
                elif L.list_sub:
                    # deeper than the hang column = the item's INSET block
                    # (lemma glosses, quoted passages). Stepping into it
                    # from the entry/hang level is a paragraph boundary
                    # (heals 20+ lemma fusions after full-width lines);
                    # WITHIN it the geometric rules hold — inset paragraphs
                    # have their own first-line indents at inset+18, and a
                    # per-line break shattered note 244's quotation
                    if prev_L.list_entry or prev_L.list_hang:
                        brk = True
                    else:
                        brk = _break_before(
                            L, prev_L, act, body_ps, cfg, geo, med_lead,
                            open_is_body, pno)
                elif L.list_hang:
                    # hang-column turnovers continue the item — the round-1
                    # split damage came from the indent-break rule (the
                    # entry sits at the column edge) — but a previous line
                    # that visibly ENDED its paragraph still breaks: a
                    # short entry line can be followed by a flush
                    # continuation paragraph at the hang column (p.341
                    # 'Intellect is a veil.' after '…See SPL 220-26.')
                    brk = _prev_short(prev_L, L, geo)
                else:
                    brk = _break_before(
                        L, prev_L, act, body_ps, cfg, geo, med_lead,
                        open_is_body, pno)
            elif prev_L is not None and \
                    prev_L.block_class != L.block_class and \
                    ("quote" in (prev_L.block_class, L.block_class)
                     or prev_L.block_class == "list"):
                # entering/leaving a classified quote or leaving a list IS a
                # block boundary in print (the verse precedent). The
                # geometric joiner cannot see some of these seams: I&B's
                # italic scripture quotes fused onto their intro prose on 38
                # boundaries — the ps-twin rule eats the style change, the
                # indent-break rule requires the ROMAN body ps, and the
                # leading gap sits under the threshold. Interior quote
                # joins stay fully geometric.
                brk = act != "join"
            else:
                brk = _break_before(L, prev_L, act, body_ps, cfg, geo, med_lead,
                                    open_is_body, pno)
            if act and act.startswith("role:"):
                brk = True  # an explicitly re-roled line is its own paragraph
            if is_dropcap:
                brk = True
            if brk:
                close_para()
                open_para = Paragraph(style=L.ps, items=[],
                                      src=SourceRef(f"p{L.page:04d}", L.idx))
                open_is_body = (L.ps == body_ps)
                if L.block_class == "verse":
                    open_para.block_class = "verse"
                    counts["verse-stanzas"] += 1
                elif L.block_class == "quote":
                    open_para.block_class = "quote"
                elif L.block_class == "list":
                    open_para.block_class = "list"
                    open_para.list_entry = L.list_entry
                if is_dropcap:
                    open_para.classes = ["first-dropcap"]
                    open_para.style = body_ps  # dropcap letter belongs to body text
                    open_is_body = True
                    res.dropcap_srcs.add((open_para.src.story_id,
                                          open_para.src.psr_index))
                    counts["dropcaps"] += 1
            inline_seam: int | None = None
            if not anchor_placed:
                # anchor sits before the first block that STARTS on this page;
                # a page whose first line CONTINUES the open paragraph gets an
                # exact InlinePageBreak at the run seam instead (the old
                # paragraph-granular deferral survives only as the whitespace
                # fallback below)
                if brk:
                    ins = len(res.flow.blocks)
                    if open_para is not None and res.flow.blocks and \
                            res.flow.blocks[-1] is open_para:
                        ins -= 1
                    for a2 in pending_anchors:
                        res.flow.blocks.insert(ins, a2)
                        ins += 1
                    res.flow.blocks.insert(ins, anchor)
                    pending_anchors.clear()
                    anchor_placed = True
                elif open_para is not None and open_para.text().strip():
                    # insertion index captured BEFORE _append_line so the
                    # join separator/dehyphenation lands on the previous
                    # TextRun first — never on the anchor seam
                    inline_seam = len(open_para.items)
                    anchor_placed = True
            if open_para is None:
                open_para = Paragraph(style=L.ps, items=[],
                                      src=SourceRef(f"p{L.page:04d}", L.idx))
                open_is_body = (L.ps == body_ps)
                if L.block_class == "verse":
                    open_para.block_class = "verse"
                    counts["verse-stanzas"] += 1
                elif L.block_class == "quote":
                    open_para.block_class = "quote"
                elif L.block_class == "list":
                    open_para.block_class = "list"
                    open_para.list_entry = L.list_entry
            if not brk and prev_L is not None and \
                    open_para.block_class in ("quote", "list") and \
                    L.block_class != open_para.block_class:
                # a paragraph mixing classed and prose lines can only arise
                # from an explicit join override (a recorded judgment) or a
                # dropcap glue; it ships OUTSIDE the blockquote/list
                open_para.block_class = None
                open_para.list_entry = False
            _append_line(open_para, L, cfg, doc, counts, glue=prev_dropcap,
                         verse=(L.block_class == "verse"
                                and open_para.block_class == "verse"))
            if L.block_class == "verse" and \
                    open_para.block_class == "verse" and L.verse_turn:
                open_para.verse_turns.append(sum(
                    it.text.count("\u2028") for it in open_para.items
                    if isinstance(it, TextRun)))
            if inline_seam is not None:
                # deferred anchors of interleaving blank pages flush here
                # first, keeping the page-list monotone
                for a2 in pending_anchors:
                    open_para.items.insert(
                        inline_seam, InlinePageBreak(a2.ordinal, a2.label))
                    inline_seam += 1
                pending_anchors.clear()
                open_para.items.insert(
                    inline_seam, InlinePageBreak(anchor.ordinal, anchor.label))
                counts["anchor-inline"] += 1
            key = (open_para.src.story_id, open_para.src.psr_index)
            para_last_page[key] = L.page
            res.para_lines.setdefault(key, []).append((L.page, L.idx))
            prev_dropcap = is_dropcap
            if act and act.startswith("role:"):
                res.role_overrides_by_line[(L.page, L.idx)] = act.split(":", 1)[1]
                consumed.add((L.page, L.idx))
            prev_L = L
        if not anchor_placed:
            # page contributed only continuation text: paragraph-granular
            # anchor lands before the next new block
            anchor.approximate = True
            pending_anchors.append(anchor)

        # register this page's notes; markers attach in the global post-pass
        for k, group in enumerate(page_notes.get(pno, []), 1):
            note_id = f"p{pno:04d}-{k}"
            note_paras = _note_paragraphs(group, cfg, doc, note_id, counts)
            res.flow.notes[note_id] = Note(note_id=note_id, paragraphs=note_paras)
            marker = _note_marker(group[0], cfg.footnote_marker)
            note_queue.append((pno, marker, note_id))
            res.note_markers[note_id] = marker
            # record the note's raw text split by the page each line sits on,
            # so the QA ground truth can excise a page-wrapping note from BOTH
            page_texts: dict[int, list[str]] = {}
            for L in group:
                page_texts.setdefault(L.page, []).append(L.ln.text())
            start_page = min(page_texts)
            for gp, txts in page_texts.items():
                res.note_raw_by_page.setdefault(gp, []).append(
                    (marker if gp == start_page else "", " ".join(txts)))

    close_para()
    for a2 in pending_anchors:
        res.flow.blocks.append(a2)
    if cfg.blocks_quotes:
        counts["quote-paras"] = sum(
            1 for b in res.flow.blocks
            if isinstance(b, Paragraph) and b.block_class == "quote")
    if cfg.blocks_lists:
        counts["list-paras"] = sum(
            1 for b in res.flow.blocks
            if isinstance(b, Paragraph) and b.block_class == "list")

    # ---- attach note markers (global pass: a marker can sit in a paragraph
    # that STARTED on the previous page)
    if note_queue:
        unmatched = _attach_noterefs(res.flow, note_queue, para_last_page,
                                     body_size, counts)
        for pno, target, note_id in unmatched:
            warns.append(_Warn(
                f"p.{pno}: no in-body marker found for note {note_id} "
                f"(expected {target!r}); ref attached at the end of the page's "
                "last paragraph", pno, -1, code="note-marker-missing"))

    # ---- stale overrides are config bugs
    stale = set(ov) - consumed
    # class: verbs count as applied only where the classifier saw them — a
    # class:verse on a page no blocks.verse spec covers must error, not
    # silently no-op through the join loop's generic override() read
    stale |= {k for k, a in ov.items()
              if a.startswith("class:") and k not in class_applied}
    if stale:
        raise SystemExit("stale flow.overrides (matched nothing): " +
                         ", ".join(f"page {p} line {i}" for p, i in sorted(stale)))
    used_fffd = {int(k.rsplit("-", 1)[1])
                 for k in list(counts) if k.startswith("_fffd-used-")}
    for k in list(counts):
        if k.startswith("_fffd-used-"):
            del counts[k]
    stale_fffd = [i for i in range(len(cfg.fffd_repairs)) if i not in used_fffd]
    if stale_fffd:
        raise SystemExit(
            "stale glyphs.fffd_repairs (matched no U+FFFD): entries " +
            ", ".join(f"#{i} pages {cfg.fffd_repairs[i].pages}"
                      for i in stale_fffd))
    if counts.get("fffd-unrepaired"):
        warns.append(_Warn(
            f"{counts['fffd-unrepaired']} unmapped-glyph U+FFFD chars survive "
            "outside glyphs.fffd_repairs pages — render-verify and add entries",
            code="fffd-unrepaired"))

    # ---- style usage + PUA gate
    for b in res.flow.blocks:
        if isinstance(b, Paragraph):
            res.flow.style_usage[b.style] += 1
    unmapped_pua = counts_pua_unmapped(res.flow, cfg)
    if unmapped_pua:
        listing = ", ".join(f"U+{ord(c):04X}×{n}" for c, n in unmapped_pua.items())
        if cfg.fail_on_unmapped_pua:
            raise SystemExit(f"unmapped private-use glyphs in flow: {listing} — "
                             "add glyphs.pua_map entries (verify on renders)")
        warns.append(_Warn(f"unmapped private-use glyphs: {listing}",
                           code="pua-unmapped"))

    res.counts = dict(counts)
    for w in warns:
        res.flow.warnings.append(w.msg)
    return res


# ------------------------------------------------------------------ helpers

def _ps_root(ps: str) -> str:
    """Fold italic variants into their roman base for break decisions
    ('TimesNewRomanPS-ItalicMT' == 'TimesNewRomanPSMT')."""
    fam, _, rest = ps.partition("@")
    fam = re.sub(r"[^A-Za-z0-9]", "", fam.replace("Italic", ""))
    return f"{fam}@{rest}"


# an inset block quote is indented on BOTH sides: its justified lines end
# short of the BODY column's right edge, so each would read as a ragged
# paragraph-ending line and the quote shatters line by line (the I&B Qurʾān
# quotes did exactly this). A run of >=2 consecutive same-inset lines whose
# right edges cluster to sub-point precision is JUSTIFIED — that shared edge is
# the block's OWN right margin, against which interior lines are full, not
# short. Ragged verse (line widths scatter by whole points) yields no cluster
# and keeps its meaningful line-by-line breaks. The tolerances live with the
# derivation in blockshapes (_JUST_LEFT_TOL / _JUST_RIGHT_TOL).


def _assign_block_right(lines: list[_L]) -> None:
    """Set L.block_right for lines in a justified inset block to that block's
    own right margin (the largest x1 that >=2 lines in the run reach). Runs
    with no such cluster — a lone inset line, or ragged verse — stay None and
    fall back to the body-column edge, preserving today's behavior. The
    derivation lives in blockshapes.justified_rights: the same cluster that
    vetoes verse is the blocks.quotes witness (one code path, never two)."""
    for L, m in zip(lines, justified_rights([L.ln for L in lines])):
        L.block_right = m


def _prev_short(prev: _L, L: _L, geo: ColumnGeometry) -> bool:
    """The bare ragged-paragraph-end signal of _break_before, without its
    indent rules: did ``prev`` visibly END its paragraph? Used for list
    hang-column lines, where the indent rules misfire by construction
    (the entry sits at the column edge) but a genuine paragraph end must
    still break."""
    col_w = geo.col_right - geo.col_left
    eff_right = geo.col_right - max(
        0.0, geo.col_left - min(prev.ln.x0, L.ln.x0))
    ref_right = prev.block_right if prev.block_right is not None else eff_right
    return (prev.ln.x1 < ref_right - max(18.0, 0.06 * col_w)
            and not prev.ln.text().rstrip().endswith(_CONT_DASHES))


def _break_before(L: _L, prev: _L | None, act: str | None, body_ps: str,
                  cfg: PdfBookConfig, geo: ColumnGeometry, med_lead: float,
                  open_is_body: bool, pno: int) -> bool:
    if act == "break":
        return True
    if act == "join":
        return False
    if prev is None:
        return True
    if L.ps != prev.ps and _ps_root(L.ps) != _ps_root(prev.ps):
        # a pstyle change breaks — but roman and its Italic twin are ONE
        # structural style (long italic quotes line-wrap between the two:
        # 'particu-'/'lar' broke mid-word on I&B without this)
        return True
    if "/center" in L.ps:
        if not cfg.join_center_lines:
            return True
        # joined center lines still respect the GAP rule: a copyright page's
        # 22pt block gaps are paragraph breaks even though every line is
        # /center (M&R p.vii shipped as ONE fused paragraph without this;
        # wrapped centered quotes at normal leading keep joining). The gap
        # scales with the LINE'S OWN size — display type leads wider, and a
        # body-scaled gap would split a two-line 21pt part title into two
        # h1 spine files (the HU Chapter-55 defect shape)
        try:
            _sz = float(L.ps.split("@", 1)[1].split("/", 1)[0])
        except (IndexError, ValueError):
            _sz = 0.0
        return (L.ln.y0 - prev.ln.y0) > \
            cfg.gap_factor * max(med_lead, 1.35 * _sz)
    # a first-line indent is indented relative to the PREVIOUS line too —
    # drop-cap wrap lines all sit at the same inset (BoK p.35: 3 lines at
    # x0=87.9 around a 52.5pt initial) and must not break line-by-line
    indented = (L.ln.x0 - geo.col_left >= cfg.indent_threshold
                and L.ln.x0 - prev.ln.x0 >= cfg.indent_threshold - 2)
    # a justified line only ends visibly SHORT of the right margin when its
    # paragraph ends there (I&B p.29: the epigraph's '(Udāna, 80–81)' line
    # ends 200pt short, yet the commentary was joined on; same shape flattens
    # verse quotations line-by-line)
    col_w = geo.col_right - geo.col_left
    # recto/verso binding margins shift the whole text block sideways, so a
    # FULL line on a left-shifted page ends short of the GLOBAL modal right
    # edge (Sufism verso pp. at x0=54 vs modal 72 end ~18pt early). Scale the
    # right edge by this block's own left inset before the 'short' test, or
    # every justified line on a shifted page reads as a paragraph end.
    eff_right = geo.col_right - max(0.0, geo.col_left - min(prev.ln.x0, L.ln.x0))
    # a line inside a justified inset block (a block quote) is measured against
    # the block's OWN narrower right margin — its full lines end well short of
    # the body column but are NOT ragged paragraph ends (see _assign_block_right)
    ref_right = prev.block_right if prev.block_right is not None else eff_right
    # a line-end hyphen is an explicit continuation signal that trumps
    # geometry: ragged citations ('Maktaba al-' / 'Hilāl, 1988') end short
    # mid-entry, and breaking there strands 'al- Hilāl' seams (gate 9)
    prev_short = (prev.ln.x1 < ref_right - max(18.0, 0.06 * col_w)
                  and not prev.ln.text().rstrip().endswith(_CONT_DASHES))
    cross_page = L.page != prev.page
    if cross_page:
        # continuation across the page turn is the default; break only when
        # the previous page's last line visibly ENDED its paragraph, or a
        # genuine first-line indent follows a full-measure line. Comparing
        # the indent against the previous line's x0 alone wrongly split
        # quote blocks whose insets differ by a few points (I&B pp.16-17).
        if "/center" in L.ps:
            return True
        if prev_short:
            return True
        return indented and prev.ln.x1 >= eff_right - 6.0
    if indented and L.ps == body_ps and \
            (prev_short or prev.ps != body_ps
             or prev.ln.x0 <= geo.col_left + 2.0):
        # a first-line indent STARTS a paragraph when the previous line
        # ended visibly short, was a different block, or sat at the column
        # edge (a normal wrap line). A deeper x0 after a full line that was
        # ITSELF indented is a hanging-indent CONTINUATION (I&B's numbered
        # list items split at every '(4) …/knowledge,' turn without this)
        return True
    if prev_short and L.ln.x0 <= prev.ln.x0 + 2.0:
        # paragraph ended on a ragged line and the next starts at (or left
        # of) the same left edge: quote -> commentary seams, verse lines
        return True
    if (L.ln.y0 - prev.ln.y0) > cfg.gap_factor * med_lead:
        return True
    return False


_GUTTER_MIN_W = 6.0        # pt: narrower x-coverage gaps are word spaces
_GUTTER_COVER_FRAC = 0.06  # a gutter is crossed by (almost) no lines
_GUTTER_START_FRAC = 0.2   # …and hugged on its right by column-start runs


def _column_splits(pages: list, count: int, skip=None) -> list[float] | None:
    """Gutter split points for one flow.columns spec, from the RAW lines of
    ALL its pages: the column grid is a property of the columned SECTION —
    a single sparse page (BoK p.323, 15 index lines) leaves the whitespace
    channel between an entry and its right-aligned page numbers as the
    widest low-coverage strip, but aggregated over the section that channel
    fills in while the true gutters stay empty. Gutters are interior
    low-coverage strips hugged on their right by column-start runs (the
    start-density test rejects a column's ragged right edge; the interior
    test rejects the folio margin). None = not enough gutters found.

    ``skip(line) -> bool`` excludes lines from the coverage census — pass it
    the furniture predicate so a full-width running head (which spans BOTH
    columns and their gutter) does not fill the channel it is meant to
    reveal; column detection runs before the per-page furniture strip."""
    kept_lines = [ln for p in pages for ln in p.lines
                  if not (skip and skip(ln))]
    runs_all = [r for ln in kept_lines for r in ln.runs]
    n_lines = len(kept_lines)
    if not runs_all or count < 2:
        return None
    lo = int(min(r.x0 for r in runs_all))
    hi = int(max(r.x1 for r in runs_all)) + 1
    cover = [0] * (hi - lo + 1)
    for r in runs_all:
        for x in range(int(r.x0) - lo, int(r.x1) + 1 - lo):
            cover[x] += 1
    thresh = max(1, int(_GUTTER_COVER_FRAC * n_lines))
    min_starts = max(3, int(_GUTTER_START_FRAC * n_lines))
    gaps: list[tuple[float, int, int]] = []  # (width, a, b) in page coords
    a = None
    for x in range(len(cover) + 1):
        low = x < len(cover) and cover[x] <= thresh
        if low and a is None:
            a = x
        elif not low and a is not None:
            ga, gb = a + lo, x - 1 + lo
            n_starts = sum(1 for r in runs_all if gb - 1 <= r.x0 <= gb + 4)
            if gb - ga >= _GUTTER_MIN_W and ga > lo and n_starts >= min_starts:
                gaps.append((float(gb - ga), ga, gb))
            a = None
    if len(gaps) < count - 1:
        return None
    # split just left of the gutter's RIGHT edge: column starts hug it,
    # while the left boundary is fuzzy (ragged right ends of the previous
    # column reach variably far into the low-coverage strip)
    gaps.sort(reverse=True)
    return sorted(gb - 2.0 for _, ga, gb in gaps[:count - 1])


def _column_resplit(kept: list[_L], splits: list[float], doc: PdfDoc,
                    cfg: PdfBookConfig, geo: ColumnGeometry,
                    counts: Counter) -> list[_L]:
    """Re-order a flow.columns page into print reading order (NOTES: the
    extract-stage baseline merge fuses same-baseline runs ACROSS columns;
    runs keep their bboxes, so the flow re-splits at the column gutters).

    Fused lines split into per-column lines; whole lines land in the column
    holding their runs; a line with a run CROSSING a gutter (a centered
    heading) is a full-width spanner that flushes the columns read so far
    and starts a new band. Entry paragraphing is by indent: column-left =
    new entry, deeper = a hanging-indent turnover that joins (tabular back
    matter; columned prose stays out of scope). RAW line indexes are
    preserved on the split lines, so overrides/provenance address the
    fused source line."""
    count = len(splits) + 1

    def bucket(x: float) -> int:
        return sum(1 for s in splits if x > s)

    out: list[_L] = []
    band: list[list[_L]] = [[] for _ in range(count)]
    col_lines: list[list[_L]] = [[] for _ in range(count)]  # page-wide, for geometry

    def flush() -> None:
        for c in range(count):
            out.extend(band[c])
            band[c] = []

    for L in kept:
        if any(r.x0 <= s - 3 and r.x1 >= s + 3 for r in L.ln.runs for s in splits):
            flush()
            out.append(L)  # spanner: page-wide ps already computed
            counts["column-spanners"] += 1
            continue
        by_col: dict[int, list[PdfRun]] = {}
        for r in L.ln.runs:
            by_col.setdefault(bucket((r.x0 + r.x1) / 2), []).append(r)
        for c, rr in sorted(by_col.items()):
            ln2 = PdfLine(runs=rr, vertical=L.ln.vertical)
            ln2.x0 = min(r.x0 for r in rr)
            ln2.y0 = min(r.y0 for r in rr)
            ln2.x1 = max(r.x1 for r in rr)
            ln2.y1 = max(r.y1 for r in rr)
            L2 = _L(L.page, L.idx, ln2, L.ps, colno=c)
            band[c].append(L2)
            col_lines[c].append(L2)
    flush()

    # per-column geometry: pstyles and entry indents are column-relative
    for c in range(count):
        if not col_lines[c]:
            continue
        cgeo = ColumnGeometry(col_left=min(L.ln.x0 for L in col_lines[c]),
                              col_right=max(L.ln.x1 for L in col_lines[c]),
                              body_size=geo.body_size)
        for L in col_lines[c]:
            L.ps = line_pstyle(L.ln, doc, cgeo, None)
            L.entry_break = L.ln.x0 < cgeo.col_left + cfg.indent_threshold
    counts["column-pages"] += 1
    counts["column-lines"] += sum(len(cl) for cl in col_lines)
    return out


def _restore_cross_run_spaces(para: Paragraph, counts: Counter) -> None:
    """restore_spaces runs per run and cannot see a fusion at a run seam
    (roman/italic boundaries: 'believer.'+'This', MR prepress). Repair each
    adjacent-TextRun seam with the same patterns via restore_space_seam;
    the space lands in the earlier run so run formatting is preserved.
    The wrong-side-of-quote swap re-runs over each run's FINAL text: print
    puts the closing quote at the next line's start often enough that the
    'punct SPACE quote' shape only exists after the line join inserted its
    separator — per-line textfix ran too early to see it."""
    prev_run = None
    for it in para.items:
        if isinstance(it, TextRun):
            t, k = swap_quote_sides(it.text)
            if k:
                it.text = t
                counts["quote-side-swaps"] += k
            if it.text == "&" and prev_run is not None \
                    and prev_run.text[-1:].islower():
                # a display-type ampersand as its own run lost BOTH spaces
                # ('Me'+'&'+'Rumi', the 52pt title); single-char runs defeat
                # the window-based seam patterns
                it.text = " & "
                counts["spaces-restored-crossrun"] += 2
            if prev_run is not None:
                a, b, n = restore_space_seam(prev_run.text, it.text)
                if n:
                    prev_run.text, it.text = a, b
                    counts["spaces-restored-crossrun"] += n
            prev_run = it
        elif isinstance(it, InlinePageBreak):
            continue  # transparent: an anchor is not a text boundary
        else:
            prev_run = None


def _collapse_cross_run_spaces(para: Paragraph) -> None:
    """'he ' + ' (may…' (glyph substitutions after space-trailing extraction
    runs) must not render as a double space."""
    prev_run = None
    for it in para.items:
        if isinstance(it, TextRun):
            if prev_run is not None and \
                    prev_run.text.endswith((" ", "\xa0")) and \
                    it.text.startswith(" "):
                prev_run.text = prev_run.text.rstrip(" \xa0")
            # in-run double spaces from the same collision
            if "  " in it.text or "\xa0 " in it.text:
                it.text = re.sub(r"[ \xa0]{2,}", " ", it.text)
            prev_run = it
        elif isinstance(it, InlinePageBreak):
            continue  # transparent: an anchor is not a text boundary
        else:
            prev_run = None


def _mk_runs(ln: PdfLine, cfg: PdfBookConfig, doc: PdfDoc) -> list[TextRun]:
    out: list[TextRun] = []
    for r in ln.runs:
        f = doc.fonts.get(r.font_id)
        fam = f.family if f else None
        flags = cfg.charstyles.get(fam or "", None)
        fmt = RunFormat(
            italic=r.italic,
            bold=r.bold,
            position="superscript" if r.superscript else "normal",
            smallcaps=bool(flags and flags.smallcaps),
            point_size=f.size if f else None,
            applied_font=fam,
        )
        prev = out[-1] if out else None
        if prev is not None and prev.fmt.key() == fmt.key():
            prev.text += r.text
        else:
            out.append(TextRun(r.text, fmt))
    # cross-run hyphen seams INSIDE one extracted line: an italic run ending
    # 'particu-' with the roman continuation ' lar' following (I&B stores
    # whole paragraphs as single content lines). Same lower-only doctrine.
    for a, b in zip(out, out[1:]):
        base = a.text.rstrip()
        nxt = b.text.lstrip()
        if base.endswith("-") and len(base) > 1 and base[-2].isalpha() \
                and nxt[:1].islower():
            a.text = base[:-1]
            b.text = nxt
    return out


def _append_line(para: Paragraph, L: _L, cfg: PdfBookConfig, doc: PdfDoc,
                 counts: Counter, glue: bool = False,
                 verse: bool = False) -> None:
    runs = _mk_runs(L.ln, cfg, doc)
    runs = _apply_textfix(runs, cfg, counts, L.page)
    if para.items and isinstance(para.items[-1], TextRun):
        prevrun = para.items[-1]
        if glue:
            sep = ""  # dropcap letter glues straight onto its continuation
        elif verse:
            # verse line seam: the printed line break IS content — join with
            # U+2028 LINE SEPARATOR (emitted as <br/>), never dehyphenate
            # (a verse line-end hyphen/dash is the poet's punctuation)
            sep = "\u2028"
        else:
            nxt = next((r.text for r in runs
                        if isinstance(r, TextRun) and r.text.strip()), "")
            prevrun_text, sep, dehy = dehyphenate_join(
                prevrun.text, nxt, cfg.dehyphenate)
            if dehy:
                counts["dehyphenated"] += 1
            prevrun.text = prevrun_text
        if sep:
            prevrun.text += sep
    para.items.extend(runs)


def _apply_textfix(runs: list[TextRun], cfg: PdfBookConfig,
                   counts: Counter, page: int = 0) -> list[TextRun]:
    from .textfix import is_shifted_run, repair_shifted_cmap, strip_control_chars

    out: list[TextRun] = []
    for run in runs:
        t = run.text
        if cfg.shifted_cmap_repair and is_shifted_run(t, cfg.shifted_cmap_highmap):
            t, unk = repair_shifted_cmap(t, cfg.shifted_cmap_highmap)
            counts["cmap-repaired-runs"] += 1
            counts["cmap-unknown-chars"] += unk
        t, n_ctrl = strip_control_chars(t)
        counts["ctrl-stripped"] += n_ctrl
        if "�" in t:
            # U+FFFD = extractor's unmapped-glyph placeholder; replaceable
            # only page-scoped with render evidence (glyphs.fffd_repairs).
            # Unconfigured occurrences are kept and warned — never silently
            # dropped; gate 20 polices the shipped artifact.
            n_f = t.count("�")
            for i, fd in enumerate(cfg.fffd_repairs):
                if page in fd.pages:
                    t = t.replace("�", fd.replace)
                    counts["fffd-replaced"] += n_f
                    counts[f"_fffd-used-{i}"] += 1
                    break
            else:
                counts["fffd-unrepaired"] += n_f
        # MuPDF span text can carry raw newlines (soft line breaks inside a
        # content line, I&B) — fold them to spaces before seam repairs
        if "\n" in t:
            t = re.sub(r"\s*\n\s*", " ", t)
        # discretionary soft hyphens (U+00AD): invisible on screen but stray in
        # the shipped text and, at a line end, misread as a paragraph-ending
        # short line. Strip a MID-run one ('distin­guish'), collapse a
        # soft-hyphen+space seam ('con­ tains' -> 'contains'); a TRAILING one is
        # left for dehyphenate_join to close the cross-line join.
        if "­" in t:
            before = t.count("­")
            t = re.sub(r"­(?=\S)", "", t)
            t = re.sub(r"­ +", "", t)
            counts["softhyphen-stripped"] += before - t.count("­")
        t, n_lig = expand_ligatures(t)
        counts["ligatures"] += n_lig
        from .textfix import inline_dehyphenate
        t, n_inl = inline_dehyphenate(t)
        counts["inline-dehyphenated"] += n_inl
        if cfg.restore_spaces:
            t, n_sp = restore_spaces(t)
            counts["spaces-restored"] += n_sp
        # PUA substitution, splitting the run when a mapped char carries lang
        if _PUA_RE.search(t):
            segs: list[tuple[str, str | None]] = []  # (text, lang|None)
            buf = ""
            for ch in t:
                rule = cfg.pua_map.get(ch)
                if rule is None:
                    if _PUA_RE.match(ch):
                        counts["pua-unmapped"] += 1
                        buf += ch  # kept: the gate/warning reports it
                    else:
                        buf += ch
                elif rule.action == "drop":
                    counts["pua-dropped"] += 1
                elif rule.lang:
                    if rule.char and rule.char.startswith(" "):
                        buf = buf.rstrip(" \xa0")  # 'he\xa0' + ' (may…' = one space
                    if buf:
                        segs.append((buf, None))
                        buf = ""
                    segs.append((rule.char or "", rule.lang))
                    counts["pua-substituted"] += 1
                else:
                    if rule.char and rule.char.startswith(" "):
                        buf = buf.rstrip(" \xa0")
                    buf += rule.char or ""
                    counts["pua-substituted"] += 1
            if buf:
                segs.append((buf, None))
            for text, lang in segs:
                if not text:
                    continue
                fmt = RunFormat(**{k: getattr(run.fmt, k) for k in
                                   ("italic", "bold", "position", "smallcaps",
                                    "point_size", "applied_font", "char_style")})
                fmt.lang = lang
                out.append(TextRun(text, fmt))
            continue
        run.text = t
        out.append(run)
    return out


def counts_pua_unmapped(flow: FlowDoc, cfg: PdfBookConfig) -> dict[str, int]:
    found: Counter[str] = Counter()

    def eat(p: Paragraph):
        for it in p.items:
            if isinstance(it, TextRun):
                for ch in _PUA_RE.findall(it.text):
                    if ch not in cfg.pua_map:
                        found[ch] += 1

    for b in flow.blocks:
        if isinstance(b, Paragraph):
            eat(b)
    for note in flow.notes.values():
        for p in note.paragraphs:
            eat(p)
    return dict(found)


def _note_paragraphs(group: list[_L], cfg: PdfBookConfig, doc: PdfDoc,
                     note_id: str, counts: Counter) -> list[Paragraph]:
    para = Paragraph(style="__note__", items=[],
                     src=SourceRef(f"p{group[0].page:04d}", group[0].idx),
                     role="footnote")
    first = True
    for L in group:
        runs = _mk_runs(L.ln, cfg, doc)
        runs = _apply_textfix(runs, cfg, counts, L.page)
        if first:
            # strip the printed marker (the emitter numbers the endnote list).
            # Match it by VALUE, not the _NOTE_START_DIGIT text pattern: the
            # marker is a smaller-font/superscript run set 'N ' with a single
            # space (often its OWN run), which that pattern misses — leaving a
            # stray '1' before the auto-numbered <li>.
            marker = _note_marker(group[0], cfg.footnote_marker)
            if marker and runs and isinstance(runs[0], TextRun):
                runs[0].text = re.sub(
                    r"^\s*" + re.escape(marker) + r"[.)]?\s*", "",
                    runs[0].text, count=1)
            # the marker may have been its own run ('1' | '. body'): drop any
            # now-empty leading runs and trim the space AND a split delimiter
            # ('.'/')') the marker's own-run left on the note's first word
            for r in runs:
                if isinstance(r, TextRun) and r.text.strip():
                    r.text = re.sub(r"^\s*[.)]?\s*", "", r.text, count=1)
                    break
                if isinstance(r, TextRun):
                    r.text = ""
            first = False
        if para.items and isinstance(para.items[-1], TextRun) and runs:
            nxt = next((r.text for r in runs
                        if isinstance(r, TextRun) and r.text.strip()), "")
            new_text, sep, _ = dehyphenate_join(para.items[-1].text, nxt,
                                                cfg.dehyphenate)
            para.items[-1].text = new_text + sep
        para.items.extend(runs)
    if cfg.restore_spaces:
        _restore_cross_run_spaces(para, counts)
    _collapse_cross_run_spaces(para)
    return [para]


def _attach_noterefs(flow: FlowDoc, queue: list[tuple[int, str, str]],
                     para_last_page: dict[tuple[str, int], int],
                     body_size: float, counts: Counter) -> list[tuple[int, str, str]]:
    """Replace in-body marker runs with NoteRefs, walking paragraphs in flow
    order against the page-ordered note queue. Markers: superscript-flagged
    runs, or small digit/star runs (old PDFs carry no flags — I&B). A note
    whose marker can't be found still gets a ref at the end of its page's
    last paragraph — notes are never silently lost."""
    remaining = list(queue)
    unmatched: list[tuple[int, str, str]] = []
    last_para_for_page: dict[int, Paragraph] = {}

    for b in flow.blocks:
        if not isinstance(b, Paragraph) or b.role == "toc-entry" or \
                b.style == "__toc__":
            continue
        p0 = int(b.src.story_id[1:]) if b.src.story_id.startswith("p") else 0
        p1 = para_last_page.get((b.src.story_id, b.src.psr_index), p0)
        for pg in range(p0, p1 + 1):
            last_para_for_page[pg] = b
        # overdue heads must not block the queue (their marker was missed)
        while remaining and remaining[0][0] < p0 - 1:
            unmatched.append(remaining.pop(0))
        i = 0
        while i < len(b.items):
            if not remaining:
                break
            it = b.items[i]
            head_page, target, note_id = remaining[0]
            if head_page > p1 + 1:
                break  # this paragraph ends before the note's page
            if isinstance(it, TextRun):
                t = it.text.strip()
                small = (it.fmt.point_size or body_size) <= 0.85 * body_size
                sup = it.fmt.position == "superscript"
                if (sup or small) and t and (
                        t == target or (target == "*" and t in ("*", "†", "‡"))):
                    # the line-join separator is parked on the PREVIOUS run's
                    # text (_append_line), i.e. often on this marker run —
                    # replacing it with a NoteRef must not swallow the space
                    # ('word.⁵ Next' shipped as 'word.⁵Next' book-wide)
                    lead = it.text[:len(it.text) - len(it.text.lstrip())]
                    trail = it.text[len(it.text.rstrip()):]
                    b.items[i] = NoteRef(note_id)
                    if trail:
                        b.items.insert(i + 1, TextRun(" "))
                    if lead:
                        b.items.insert(i, TextRun(" "))
                        i += 1
                    remaining.pop(0)
                    counts["noterefs"] += 1
            i += 1

    for head_page, target, note_id in remaining:
        para = last_para_for_page.get(head_page)
        if para is None:
            cand = [pg for pg in last_para_for_page if pg <= head_page]
            para = last_para_for_page[max(cand)] if cand else None
        if para is not None:
            para.items.append(NoteRef(note_id))
            counts["noterefs-fallback"] += 1
        unmatched.append((head_page, target, note_id))
    return unmatched


def _page_labels(doc: PdfDoc, cfg: PdfBookConfig,
                 warns: list[_Warn]) -> dict[int, str]:
    labels: dict[int, str] = {}
    if cfg.label_source == "pdf-page-labels":
        for p in doc.pages:
            labels[p.number] = p.label or str(p.number)
    elif cfg.label_source == "printed-folios":
        # printed folio where present; arithmetic continuation elsewhere,
        # and BACKFILL before the first printed folio (front-matter pages
        # rarely print theirs — falling back to physical numbers created
        # duplicate labels and roman-after-arabic breaks on I&B)
        last_num: int | None = None
        last_roman = False
        pending: list[int] = []
        for p in doc.pages:
            pf = _printed_folio(p)
            if pf and pf.isdigit():
                last_num, last_roman = int(pf), False
                labels[p.number] = pf
            elif pf:
                try:
                    last_num = _roman_to_int(pf)
                    last_roman = True
                    labels[p.number] = pf.lower()
                except ValueError:
                    labels[p.number] = pf
            elif last_num is not None:
                last_num += 1
                labels[p.number] = (int_to_roman(last_num) if last_roman
                                    else str(last_num))
            else:
                pending.append(p.number)
                continue
            if pending:
                # first folio just seen: walk backwards from it
                base = last_num - 1
                for pn in reversed(pending):
                    if base >= 1:
                        labels[pn] = int_to_roman(base) if last_roman else str(base)
                        base -= 1
                    else:
                        labels[pn] = str(pn)
                pending.clear()
        for pn in pending:
            labels[pn] = str(pn)
    else:  # synthetic
        for p in doc.pages:
            labels[p.number] = str(p.number)
    for pno, lab in cfg.label_overrides.items():
        labels[pno] = lab
    return labels


_ROMAN_VALS = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman_to_int(s: str) -> int:
    s = s.lower()
    if not s or any(c not in _ROMAN_VALS for c in s):
        raise ValueError(s)
    total = 0
    for a, b in zip(s, s[1:] + "\0"):
        v = _ROMAN_VALS[a]
        total += -v if b != "\0" and _ROMAN_VALS.get(b, 0) > v else v
    return total
