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
from .config import PdfBookConfig
from .core.model import (
    Figure,
    FlowDoc,
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
from .textfix import dehyphenate_join, expand_ligatures, restore_spaces

_PUA_RE = re.compile(r"[\ue000-\uf8ff]")
# note bodies start '9. text' (I&B), '9) text', or '1<TAB>text' (BoK)
_NOTE_START_DIGIT = re.compile(r"^\s*(\d{1,3})(?:[.)]\s+|\t+| {2,})")
_NOTE_START_STAR = re.compile(r"^\s*([*†‡])\s*")


@dataclass(slots=True)
class _Warn:
    msg: str
    page: int = 0
    line: int = -1
    snippet: str = ""  # ready-to-paste book.yaml override


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


@dataclass(slots=True)
class _L:
    page: int
    idx: int  # RAW extract line index within the page
    ln: PdfLine
    ps: str


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

    # ---- per-page: strip furniture, split footnotes, collect body lines
    pages_lines: dict[int, list[_L]] = {}
    page_notes: dict[int, list[list[_L]]] = {}  # page -> list of note line-groups
    prev_had_notes = False
    for p in in_flow:
        kept: list[_L] = []
        for idx, ln in enumerate(p.lines):
            act = override(p.number, idx)
            if act == "drop":
                counts["override-drop"] += 1
                continue
            L = _L(p.number, idx, ln, line_pstyle(ln, doc, geo))
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
                if is_folio_line(t_norm):
                    counts["furniture-folio"] += 1
                    continue
                if tpl in fur:
                    counts["furniture-head"] += 1
                    continue
                if (head_base is not None and abs(ln.y0 - head_base) <= 3
                        and re.search(r"^#|#$", tpl)):
                    counts["furniture-baseline"] += 1
                    continue
                if near_top and top_band and ln.y0 <= p.trim[1] + top_band:
                    warns.append(_Warn(
                        f"p.{p.number} line {idx}: unrecognized top-band line kept: "
                        f"{ln.text()[:60]!r}", p.number, idx,
                        f"{{page: {p.number}, line: {idx}, action: drop, note: FILL}}"))
            kept.append(L)

        # footnote region split (bottom small-font block)
        notes_here: list[list[_L]] = []
        if cfg.footnote_policy == "markers" and kept:
            max_sz = cfg.footnote_region_max_size or (body_size - 1.5)
            region: list[_L] = []
            for L in reversed(kept):
                f = doc.fonts.get(L.ln.dominant_font())
                if f and f.size <= max_sz and not L.ln.vertical:
                    region.append(L)
                else:
                    break
            region.reverse()
            if region and len(" ".join(x.ln.text() for x in region)) > 20:
                pat = _NOTE_START_DIGIT if cfg.footnote_marker == "digits" else _NOTE_START_STAR
                # small font is NOT sufficient — 9pt block quotes sit at page
                # bottoms too (BoK p.186). The note region starts at the FIRST
                # marker-pattern line; small-font lines above it stay body.
                # A region with no marker at all is body — unless it
                # continues the previous page's notes (merge pass below).
                first_marked = next((i for i, L in enumerate(region)
                                     if pat.match(L.ln.text())), None)
                prev_page_had_notes = prev_had_notes
                if first_marked is None and not prev_page_had_notes:
                    region = []
                elif first_marked and first_marked > 0 and not prev_page_had_notes:
                    region = region[first_marked:]
                if region:
                    kept = kept[:len(kept) - len(region)]
                    cur: list[_L] = []
                    for L in region:
                        if pat.match(L.ln.text()) and cur:
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
        pat = _NOTE_START_DIGIT if cfg.footnote_marker == "digits" else _NOTE_START_STAR
        prev_last_group: list[_L] | None = None
        for pno in sorted(page_notes):
            groups = page_notes[pno]
            if groups and prev_last_group is not None and \
                    not pat.match(groups[0][0].ln.text()):
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
            for L in pages_lines.get(pno, []):
                ent = _trailing_folio_entry(L.ln)
                if ent:
                    title, label = ent
                    fixed = _apply_textfix([TextRun(f"{title}\t{label}", RunFormat())],
                                           cfg, counts)
                    text = "".join(r.text for r in fixed if isinstance(r, TextRun))
                    last_entry = Paragraph(
                        style="__toc__",
                        items=[TextRun(text, RunFormat())],
                        src=SourceRef(f"p{L.page:04d}", L.idx))
                    paras.append(last_entry)
                elif L.ps != body_ps and "center" in L.ps:
                    paras.append(Paragraph(
                        style=L.ps,
                        items=_apply_textfix(_mk_runs(L.ln, cfg, doc), cfg, counts),
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
                        f"{L.ln.text()[:50]!r}", pno, L.idx))
                    paras.append(Paragraph(
                        style=L.ps,
                        items=_apply_textfix(_mk_runs(L.ln, cfg, doc), cfg, counts),
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

    # ---- join pass, page by page, with cross-page continuation
    open_para: Paragraph | None = None
    open_is_body = False
    prev_L: _L | None = None
    pending_anchors: list[PageAnchor] = []
    para_last_page: dict[tuple[str, int], int] = {}
    note_queue: list[tuple[int, str, str]] = []  # (page, marker target, note_id)

    def close_para():
        nonlocal open_para, open_is_body
        if open_para is not None and open_para.text().strip():
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
            continue

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

        anchor_placed = False
        prev_dropcap = False
        for L in lines:
            act = override(L.page, L.idx)
            # drop-cap: oversized 1-2 letter line glues onto the next line
            f = doc.fonts.get(L.ln.dominant_font())
            is_dropcap = (cfg.reattach_dropcaps and f is not None
                          and f.size >= 2 * body_size
                          and 1 <= len(L.ln.text().strip()) <= 2
                          and L.ln.text().strip().isalpha())

            if prev_dropcap and act != "break":
                brk = False  # the letter's own paragraph continues here
            else:
                brk = _break_before(L, prev_L, act, body_ps, cfg, geo, med_lead,
                                    open_is_body, pno)
            if is_dropcap:
                brk = True
            if brk:
                close_para()
                open_para = Paragraph(style=L.ps, items=[],
                                      src=SourceRef(f"p{L.page:04d}", L.idx))
                open_is_body = (L.ps == body_ps)
                if is_dropcap:
                    open_para.classes = ["first-dropcap"]
                    open_para.style = body_ps  # dropcap letter belongs to body text
                    open_is_body = True
                    res.dropcap_srcs.add((open_para.src.story_id,
                                          open_para.src.psr_index))
                    counts["dropcaps"] += 1
            if not anchor_placed:
                # anchor sits before the first block that STARTS on this page;
                # a paragraph continuing from the previous page keeps the
                # anchor just before its continuation point is not possible in
                # a linear flow, so it lands before the NEXT new block (the
                # idml2epub paragraph-granularity convention)
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
            if open_para is None:
                open_para = Paragraph(style=L.ps, items=[],
                                      src=SourceRef(f"p{L.page:04d}", L.idx))
                open_is_body = (L.ps == body_ps)
            _append_line(open_para, L, cfg, doc, counts, glue=prev_dropcap)
            para_last_page[(open_para.src.story_id, open_para.src.psr_index)] = L.page
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
            note_paras = _note_paragraphs(group, cfg, doc, note_id)
            res.flow.notes[note_id] = Note(note_id=note_id, paragraphs=note_paras)
            m = _NOTE_START_DIGIT.match(group[0].ln.text())
            marker = m.group(1) if m else "*"
            note_queue.append((pno, marker, note_id))
            res.note_markers[note_id] = marker

    close_para()
    for a2 in pending_anchors:
        res.flow.blocks.append(a2)

    # ---- attach note markers (global pass: a marker can sit in a paragraph
    # that STARTED on the previous page)
    if note_queue:
        unmatched = _attach_noterefs(res.flow, note_queue, para_last_page,
                                     body_size, counts)
        for pno, target, note_id in unmatched:
            warns.append(_Warn(
                f"p.{pno}: no in-body marker found for note {note_id} "
                f"(expected {target!r}); ref attached at the end of the page's "
                "last paragraph", pno, -1))

    # ---- stale overrides are config bugs
    stale = set(ov) - consumed
    if stale:
        raise SystemExit("stale flow.overrides (matched nothing): " +
                         ", ".join(f"page {p} line {i}" for p, i in sorted(stale)))

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
        warns.append(_Warn(f"unmapped private-use glyphs: {listing}"))

    res.counts = dict(counts)
    for w in warns:
        res.flow.warnings.append(w.msg)
    return res


# ------------------------------------------------------------------ helpers

def _break_before(L: _L, prev: _L | None, act: str | None, body_ps: str,
                  cfg: PdfBookConfig, geo: ColumnGeometry, med_lead: float,
                  open_is_body: bool, pno: int) -> bool:
    if act == "break":
        return True
    if act == "join":
        return False
    if prev is None:
        return True
    if L.ps != prev.ps:
        # stacked centered lines of one pstyle continue (multi-line headings)
        return True
    if "/center" in L.ps:
        return not cfg.join_center_lines
    # a first-line indent is indented relative to the PREVIOUS line too —
    # drop-cap wrap lines all sit at the same inset (BoK p.35: 3 lines at
    # x0=87.9 around a 52.5pt initial) and must not break line-by-line
    indented = (L.ln.x0 - geo.col_left >= cfg.indent_threshold
                and L.ln.x0 - prev.ln.x0 >= cfg.indent_threshold - 2)
    cross_page = L.page != prev.page
    if cross_page:
        # any same-pstyle uncentered text continues across the page turn —
        # restricting this to the body pstyle force-broke 10pt front matter
        # and block quotes mid-word ('com-' | 'munity', BoK acknowledgments)
        if "/center" in L.ps:
            return True
        return indented
    if indented and L.ps == body_ps:
        return True
    if (L.ln.y0 - prev.ln.y0) > cfg.gap_factor * med_lead:
        return True
    return False


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
    return out


def _append_line(para: Paragraph, L: _L, cfg: PdfBookConfig, doc: PdfDoc,
                 counts: Counter, glue: bool = False) -> None:
    runs = _mk_runs(L.ln, cfg, doc)
    runs = _apply_textfix(runs, cfg, counts)
    if para.items and isinstance(para.items[-1], TextRun):
        prevrun = para.items[-1]
        if glue:
            sep = ""  # dropcap letter glues straight onto its continuation
        else:
            prevrun_text, sep, dehy = dehyphenate_join(
                prevrun.text, runs[0].text if runs else "", cfg.dehyphenate)
            if dehy:
                counts["dehyphenated"] += 1
            prevrun.text = prevrun_text
        if sep:
            prevrun.text += sep
    para.items.extend(runs)


def _apply_textfix(runs: list[TextRun], cfg: PdfBookConfig,
                   counts: Counter) -> list[TextRun]:
    out: list[TextRun] = []
    for run in runs:
        t, n_lig = expand_ligatures(run.text)
        counts["ligatures"] += n_lig
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
                    if buf:
                        segs.append((buf, None))
                        buf = ""
                    segs.append((rule.char or "", rule.lang))
                    counts["pua-substituted"] += 1
                else:
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
                     note_id: str) -> list[Paragraph]:
    para = Paragraph(style="__note__", items=[],
                     src=SourceRef(f"p{group[0].page:04d}", group[0].idx),
                     role="footnote")
    counts: Counter = Counter()
    first = True
    for L in group:
        runs = _mk_runs(L.ln, cfg, doc)
        runs = _apply_textfix(runs, cfg, counts)
        if first:
            # strip the printed marker; the emitter numbers the endnote list
            if runs and isinstance(runs[0], TextRun):
                pat = _NOTE_START_DIGIT if cfg.footnote_marker == "digits" else _NOTE_START_STAR
                runs[0].text = pat.sub("", runs[0].text, count=1)
            first = False
        if para.items and isinstance(para.items[-1], TextRun) and runs:
            new_text, sep, _ = dehyphenate_join(para.items[-1].text, runs[0].text,
                                                cfg.dehyphenate)
            para.items[-1].text = new_text + sep
        para.items.extend(runs)
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
                    b.items[i] = NoteRef(note_id)
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
        # printed folio where present; arithmetic continuation elsewhere
        last_num: int | None = None
        last_roman = False
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
                labels[p.number] = str(p.number)
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
