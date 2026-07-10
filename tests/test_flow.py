"""Flow builder over a synthetic PdfDoc: joins, dropcaps, notes, overrides."""

import pytest

from pdf2epub.config import PdfBookConfig, FlowOverride
from pdf2epub.core.model import NoteRef, Paragraph, PageAnchor, TextRun
from pdf2epub.flowbuilder import build_flow
from pdf2epub.pdfmodel import PdfDoc, PdfFont, PdfLine, PdfPage, PdfRun
from pdf2epub.textfix import dehyphenate_join, expand_ligatures, restore_spaces

BODY = 0
SMALL = 1
BIG = 2
SUP = 3

FONTS = {
    BODY: PdfFont(BODY, "Serif", "AAAAAA+Serif", 11.0, "#000000"),
    SMALL: PdfFont(SMALL, "Serif", "AAAAAA+Serif", 9.0, "#000000"),
    BIG: PdfFont(BIG, "Serif", "AAAAAA+Serif", 30.0, "#000000"),
    SUP: PdfFont(SUP, "Serif", "AAAAAA+Serif", 6.5, "#000000"),
}


def _line(text, y, x0=72.0, font=BODY, width=290.0, sup=False):
    x1 = x0 + width
    return PdfLine(runs=[PdfRun(text=text, font_id=font, superscript=sup,
                                x0=x0, y0=y, x1=x1, y1=y + 12)],
                   x0=x0, y0=y, x1=x1, y1=y + 12)


def _page(number, lines, height=648.0):
    return PdfPage(number=number, label=str(number), width=431.0, height=height,
                   trim=(0.0, 0.0, 431.0, height), lines=lines,
                   n_chars=sum(len(l.text()) for l in lines))


def _doc(pages):
    return PdfDoc(pdf_path="x.pdf", sha256="s", producer="t", n_pages=len(pages),
                  pages=pages, fonts=dict(FONTS))


def _cfg(tmp_path, **kw):
    cfg = PdfBookConfig(path=tmp_path / "book.yaml")
    cfg.pdf = "x.pdf"
    cfg.body_pstyle = "Serif@11"
    cfg.indent_threshold = 9.0
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def _paras(flow):
    return [b for b in flow.blocks if isinstance(b, Paragraph)]


def test_join_and_indent_break(tmp_path):
    # long full lines join; the indented line starts a new paragraph
    pages = [_page(1, [
        _line("First paragraph line one", 100),
        _line("continues here.", 113.5),
        _line("Second paragraph starts indented", 127, x0=90.0),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    paras = _paras(res.flow)
    assert len(paras) == 2
    assert paras[0].text() == "First paragraph line one continues here."
    assert paras[1].text().startswith("Second paragraph")


def test_dehyphenation_cases(tmp_path):
    pages = [_page(1, [
        _line("the rational tradi-", 100),
        _line("tion continues; see Kaccayanagotta-", 113.5),
        _line("Sutta for details.", 127),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    text = _paras(res.flow)[0].text()
    assert "tradition continues" in text          # lowercase -> hyphen dropped
    assert "Kaccayanagotta-Sutta" in text         # capital -> hyphen kept


def test_dropcap_reattaches_and_flags(tmp_path):
    pages = [_page(1, [
        _line("A", 100, font=BIG, width=20.0),
        _line("lmost a thousand years ago the story", 104, x0=95.0),
        _line("continues on a plain line.", 117),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    paras = _paras(res.flow)
    assert paras[0].text().startswith("Almost a thousand")
    assert ("p0001", 0) in res.dropcap_srcs


def test_footnote_split_and_marker_pairing(tmp_path):
    body = [
        _line("Body text with a marker", 100),
        PdfLine(runs=[PdfRun(text="Body text second line", font_id=BODY,
                             x0=72, y0=113.5, x1=290, y1=125),
                      PdfRun(text="7", font_id=SUP, superscript=True,
                             x0=291, y0=112, x1=296, y1=120)],
                x0=72, y0=113.5, x1=296, y1=125),
        _line("7. The footnote body text here", 600, font=SMALL),
    ]
    pages = [_page(1, body)]
    cfg = _cfg(tmp_path, footnote_policy="markers", footnote_marker="digits")
    res = build_flow(_doc(pages), cfg, say=lambda m: None)
    assert len(res.flow.notes) == 1
    note = list(res.flow.notes.values())[0]
    assert note.paragraphs[0].text().startswith("The footnote body")  # marker stripped
    refs = [it for p in _paras(res.flow) for it in p.items if isinstance(it, NoteRef)]
    assert len(refs) == 1 and refs[0].note_id == note.note_id


def test_flow_overrides_break_and_stale(tmp_path):
    pages = [_page(1, [
        _line("Line one flows", 100),
        _line("line two would continue.", 113.5),
    ])]
    cfg = _cfg(tmp_path, flow_overrides=[FlowOverride(page=1, line=1, action="break")])
    res = build_flow(_doc(pages), cfg, say=lambda m: None)
    assert len(_paras(res.flow)) == 2
    cfg2 = _cfg(tmp_path, flow_overrides=[FlowOverride(page=9, line=9, action="drop")])
    with pytest.raises(SystemExit, match="stale flow.overrides"):
        build_flow(_doc(pages), cfg2, say=lambda m: None)


def test_figure_page_keep_text(tmp_path):
    from pdf2epub.config import FigurePages
    from pdf2epub.core.model import Figure

    pages = [_page(1, [
        _line("Foreword", 70, x0=180.0, width=80.0, font=BIG),
        _line("by His Holiness", 90, x0=160.0, width=120.0),
    ])]
    fp = FigurePages(pages=[1], alt_template="Facsimile letter", keep_text=True)
    res = build_flow(_doc(pages), _cfg(tmp_path, figure_pages=[fp]),
                     say=lambda m: None)
    kinds = [type(b).__name__ for b in res.flow.blocks]
    assert kinds[0] == "PageAnchor" and kinds[1] == "Figure"
    assert sum(1 for k in kinds if k == "PageAnchor") == 1   # no double anchor
    figs = [b for b in res.flow.blocks if isinstance(b, Figure)]
    assert figs[0].alt == "Facsimile letter"
    texts = [b.text() for b in _paras(res.flow)]
    assert any("Foreword" in t for t in texts)               # text still flows
    # without keep_text the page's text does NOT flow (unchanged behavior)
    fp2 = FigurePages(pages=[1], alt_template="x")
    res2 = build_flow(_doc(pages), _cfg(tmp_path, figure_pages=[fp2]),
                      say=lambda m: None)
    assert not _paras(res2.flow)


def test_anchor_per_page_monotone(tmp_path):
    from pdf2epub.qa.visual import _flow_anchors

    # page 2's line continues page 1's paragraph across the turn, so its
    # anchor is inline; block+inline anchors together stay one-per-page
    # and monotone
    pages = [_page(1, [_line("Page one text content here", 100)]),
             _page(2, [_line("Page two text content here", 100)])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    assert [a.ordinal for a in _flow_anchors(res.flow)] == [1, 2]
    block_anchors = [b for b in res.flow.blocks if isinstance(b, PageAnchor)]
    assert [a.ordinal for a in block_anchors] == [1]
    # a page that genuinely starts a new paragraph keeps a block anchor
    pages = [_page(1, [_line("the paragraph ends short here.", 520, x0=72.0,
                             width=140.0)]),
             _page(2, [_line("A new paragraph opens the next page at margin",
                             72, x0=72.0, width=290.0)])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    block_anchors = [b for b in res.flow.blocks if isinstance(b, PageAnchor)]
    assert [a.ordinal for a in block_anchors] == [1, 2]


def test_para_lines_provenance(tmp_path):
    # every kept line of a joined paragraph lands in res.para_lines under the
    # paragraph's src key, in order — including cross-page continuations
    pages = [_page(1, [
        _line("First paragraph line one", 100),
        _line("continues here and then", 113.5),
        _line("spills toward the page end", 127),
    ]), _page(2, [
        _line("finishing on the next page.", 100),
        _line("Second paragraph starts indented", 113.5, x0=90.0),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    paras = _paras(res.flow)
    assert len(paras) == 2
    key0 = (paras[0].src.story_id, paras[0].src.psr_index)
    key1 = (paras[1].src.story_id, paras[1].src.psr_index)
    assert res.para_lines[key0] == [(1, 0), (1, 1), (1, 2), (2, 0)]
    assert res.para_lines[key1] == [(2, 1)]
    # every flow paragraph has provenance
    assert {(p.src.story_id, p.src.psr_index) for p in paras} <= set(res.para_lines)


def test_short_line_ends_paragraph(tmp_path):
    # I&B p.29 shape: an inset quote's last line ends far short of the right
    # margin; the commentary that follows (outdented to the column left)
    # must start a NEW paragraph even though pstyle and leading match
    pages = [_page(1, [
        _line("quotation line running to the right margin here", 100, x0=90.0,
              width=272.0),
        _line("(Udana, 80-81)", 113.5, x0=90.0, width=70.0),
        _line("The juxtaposition of these two scriptural citations", 127,
              x0=72.0, width=290.0),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    paras = _paras(res.flow)
    assert len(paras) == 2
    assert paras[1].text().startswith("The juxtaposition")
    # verse lines: each ends short at the SAME x0 -> line-by-line paragraphs
    # (full-width body lines establish the real column edges)
    pages = [_page(1, [
        _line("body context establishing the column geometry width", 74),
        _line("more body context running to the right margin here", 87),
        _line("Since sentient beings are thus,", 100, x0=90.0, width=136.0),
        _line("So also are the Buddhas:", 113.5, x0=90.0, width=112.0),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    assert len(_paras(res.flow)) == 3
    # a justified paragraph's full-width lines still join
    pages = [_page(1, [
        _line("a full width line of an ordinary body paragraph he", 100),
        _line("continues here to the right margin and keeps going", 113.5),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    assert len(_paras(res.flow)) == 1


def test_inset_block_quote_joins_by_own_margin(tmp_path):
    # I&B Qurʾān-quote shape: an inset block quote (x0=90) is indented on BOTH
    # sides, so its justified lines end ~18pt short of the BODY column edge and
    # each read as a ragged paragraph end under a body-column short test. The
    # block's OWN right margin (the tight x1 cluster its full lines reach) makes
    # them full again, so the quote flows as ONE paragraph instead of shattering
    # line by line. Contrast test_short_line_ends_paragraph's verse block, whose
    # scattered widths yield no cluster and stay broken.
    pages = [_page(1, [
        _line("body context establishing the column geometry width", 74),
        _line("more body context running to the right margin here", 87),
        _line("Whoso migrates for the sake of God will find refuge", 113.5,
              x0=90.0, width=253.0),   # x1=343, ~19pt short of the 362 body edge
        _line("and abundance in the earth and whoso forsakes home", 127,
              x0=90.0, width=253.0),   # x1=343
        _line("being a fugitive to God and death overtakes that man", 140.5,
              x0=90.0, width=252.0),   # x1=342 — still full to the block margin
        _line("ever Forgiving Merciful (4:100)", 154, x0=90.0, width=100.0),
        _line("The juxtaposition of these citations shows a deep truth", 172),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    texts = [p.text() for p in _paras(res.flow)]
    quote = [t for t in texts if t.startswith("Whoso migrates")]
    assert len(quote) == 1  # the four quote lines are ONE paragraph, not four
    assert "abundance in the earth" in quote[0]
    assert quote[0].rstrip().endswith("(4:100)")
    assert any(t.startswith("The juxtaposition") for t in texts)


def test_hanging_indent_list_items(tmp_path):
    # I&B printed xiv: items start at x0=90, continuations hang DEEPER at
    # x0=108. A deeper x0 after a FULL line is a continuation, not a new
    # paragraph; the item boundary breaks via the short last line
    pages = [_page(1, [
        _line("context line running the full column width here now", 61),
        _line("second context line running the full column width to", 74),
        _line("third context line running the full column width too", 87),
        _line("(3) The belief in the categorical moral imperative", 100,
              x0=90.0, width=280.0),
        _line("and that through Mercy we are saved and delivered).", 113.5,
              x0=108.0, width=232.0),
        _line("(4) The belief that human beings are capable of sup", 127,
              x0=90.0, width=282.0),
        _line("knowledge, the source both of salvation in the Here", 140.5,
              x0=108.0, width=264.0),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    texts = [p.text() for p in _paras(res.flow)]
    assert any("imperative and that through Mercy" in t for t in texts)
    assert any(t.startswith("(4) The belief") and "knowledge, the source"
               in t for t in texts)
    assert len([t for t in texts if t.startswith("(")]) == 2


def test_cross_page_quote_continues(tmp_path):
    # I&B pp.16-17 shape: a quote block's insets differ by a few points
    # across the page turn; the continuation must NOT split mid-sentence
    pages = [
        _page(1, [_line("body context establishing the column geometry wide", 74),
                  _line("more body context running to the right margin one", 87),
                  _line("worthy beings who were ill conducted in body and s",
                        520, x0=81.0, width=273.0)]),
        _page(2, [_line("mind, revilers of noble ones, wrong in their views",
                        72, x0=90.0, width=264.0),
                  _line("third body context line running to the right edge", 500),
                  _line("fourth body context line running to the far right", 513)]),
    ]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    # quote continuation joins across the turn (first para = context+quote
    # start; the p.2 quote line must NOT start its own paragraph)
    texts = [p.text() for p in _paras(res.flow)]
    assert any("body and s mind, revilers" in t for t in texts)
    # but a paragraph that visibly ENDED (short last line) breaks at the turn
    pages = [
        _page(1, [_line("the paragraph ends short here.", 520, x0=72.0,
                        width=140.0)]),
        _page(2, [_line("A new paragraph opens the next page at the margin",
                        72, x0=72.0, width=290.0)]),
    ]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    assert len(_paras(res.flow)) == 2


def test_noteref_keeps_join_separator(tmp_path):
    # the marker run carries the join separator appended by _append_line;
    # replacing it with a NoteRef must leave a space run behind, or the
    # following joined line fuses onto the ref ('word.[38]The next')
    body = [
        PdfLine(runs=[PdfRun(text="First line of body text runs to the margin.",
                             font_id=BODY, x0=72, y0=100, x1=352, y1=112),
                      PdfRun(text="38", font_id=SUP, superscript=True,
                             x0=353, y0=98, x1=361, y1=106)],
                x0=72, y0=100, x1=361, y1=112),
        _line("The continuation line joins after the marker.", 113.5),
        _line("38. The footnote body text sits down here", 600, font=SMALL),
    ]
    cfg = _cfg(tmp_path, footnote_policy="markers", footnote_marker="digits")
    res = build_flow(_doc([_page(1, body)]), cfg, say=lambda m: None)
    para = _paras(res.flow)[0]
    kinds = [type(it).__name__ for it in para.items]
    ref_at = kinds.index("NoteRef")
    after = para.items[ref_at + 1]
    assert isinstance(after, TextRun) and after.text.startswith(" ")
    assert "".join(getattr(it, "text", "") for it in para.items) == (
        "First line of body text runs to the margin. "
        "The continuation line joins after the marker.")
    # marker at paragraph end: nothing follows, no stray space run
    body2 = [
        PdfLine(runs=[PdfRun(text="Paragraph ends with a marker.",
                             font_id=BODY, x0=72, y0=100, x1=260, y1=112),
                      PdfRun(text="7", font_id=SUP, superscript=True,
                             x0=261, y0=98, x1=266, y1=106)],
                x0=72, y0=100, x1=266, y1=112),
        _line("7. Note body for the second case here", 600, font=SMALL),
    ]
    res2 = build_flow(_doc([_page(1, body2)]), cfg, say=lambda m: None)
    para2 = _paras(res2.flow)[0]
    assert isinstance(para2.items[-1], NoteRef)


def test_inline_anchor_at_continuation_seam(tmp_path):
    from pdf2epub.core.model import InlinePageBreak

    pages = [_page(1, [
        _line("First paragraph line one", 100),
        _line("continues here and then", 113.5),
        _line("spills toward the page end", 127),
    ]), _page(2, [
        _line("finishing on the next page.", 100),
        _line("Second paragraph starts indented", 113.5, x0=90.0),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    paras = _paras(res.flow)
    assert len(paras) == 2
    # page 2 starts mid-paragraph: its anchor sits INSIDE the spanning
    # paragraph at the exact run seam, not deferred to the next block
    kinds = [type(it).__name__ for it in paras[0].items]
    assert kinds.count("InlinePageBreak") == 1
    at = kinds.index("InlinePageBreak")
    assert paras[0].items[at].ordinal == 2
    before = "".join(it.text for it in paras[0].items[:at]
                     if isinstance(it, TextRun))
    after = "".join(it.text for it in paras[0].items[at:]
                    if isinstance(it, TextRun))
    assert before.endswith("page end ")   # join separator BEFORE the anchor
    assert after.startswith("finishing")
    block_anchors = [b for b in res.flow.blocks if isinstance(b, PageAnchor)]
    assert [a.ordinal for a in block_anchors] == [1]
    assert not any(a.approximate for a in block_anchors)
    assert res.counts["anchor-inline"] == 1


def test_inline_anchor_dehyphenated_seam(tmp_path):
    from pdf2epub.core.model import InlinePageBreak

    pages = [
        _page(1, [_line("the discussion of the rational tradi-", 520)]),
        _page(2, [_line("tion resumes on the next page here now", 72)]),
    ]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    para = _paras(res.flow)[0]
    assert "tradition resumes" in para.text()
    kinds = [type(it).__name__ for it in para.items]
    at = kinds.index("InlinePageBreak")
    # mid-word anchor: no space fabricated around the dehyphenated seam
    assert para.items[at - 1].text.endswith("tradi")
    assert para.items[at + 1].text.startswith("tion")


def test_inline_anchor_blank_page_flush(tmp_path):
    from pdf2epub.core.model import InlinePageBreak
    from pdf2epub.qa.visual import _flow_anchors

    pages = [
        _page(1, [_line("a paragraph running to the right margin and it", 520)]),
        _page(2, []),   # blank page: anchor deferred
        _page(3, [_line("continuing the same sentence on page three now", 72)]),
    ]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    para = _paras(res.flow)[0]
    inline = [it for it in para.items if isinstance(it, InlinePageBreak)]
    # the blank page's deferred anchor flushes at the same seam, in order
    assert [a.ordinal for a in inline] == [2, 3]
    assert [a.ordinal for a in _flow_anchors(res.flow)] == [1, 2, 3]


def test_inline_pagebreak_roundtrip():
    import json

    from pdf2epub.core.model import (InlinePageBreak, Paragraph, SourceRef,
                                     block_from_dict, block_to_dict)

    p = Paragraph(style="s",
                  items=[TextRun("a"), InlinePageBreak(5, "v"), TextRun("b")],
                  src=SourceRef("p0001", 0))
    p2 = block_from_dict(json.loads(json.dumps(block_to_dict(p))))
    assert [type(it).__name__ for it in p2.items] == \
        ["TextRun", "InlinePageBreak", "TextRun"]
    assert p2.items[1].ordinal == 5 and p2.items[1].label == "v"


def test_emit_inline_pagebreak_span(tmp_path):
    from pdf2epub.core.emit_xhtml import Emitter

    pages = [_page(1, [
        _line("First paragraph line one", 100),
        _line("spills toward the page end", 113.5),
    ]), _page(2, [
        _line("finishing on the next page.", 100),
    ])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    out = Emitter(_cfg(tmp_path), res.flow, say=lambda m: None).emit()
    body = "".join(part for f in out.files for part in f.body_parts)
    assert ('<span id="pg-2" class="pagebreak" epub:type="pagebreak" '
            'role="doc-pagebreak" aria-label="2"></span>') in body
    pbs = [pb for f in out.files for pb in f.pagebreaks]
    assert [label for label, _ in pbs] == ["1", "2"]   # document order
    # rescue: a dropped paragraph must not swallow its inline anchor
    para = _paras(res.flow)[0]
    para.role = "drop"
    out2 = Emitter(_cfg(tmp_path), res.flow, say=lambda m: None).emit()
    body2 = "".join(part for f in out2.files for part in f.body_parts)
    assert '<div id="pg-2"' in body2
    pbs2 = [pb for f in out2.files for pb in f.pagebreaks]
    assert [label for label, _ in pbs2] == ["1", "2"]


def test_is_shifted_run_wordshape():
    from pdf2epub.textfix import is_shifted_run, repair_shifted_cmap

    assert is_shifted_run("WKH\x03ERRN")            # control marker (space)
    assert is_shifted_run("%LEOLRJUDSK\\")          # marker-less single word
    assert repair_shifted_cmap("%LEOLRJUDSK\\", {})[0] == "Bibliography"
    # real text must never shape-match: capitals shift to backtick-range
    # junk, digits to capitals, lowercase is outside the shifted range
    for real in ("BIBLIOGRAPHY", "COPYRIGHT", "2004", "$40,50%", "Fig.7",
                 "plain text", "NNW-by-W"):
        assert not is_shifted_run(real), real


def test_is_shifted_run_highmap_wordshape():
    from pdf2epub.textfix import is_shifted_run, repair_shifted_cmap

    hm = {"¶": "ʾ"}  # ¶ -> ʾ (hamza), the I&B-verified entry
    # 'VDED¶' (I&B p.140 italic run) = 'sabaʾ': shifted letters + one
    # highmap diacritic — invisible to the pure word-shape branch
    assert is_shifted_run("VDED¶", hm)
    assert repair_shifted_cmap("VDED¶", hm)[0] == "sabaʾ"
    assert not is_shifted_run("VDED¶")          # no highmap: undetected
    assert not is_shifted_run("VDED¶", {})
    # precision: >=4 in-range chars, >=1 highmap char, full coverage
    assert not is_shifted_run("AB¶", hm)        # too few in-range
    assert not is_shifted_run("$40,50%", hm)         # no highmap char
    assert not is_shifted_run("see ¶4", hm)     # lowercase outside range
    for real in ("BIBLIOGRAPHY", "COPYRIGHT", "2004", "Fig.7", "plain text",
                 "NNW-by-W"):
        assert not is_shifted_run(real, hm), real


def test_probe_text_repairs_folio_shape():
    from pdf2epub.textfix import probe_text
    from pdf2epub.core.textnorm import is_folio_line
    # I&B p.154 folio '129' arrives as control bytes; the furniture SHAPE test
    # runs before the flow's per-run repair, so probe_text must repair first
    assert probe_text("\x14\x15\x1c", True, {}) == "129"
    assert is_folio_line(probe_text("\x14\x15\x1c", True, {}))
    # no-op when repair is off (every other book) or the text already decoded
    assert probe_text("\x14\x15\x1c", False, {}) == "\x14\x15\x1c"
    assert probe_text("129", True, {}) == "129"
    assert probe_text("body words", True, {}) == "body words"


def test_shifted_cmap_folio_stripped(tmp_path):
    # I&B p.154: a shifted-CMap folio at the page foot must strip as furniture,
    # not leak into the body as an unmapped pstyle (furniture stripping runs
    # ahead of the flow's text repair, so the shape test repairs the folio)
    cfg = _cfg(tmp_path, shifted_cmap_repair=True)
    pages = [_page(1, [
        _line("A body paragraph running to the right margin here now", 100),
        _line("that continues onto a second full line of the column", 113.5),
        _line("\x14\x15\x1c", 610, x0=205.0, width=15.0),   # garbled folio '129'
    ])]
    res = build_flow(_doc(pages), cfg, say=lambda m: None)
    texts = " ".join(p.text() for p in _paras(res.flow))
    assert "129" not in texts and "\x14\x15\x1c" not in texts
    # the body itself is untouched
    assert any("second full line" in p.text() for p in _paras(res.flow))


def test_fffd_repair_pagescoped(tmp_path):
    from pdf2epub.config import FffdRepair

    pages = [_page(1, [_line("Note prefix ��� then text", 100)])]
    cfg = _cfg(tmp_path, fffd_repairs=[
        FffdRepair(pages=[1], replace="", note="render: leader rule, no text")])
    res = build_flow(_doc(pages), cfg, say=lambda m: None)
    text = _paras(res.flow)[0].text()
    assert "�" not in text
    assert text == "Note prefix then text"       # collapse eats the double space
    assert res.counts["fffd-replaced"] == 3
    # uncovered page: kept (never silently dropped) + counted + warned
    res2 = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    assert "�" in _paras(res2.flow)[0].text()
    assert res2.counts["fffd-unrepaired"] == 3
    assert any("U+FFFD" in w.msg for w in res2.warns)
    # a stale entry (its pages carry no FFFD) is a config bug
    cfg3 = _cfg(tmp_path, fffd_repairs=[
        FffdRepair(pages=[9], replace="", note="n")])
    with pytest.raises(SystemExit, match="stale glyphs.fffd_repairs"):
        build_flow(_doc(pages), cfg3, say=lambda m: None)


def test_textfix_functions():
    assert expand_ligatures("ﬁnal ﬂow")[0] == "final flow"
    t, n = restore_spaces('say,"If I went.Then')
    assert t == 'say, "If I went. Then' and n == 2
    t, n = restore_spaces("W.M. Watt and op.cit. stay")
    assert n == 0
    # bracket/paren/digit + comma + double quote + capital (MR gate-11
    # residuals): the mandatory quote keeps initials and numerics out
    t, n = restore_spaces('say [about me],"This man and (216),"We have '
                          'and Koran 86:9,"On the day')
    assert t == ('say [about me], "This man and (216), "We have '
                 'and Koran 86:9, "On the day') and n == 3
    assert restore_spaces("pp. 12,14 and 1,000 stay")[1] == 0
    # 2026-07-10: the comma+lowercase class is repaired too (print-verified
    # during the M&R proofread pass — the deferral this line used to pin)
    assert restore_spaces('lower,"case stays quoteless,next')[1] == 2
    assert dehyphenate_join("tradi-", "tion") == ("tradi", "", True)
    assert dehyphenate_join("Kaccayanagotta-", "Sutta") == ("Kaccayanagotta-", "", False)
    assert dehyphenate_join("plain", "next") == ("plain", " ", False)
    # compound-forming prefixes keep their hyphen (I&B 'selfevident' class)
    assert dehyphenate_join("will be self-", "evident") == ("will be self-", "", False)
    assert dehyphenate_join("God's all-", "embracing") == ("God's all-", "", False)
    # ...but only as whole words: 'himself-' is not the prefix 'self-'
    assert dehyphenate_join("himself-", "ish")[2] is True
    assert dehyphenate_join("At twenty-", "two, he")[2] is False
    assert dehyphenate_join("a low-", "lying parcel")[2] is False
    assert dehyphenate_join("must follow-", "ing")[2] is True  # not 'low-'
    # closed em/en-dash at line end joins WITHOUT a space (Schuon's dash style:
    # 'object—or', not 'object— or' — a false 'word- word' after normalize)
    assert dehyphenate_join("cast by an object—", "or that") == ("cast by an object—", "", False)
    assert dehyphenate_join("al-Khidr—", "and outside") == ("al-Khidr—", "", False)
    assert dehyphenate_join("a range 26–", "28 pages") == ("a range 26–", "", False)
    # a SPACED dash keeps the space (base ends ' —', not a letter)
    assert dehyphenate_join("word —", "word") == ("word —", " ", False)
    # a soft hyphen (U+00AD) at the line end is an explicit hyphenation point:
    # drop it and join closed regardless of the continuation's case
    assert dehyphenate_join("eso­", "terism") == ("eso", "", True)
    assert dehyphenate_join("Apara­", "Brahma") == ("Apara", "", True)


def _seamline(a_text, b_text, y=100.0):
    """One PdfLine of two runs with different formatting (roman + italic) so
    _mk_runs keeps the run seam."""
    return PdfLine(runs=[
        PdfRun(text=a_text, font_id=BODY, x0=72, y0=y, x1=250, y1=y + 12),
        PdfRun(text=b_text, font_id=BODY, italic=True,
               x0=251, y0=y, x1=362, y1=y + 12)],
        x0=72, y0=y, x1=362, y1=y + 12)


def test_restore_space_seam():
    from pdf2epub.textfix import restore_space_seam

    assert restore_space_seam("believer.", "This") == ("believer. ", "This", 1)
    assert restore_space_seam('say,"', "If") == ('say, "', "If", 1)
    assert restore_space_seam("word”", "We") == ("word” ", "We", 1)
    # punctuation opening the second run: the space lands there instead
    assert restore_space_seam("believer", ".This") == ("believer", ". This", 1)
    # initials / abbreviations / already-spaced seams stay untouched
    assert restore_space_seam("W.", "M. Watt") == ("W.", "M. Watt", 0)
    assert restore_space_seam("op.", "cit.") == ("op.", "cit.", 0)
    assert restore_space_seam("ends. ", "Then") == ("ends. ", "Then", 0)
    assert restore_space_seam("plain", "text") == ("plain", "text", 0)
    assert restore_space_seam("", "Text") == ("", "Text", 0)


def test_cross_run_space_restore(tmp_path):
    # MR prepress: a space lost exactly at a roman/italic run seam is
    # invisible to per-run restore_spaces ('believer.'+'This') — the
    # paragraph-level seam pass repairs it, preserving run formatting
    pages = [_page(1, [_seamline("the mirror of the believer.",
                                 "This means either that God")])]
    res = build_flow(_doc(pages), _cfg(tmp_path, restore_spaces=True),
                     say=lambda m: None)
    para = _paras(res.flow)[0]
    assert para.text() == "the mirror of the believer. This means either that God"
    runs = [it for it in para.items if isinstance(it, TextRun)]
    assert runs[0].text.endswith(". ") and not runs[0].fmt.italic
    assert runs[1].text.startswith("This") and runs[1].fmt.italic
    assert res.counts["spaces-restored-crossrun"] == 1
    # quote seam
    pages = [_page(1, [_seamline('and they say,"', "If I went away")])]
    res = build_flow(_doc(pages), _cfg(tmp_path, restore_spaces=True),
                     say=lambda m: None)
    assert _paras(res.flow)[0].text() == 'and they say, "If I went away'
    # initials at a seam stay protected
    pages = [_page(1, [_seamline("as quoted by W.", "M. Watt in his study")])]
    res = build_flow(_doc(pages), _cfg(tmp_path, restore_spaces=True),
                     say=lambda m: None)
    assert "W.M. Watt" in _paras(res.flow)[0].text()
    assert res.counts.get("spaces-restored-crossrun", 0) == 0
    # gated on flow.restore_spaces (default off): seam untouched
    pages = [_page(1, [_seamline("the mirror of the believer.",
                                 "This means either that God")])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    assert "believer.This" in _paras(res.flow)[0].text()


def test_cross_run_space_restore_in_notes(tmp_path):
    # the seam pass also runs on footnote paragraphs, and its counts roll up
    body = [
        PdfLine(runs=[PdfRun(text="Body text with a marker", font_id=BODY,
                             x0=72, y0=100, x1=290, y1=112),
                      PdfRun(text="7", font_id=SUP, superscript=True,
                             x0=291, y0=98, x1=296, y1=106)],
                x0=72, y0=100, x1=296, y1=112),
        PdfLine(runs=[PdfRun(text="7. The note ends here.", font_id=SMALL,
                             x0=72, y0=600, x1=200, y1=610),
                      PdfRun(text="Then it continues in italic",
                             font_id=SMALL, italic=True,
                             x0=201, y0=600, x1=340, y1=610)],
                x0=72, y0=600, x1=340, y1=610),
    ]
    cfg = _cfg(tmp_path, footnote_policy="markers", footnote_marker="digits",
               restore_spaces=True)
    res = build_flow(_doc([_page(1, body)]), cfg, say=lambda m: None)
    note = list(res.flow.notes.values())[0]
    assert note.paragraphs[0].text() == \
        "The note ends here. Then it continues in italic"
    assert res.counts["spaces-restored-crossrun"] == 1


def _runline(specs, y):
    """PdfLine from [(text, x0, x1), ...] run specs (baseline-fused columns)."""
    runs = [PdfRun(text=t, font_id=SMALL, x0=a, y0=y, x1=b, y1=y + 10)
            for t, a, b in specs]
    return PdfLine(runs=runs, x0=min(r.x0 for r in runs), y0=y,
                   x1=max(r.x1 for r in runs), y1=y + 10)


def test_flow_columns_resplit(tmp_path):
    from pdf2epub.config import ColumnSpec

    # two-column index page: a centered heading spans the gutter (~192-221);
    # some lines arrive baseline-FUSED across both columns, one col-1 entry
    # carries a hanging-indent turnover, and column 2 holds its own lines
    pages = [_page(1, [
        _runline([("Qur'anic Verses Cited", 180.0, 260.0)], 100),
        _runline([("2:44, 169, 183", 72.0, 160.0),
                  ("18:67, 145", 222.0, 320.0)], 130),
        _runline([("2:89, 174", 72.0, 150.0),
                  ("18:70, 145", 222.0, 330.0)], 142),
        _runline([("ablutions, 33, 66,", 72.0, 190.0)], 154),
        _runline([("71, 108", 103.5, 150.0),
                  ("20:24, 102", 222.0, 310.0)], 166),
    ])]
    cfg = _cfg(tmp_path, flow_columns=[ColumnSpec(pages=[1], count=2)])
    res = build_flow(_doc(pages), cfg, say=lambda m: None)
    texts = [p.text() for p in _paras(res.flow)]
    assert texts == [
        "Qur'anic Verses Cited",       # spanner emits before the columns
        "2:44, 169, 183",              # column 1, top to bottom
        "2:89, 174",
        "ablutions, 33, 66, 71, 108",  # turnover joined to its entry
        "18:67, 145",                  # then column 2
        "18:70, 145",
        "20:24, 102",
    ]
    assert res.counts.get("column-pages") == 1
    assert res.counts.get("column-spanners") == 1


def test_flow_columns_no_gutter_warns(tmp_path):
    from pdf2epub.config import ColumnSpec

    # full-width prose lines: no gutter exists — page must stay in y-order
    # with a loud warning, never silently mangle
    pages = [_page(1, [
        _line("An ordinary full width body line of text here", 100),
        _line("and another one continuing the paragraph.", 113),
    ])]
    cfg = _cfg(tmp_path, flow_columns=[ColumnSpec(pages=[1], count=2)])
    res = build_flow(_doc(pages), cfg, say=lambda m: None)
    assert any("gutters were not found" in w.msg for w in res.warns)
    assert [p.text() for p in _paras(res.flow)] == [
        "An ordinary full width body line of text here "
        "and another one continuing the paragraph."]


def test_figure_region_ships_table_as_raster(tmp_path):
    from pdf2epub.config import FigureRegion
    from pdf2epub.core.model import Figure

    # prose, then a 3-column table (mangled by line order), then prose:
    # the region rect swallows the table lines and a Figure lands in place
    pages = [_page(1, [
        _line("Intro paragraph before the legend table sits here.", 100),
        _line("Arabic glyphEnglish meaningUsage", 150),
        _line("GlyphMighty and majestic isOn mention of God", 165),
        _line("He", 180),
        _line("Closing paragraph after the table resumes the prose.", 230),
    ])]
    cfg = _cfg(tmp_path, figure_regions=[
        FigureRegion(page=1, rect=(60.0, 140.0, 380.0, 200.0),
                     alt="Legend table of honorific glyphs")])
    res = build_flow(_doc(pages), cfg, say=lambda m: None)
    blocks = [b for b in res.flow.blocks if isinstance(b, (Paragraph, Figure))]
    assert [type(b).__name__ for b in blocks] == ["Paragraph", "Figure", "Paragraph"]
    fig = blocks[1]
    assert fig.image_key == "region-0001-0.png"
    assert fig.alt == "Legend table of honorific glyphs"
    assert "Mighty" not in blocks[2].text() and "Mighty" not in blocks[0].text()
    # gt excision evidence: whole lines AND their runs, normalized
    assert any("Mighty and majestic" in t for t in res.region_texts[1])
    assert res.counts.get("figure-regions") == 1


def _mrun(x0, x1, text, y):
    return PdfRun(text=text, font_id=BODY, superscript=False,
                  x0=x0, y0=y, x1=x1, y1=y + 12)


def _mline(runs):
    xs0 = [r.x0 for r in runs]
    xs1 = [r.x1 for r in runs]
    y = runs[0].y0
    return PdfLine(runs=list(runs), x0=min(xs0), y0=y, x1=max(xs1), y1=y + 12)


def test_column_splits_ignores_gutter_crossing_running_head():
    """A full-width running head spans BOTH columns and their gutter; on a
    sparse section it fills the very channel detection needs. The skip
    predicate (furniture) must exclude it so the gutter is found again.
    Regression: Sufism index recto pages (recto/verso margin split)."""
    from pdf2epub.flowbuilder import _column_splits

    lines = []
    # two full-width running-head lines crossing the gutter (x 100..350)
    for k in range(2):
        lines.append(_mline([_mrun(100.0, 350.0, "Running Head", 40.0 + k)]))
    # 15 two-column body lines: left [72,200], right [240,380]
    for k in range(15):
        y = 70.0 + k * 13
        lines.append(_mline([_mrun(72.0, 200.0, f"left entry {k}", y),
                             _mrun(240.0, 380.0, f"right entry {k}", y)]))
    page = _page(1, lines)

    # without skip the running heads mask the gutter -> not found
    assert _column_splits([page], 2) is None
    # skipping the running-head lines recovers the gutter (~just left of 240)
    skip = lambda ln: ln.text().startswith("Running Head")
    splits = _column_splits([page], 2, skip=skip)
    assert splits is not None and len(splits) == 1
    assert 200.0 < splits[0] < 240.0


# ---- footnote marker detection (smaller-font / superscript digit markers) ----

def _frun(text, font, x0, x1, y, sup=False):
    return PdfRun(text=text, font_id=font, superscript=sup,
                  x0=x0, y0=y, x1=x1, y1=y + 9)


def _fline(runs):
    return PdfLine(runs=list(runs), x0=min(r.x0 for r in runs), y0=runs[0].y0,
                   x1=max(r.x1 for r in runs), y1=runs[0].y0 + 9)


class _Lw:
    def __init__(self, ln):
        self.ln = ln


def test_note_start_and_marker_smaller_font():
    """A digit marker set one size down ('8' at 6.5pt over 9pt note text) is a
    note start even though 'digit + single space' misses the text pattern."""
    from pdf2epub.flowbuilder import _note_start, _note_marker
    doc = _doc([])
    ln = _fline([_frun("8", SUP, 72, 78, 560),
                 _frun(" Let us note the relative frequency in Arab texts", SMALL,
                       78, 320, 560)])
    assert _note_start(_Lw(ln), "digits", doc) is True
    assert _note_marker(_Lw(ln), "digits") == "8"
    # a superscript same-size marker also counts
    sup = _fline([_frun("2", SMALL, 72, 78, 560, sup=True),
                  _frun(" This is one of the meanings of this verse", SMALL,
                        78, 320, 560)])
    assert _note_start(_Lw(sup), "digits", doc) is True
    # a note continuation line (note-size, no raised head) is NOT a start
    cont = _fline([_frun("at once patriarchal and mercantile", SMALL,
                         72, 300, 573)])
    assert _note_start(_Lw(cont), "digits", doc) is False


def test_footnote_extracted_and_joined(tmp_path):
    """A small-marker footnote is pulled out of the body and its two typeset
    lines JOIN into one note paragraph (not shattered per line)."""
    body = _line("A body sentence that carries a note marker.", 100)
    fn1 = _fline([_frun("1", SUP, 72, 78, 560),
                  _frun(" This footnote body wraps", SMALL, 78, 320, 560)])
    fn2 = _fline([_frun("across two typeset lines.", SMALL, 72, 300, 573)])
    cfg = _cfg(tmp_path, footnote_policy="markers", footnote_marker="digits")
    res = build_flow(_doc([_page(1, [body, fn1, fn2])]), cfg, say=lambda m: None)
    assert len(res.flow.notes) == 1
    note = next(iter(res.flow.notes.values()))
    assert len(note.paragraphs) == 1
    txt = note.paragraphs[0].text()
    assert "wraps across two typeset lines" in txt
    # the printed marker '1' is stripped (the <ol> numbers the endnote itself)
    assert txt.startswith("This footnote body") and not txt.lstrip()[:1].isdigit()


def test_footnotes_not_merged_across_marked_pages(tmp_path):
    """The note-continuation merge must NOT fold a marker-started note into the
    previous page's note (the '2 …' single-space marker regression)."""
    b1 = _line("Body on page one referencing a note.", 100)
    p1n = _fline([_frun("1", SUP, 72, 78, 560),
                  _frun(" First footnote text on page one.", SMALL, 78, 320, 560)])
    b2 = _line("Body on page two referencing another note.", 100)
    p2n = _fline([_frun("2", SUP, 72, 78, 560),
                  _frun(" Second footnote text on page two.", SMALL, 78, 320, 560)])
    pages = [_page(1, [b1, p1n]), _page(2, [b2, p2n])]
    cfg = _cfg(tmp_path, footnote_policy="markers", footnote_marker="digits")
    res = build_flow(_doc(pages), cfg, say=lambda m: None)
    assert len(res.flow.notes) == 2
    # each note keeps only its own page's text
    texts = [" ".join(p.text() for p in n.paragraphs)
             for n in res.flow.notes.values()]
    assert any("First footnote" in t and "Second footnote" not in t for t in texts)
    assert any("Second footnote" in t and "First footnote" not in t for t in texts)
    # per-page raw excision text is recorded for BOTH pages
    assert set(res.note_raw_by_page) == {1, 2}


def _wline(text, y, x0, x1):
    return PdfLine(runs=[PdfRun(text=text, font_id=BODY, superscript=False,
                                x0=x0, y0=y, x1=x1, y1=y + 12)],
                   x0=x0, y0=y, x1=x1, y1=y + 12)


def test_break_before_scales_short_test_by_left_shift(tmp_path):
    """A recto/verso left-shifted page: full lines end short of the GLOBAL
    modal right edge but must still JOIN, not read as paragraph ends."""
    p1 = [_wline(f"Modal page full measure prose line number {k} runs here now.",
                 100 + 13 * k, 72.0, 381.0) for k in range(6)]
    p2 = [_wline("Shifted page line one runs the full narrower measure now here.",
                 100, 54.0, 360.0),
          _wline("and continues on line two of the same shifted paragraph now.",
                 113, 54.0, 360.0)]
    res = build_flow(_doc([_page(1, p1), _page(2, p2)]), _cfg(tmp_path),
                     say=lambda m: None)
    shifted = [b for b in res.flow.blocks
               if isinstance(b, Paragraph) and "Shifted page" in b.text()]
    assert len(shifted) == 1
    assert "line one" in shifted[0].text() and "line two" in shifted[0].text()


def test_soft_hyphen_repair(tmp_path):
    """Embedded soft hyphens are stripped; a trailing soft hyphen joins closed."""
    pages = [_page(1, [_line("The dif­ficult inde­", 100),
                       _line("pendent word.", 113)])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    txt = _paras(res.flow)[0].text()
    assert "­" not in txt
    assert "difficult" in txt and "independent" in txt


def test_page_shift_centering_recto_verso(tmp_path):
    """A centered line on a left-shifted verso page is still /center; the shift
    is computed only from LEFT-ALIGNED prose, so a centered page gets none.
    Regression: Sufism section-break asterisks + copyright page."""
    from pdf2epub.analyze import column_geometry, line_pstyle
    # modal geometry: 6 full recto lines x0=72..x1=381 (center 226.5)
    recto = [_wline(f"Recto full measure line {k} of ordinary prose text here.",
                    100 + 13 * k, 72.0, 381.0) for k in range(6)]
    # verso body block shifted left 18pt (x0=54..x1=363), plus a short line
    # centered on THAT block (center ~208)
    verso = [_wline(f"Verso full measure line {k} of ordinary prose text now.",
                    100 + 13 * k, 54.0, 363.0) for k in range(4)]
    star = _wline("*", 160.0, 205.0, 211.0)
    doc = _doc([_page(1, recto), _page(2, verso + [star])])
    geo = column_geometry(doc)
    assert geo.shift(2) == 18.0          # verso shift detected
    assert geo.shift(1) == 0.0           # recto = modal, no shift
    # the centered star reads as /center ONLY when the page shift is applied
    assert line_pstyle(star, doc, geo, None,
                       page_shift=geo.shift(2)).endswith("/center")
    assert not line_pstyle(star, doc, geo, None, page_shift=0.0).endswith("/center")


def test_page_shift_skips_centered_page(tmp_path):
    """A page whose only long lines are CENTERED display text (a title page)
    yields NO shift — else its own headings would be un-centered."""
    from pdf2epub.analyze import column_geometry
    body = [_wline(f"Body full measure line {k} of ordinary prose text here.",
                   100 + 13 * k, 72.0, 381.0) for k in range(6)]
    # a 'title page': two wide centered lines at a centered x0, no shared left
    title = [_wline("Sufism: Veil and Quintessence a long centered display title",
                    100, 120.0, 333.0),
             _wline("A New Translation with Selected Letters centered subtitle x",
                    140, 118.0, 335.0)]
    doc = _doc([_page(1, body), _page(2, title)])
    geo = column_geometry(doc)
    assert geo.shift(2) == 0.0           # centered page -> no bogus shift


def test_footnote_split_delimiter_marker(tmp_path):
    """Marker '1' in its OWN run with the delimiter '. ' in the next run: the
    note body must not start with the stray '.' (review #423 finding 1)."""
    body = _line("A body sentence that carries a note marker.", 100)
    fn = _fline([_frun("1", SUP, 72, 78, 560),
                 _frun(". Footnote body long enough to register as a note.",
                       SMALL, 78, 340, 560)])
    cfg = _cfg(tmp_path, footnote_policy="markers", footnote_marker="digits")
    res = build_flow(_doc([_page(1, [body, fn])]), cfg, say=lambda m: None)
    assert len(res.flow.notes) == 1
    txt = next(iter(res.flow.notes.values())).paragraphs[0].text()
    assert txt.startswith("Footnote body") and txt[0] not in ".)"


def test_page_shift_skips_centered_display_sharing_x0(tmp_path):
    """Three equally-wide CENTERED display lines sharing an x0: 'wide' but inset
    (never full-measure), so no line at that edge confirms a real left margin
    and they anchor NO page shift (review #423 finding 2)."""
    from pdf2epub.analyze import column_geometry
    body = [_wline(f"Body full measure prose line {k} of text here now again.",
                   100 + 13 * k, 72.0, 381.0) for k in range(6)]
    # x0=120..x1=320: width 200 (>= 0.55*wmax so 'wide') but inset both sides
    disp = [_wline("A wide centered display heading inset from both edges now",
                   100 + 18 * k, 120.0, 320.0) for k in range(3)]
    doc = _doc([_page(1, body), _page(2, disp)])
    geo = column_geometry(doc)
    assert geo.shift(2) == 0.0


def test_verse_fields_roundtrip():
    import json

    from pdf2epub.core.model import (Paragraph, SourceRef, block_from_dict,
                                     block_to_dict)

    p = Paragraph(style="s", items=[TextRun("line one\u2028line two")],
                  src=SourceRef("p0001", 0), block_class="verse",
                  verse_turns=[1])
    p2 = block_from_dict(json.loads(json.dumps(block_to_dict(p))))
    assert p2.block_class == "verse"
    assert p2.verse_turns == [1]
    assert "\u2028" in p2.items[0].text
    # old IR dumps without the new keys stay loadable (defaults apply)
    d = block_to_dict(Paragraph(style="s", items=[TextRun("a")],
                                src=SourceRef("p0001", 0)))
    del d["block_class"], d["verse_turns"]
    p3 = block_from_dict(d)
    assert p3.block_class is None and p3.verse_turns == []


# ---------------------------------------------------------------- verse (V1)
# Geometry mirrors the measured Me & Rumi damage cells: synthetic column
# left 72 / right 362, body 11pt at 13pt leading; verse base offset 9
# (x0=81), turn offset 36 (x0=108); prose->verse gap 20.0pt sits just under
# the gap rule (1.6 x 13 = 20.8) and the 9pt indent just under M&R's
# indent_threshold 10 -- the exact knife-edges that fused the p.46 couplet.
# Every page carries full-measure prose anchors at x0=72 so the modal
# column derives as in a real book. Em dash / U+2028 only as escapes.

def _verse_cfg(tmp_path, pages, **kw):
    from pdf2epub.config import VerseSpec
    return _cfg(tmp_path, indent_threshold=10.0,
                blocks_verse=[VerseSpec(pages=pages, base=[9.0], turns=[36.0],
                                        note="test verse")], **kw)


def _p46_lines():
    return [
        _line("Prose line one about the pilgrim heart at full", 87,
              x0=72, width=290),
        _line("measure, and I am happy-hearted and joyful.", 100,
              x0=72, width=290),
        _line("Within the Kaaba, it's fitting that there be no kiblah\u2014",
              120, x0=81, width=237),
        _line("outside the Kaaba, there's no escape from the kiblah.", 133,
              x0=108, width=180),
        _line("(753-55)", 153, x0=90, width=40),
    ]


def test_verse_p46_couplet_extracted_from_prose(tmp_path):
    res = build_flow(_doc([_page(1, _p46_lines())]),
                     _verse_cfg(tmp_path, [1]), say=lambda *a: None)
    paras = _paras(res.flow)
    assert len(paras) == 3
    assert paras[0].block_class is None
    assert paras[0].text().endswith("happy-hearted and joyful.")
    assert paras[1].block_class == "verse"
    assert paras[1].text() == (
        "Within the Kaaba, it's fitting that there be no kiblah\u2014\u2028"
        "outside the Kaaba, there's no escape from the kiblah.")
    assert paras[1].verse_turns == [1]
    assert paras[2].block_class is None
    assert paras[2].text() == "(753-55)"
    assert res.counts["verse-groups"] == 1
    assert res.counts["verse-lines"] == 2


def test_verse_p46_regression_without_config(tmp_path):
    # the shipped-damage cell: WITHOUT blocks.verse the knife-edge geometry
    # fuses the couplet's first line into the prose paragraph (the closed
    # em-dash join, exactly as the old artifact shipped it)
    res = build_flow(_doc([_page(1, _p46_lines())]), _cfg(
        tmp_path, indent_threshold=10.0), say=lambda *a: None)
    paras = _paras(res.flow)
    assert "no kiblah\u2014outside" in paras[0].text()


def test_verse_p35_quatrain(tmp_path):
    lines = [
        _line("Anchor prose at full measure for the modal column", 61,
              x0=72, width=290),
        _line("and a second full-measure line to hold the edges.", 74,
              x0=72, width=290),
        _line("He said in maqam concerning this, I heard:", 87,
              x0=72, width=228),  # prose ends short (x1=300)
        _line("I dwell at your door always, like dirt\u2014", 107,
              x0=81, width=170),
        _line("others come and go like the wind.", 120, x0=108, width=160),
        _line("Whoever brings his heart to your door", 133,
              x0=81, width=232),
        _line("finds health beyond every sickness.", 146, x0=108, width=175),
    ]
    res = build_flow(_doc([_page(1, lines)]),
                     _verse_cfg(tmp_path, [1]), say=lambda *a: None)
    paras = _paras(res.flow)
    assert len(paras) == 2  # [anchors+intro prose] [quatrain stanza]
    verse = [p for p in paras if p.block_class == "verse"]
    assert len(verse) == 1
    assert verse[0].text().count("\u2028") == 3
    assert verse[0].verse_turns == [1, 3]


def test_verse_p165_stanza_gaps_and_full_line_exit(tmp_path):
    lines = [
        _line("Anchor prose at full measure for the modal column", 48,
              x0=72, width=290),
        _line("and a second full-measure line to hold the edges", 61,
              x0=72, width=290),
        _line("and a third, ending the paragraph a bit short.", 74,
              x0=72, width=250),
        _line("Seek refuge in the shape of your rosy cheek,", 94,
              x0=81, width=220),
        _line("have put rose into rosewater.", 107, x0=108, width=150),
        # 20pt stanza gap (> 1.4 x 13 = 18.2) opens stanza two
        _line("Though my gold and silver are spent,", 127, x0=81, width=200),
        _line("I am rich in the coin of your love.", 140, x0=108, width=170),
        # a FULL-measure line at the BASE offset must NOT be swallowed
        # (M&R p.165 line 35 -- the all-short criterion excludes it)
        _line("The commentary resumes at full measure across the", 160,
              x0=81, width=281),
        _line("column and continues like ordinary prose text here.", 173,
              x0=72, width=290),
    ]
    res = build_flow(_doc([_page(1, lines)]),
                     _verse_cfg(tmp_path, [1]), say=lambda *a: None)
    paras = _paras(res.flow)
    verse = [p for p in paras if p.block_class == "verse"]
    assert len(verse) == 2  # two stanzas, one paragraph each
    assert verse[0].text().count("\u2028") == 1
    assert verse[1].text().count("\u2028") == 1
    exits = [p for p in paras if p.text().startswith("The commentary")]
    assert len(exits) == 1 and exits[0].block_class is None


def test_verse_requires_turn_line(tmp_path):
    # base-only ragged short lines (no turn alternation) stay prose even on
    # a spec page; the isolated couplet keeps the spec non-stale
    lines = [
        _line("Anchor prose at full measure for the modal column", 48,
              x0=72, width=290),
        _line("and a second full-measure line to hold the edges", 61,
              x0=72, width=290),
        _line("and a third full-measure anchor for good measure.", 74,
              x0=72, width=290),
        _line("True couplet first line at the base,", 94, x0=81, width=190),
        _line("and its turn line completes it.", 107, x0=108, width=155),
        _line("Full-measure prose separates the couplet from the", 127,
              x0=72, width=290),
        _line("ragged run below, ending its paragraph rather short.", 140,
              x0=72, width=270),
        _line("A ragged base-level short line", 160, x0=81, width=150),
        _line("another ragged line of scattered width", 173, x0=81,
              width=163),
        _line("and a third one, still base", 186, x0=81, width=141),
        _line("Full-measure prose closes the page after the run so", 206,
              x0=72, width=290),
        _line("no pending tail is carried to a nonexistent page.", 219,
              x0=72, width=290),
    ]
    res = build_flow(_doc([_page(1, lines)]),
                     _verse_cfg(tmp_path, [1]), say=lambda *a: None)
    paras = _paras(res.flow)
    verse = [p for p in paras if p.block_class == "verse"]
    assert len(verse) == 1
    assert verse[0].text().startswith("True couplet")
    # the base-only run must not be verse, whatever prose shape it joins as
    assert all("ragged" not in p.text() for p in verse)
    assert all(p.block_class is None for p in paras
               if "ragged" in p.text())


def test_verse_vetoed_by_justified_cluster(tmp_path):
    # a justified inset block (tight right-edge cluster) at a configured
    # level is a BLOCK QUOTE, not verse -- _assign_block_right's cluster
    # vetoes; the quote joins into one paragraph by its own margin
    lines = [
        _line("Anchor prose at full measure for the modal column", 48,
              x0=72, width=290),
        _line("and a second full-measure line to hold the edges", 61,
              x0=72, width=290),
        _line("and a third full-measure anchor for good measure.", 74,
              x0=72, width=290),
        _line("True couplet first line at the base,", 94, x0=81, width=190),
        _line("and its turn line completes it.", 107, x0=108, width=155),
        _line("A justified quote line set at the base offset xx", 127,
              x0=81, width=263.0),
        _line("second justified line reaching the same margin yy", 140,
              x0=81, width=263.4),
        _line("third line ends ragged short like quote ends do.", 153,
              x0=81, width=150),
        _line("Full-measure prose closes the page after the quote", 173,
              x0=72, width=290),
        _line("so nothing dangles at the bottom of this test page.", 186,
              x0=72, width=290),
    ]
    res = build_flow(_doc([_page(1, lines)]),
                     _verse_cfg(tmp_path, [1]), say=lambda *a: None)
    paras = _paras(res.flow)
    verse = [p for p in paras if p.block_class == "verse"]
    assert len(verse) == 1 and verse[0].text().startswith("True couplet")
    quote = [p for p in paras if p.text().startswith("A justified quote")]
    assert len(quote) == 1 and quote[0].block_class is None
    assert "third line ends ragged" in quote[0].text()  # joined, not split


def test_verse_stale_spec_fails_build(tmp_path):
    lines = [_line("Ordinary full-measure prose only here on this", 87,
                   x0=72, width=290),
             _line("page, so the verse spec matches nothing at all.", 100,
                   x0=72, width=290)]
    with pytest.raises(SystemExit, match="stale blocks.verse"):
        build_flow(_doc([_page(1, lines)]),
                   _verse_cfg(tmp_path, [1]), say=lambda *a: None)


def test_verse_class_overrides(tmp_path):
    # class:verse pulls in a citation line whose offset matches no level;
    # class:prose ejecting the couplet's base line leaves no acceptable
    # group -> the spec is stale (config bug)
    lines = _p46_lines()
    cfg = _verse_cfg(tmp_path, [1])
    cfg.flow_overrides = [
        FlowOverride(page=1, line=4, action="class:verse", note="citation")]
    res = build_flow(_doc([_page(1, lines)]), cfg, say=lambda *a: None)
    paras = _paras(res.flow)
    verse = [p for p in paras if p.block_class == "verse"]
    assert any("(753-55)" in p.text() for p in verse)

    cfg2 = _verse_cfg(tmp_path, [1])
    cfg2.flow_overrides = [
        FlowOverride(page=1, line=2, action="class:prose", note="not verse")]
    with pytest.raises(SystemExit, match="stale blocks.verse"):
        build_flow(_doc([_page(1, lines)]), cfg2, say=lambda *a: None)


def test_verse_cross_page_stanza_inline_anchor(tmp_path):
    from pdf2epub.core.model import InlinePageBreak

    p1 = _page(1, [
        _line("Prose introduces the poem at full measure width", 87,
              x0=72, width=290),
        _line("continuing to the couplet with a colon here:", 100,
              x0=72, width=290),
        # the couplet's base line ends page 1: a pending tail no page can
        # accept alone -- stitched when page 2's turn line accepts the union
        _line("I dwell at your door always, like dirt\u2014", 120,
              x0=81, width=170),
    ])
    p2 = _page(2, [
        _line("others come and go like the wind.", 87, x0=108, width=160),
        _line("Prose resumes after the poem at full measure and", 110,
              x0=72, width=290),
        _line("runs on to the end of the paragraph as usual.", 123,
              x0=72, width=290),
    ])
    res = build_flow(_doc([p1, p2]), _verse_cfg(tmp_path, [1, 2]),
                     say=lambda *a: None)
    paras = _paras(res.flow)
    verse = [p for p in paras if p.block_class == "verse"]
    assert len(verse) == 1
    assert verse[0].text() == ("I dwell at your door always, like "
                               "dirt\u2014\u2028others come and go like "
                               "the wind.")
    assert verse[0].verse_turns == [1]
    # the page-2 anchor lands INSIDE the stanza at the exact line seam
    inline = [it for it in verse[0].items if isinstance(it, InlinePageBreak)]
    assert [a.ordinal for a in inline] == [2]


def test_verse_suspect_warning_fires_uncovered(tmp_path):
    # the uncalibrated witness: a verse-shaped run (>=3 lines, two levels,
    # ragged) with NO blocks.verse config warns verse-suspect
    lines = [
        _line("Ordinary prose paragraph at full measure width to", 74,
              x0=72, width=290),
        _line("anchor the leading and the column edges properly.", 87,
              x0=72, width=290),
        _line("I dwell at your door always, like dirt,", 107,
              x0=81, width=170),
        _line("others come and go like the wind.", 120, x0=108, width=160),
        _line("Whoever brings his heart to your door", 133,
              x0=81, width=232),
    ]
    res = build_flow(_doc([_page(1, lines)]), _cfg(tmp_path),
                     say=lambda *a: None)
    assert res.counts.get("verse-suspect") == 1
    assert any("verse-shaped block" in w for w in res.flow.warnings)


def test_verse_single_level_calibrated(tmp_path):
    # I&B p.113 real geometry: Milarepa song, EVERY line at one 18pt inset
    # (x0=81 on a col-left-63 verso), ragged right — no turn level exists.
    # A spec with empty turns classifies it; the ragged requirement carries
    # the discrimination a turn line provides in two-level verse.
    from pdf2epub.config import VerseSpec

    lines = [
        _line("ling verses of Milarepa, showing how impossible", 61,
              x0=63, width=300),
        _line("from oneself if the sense of self be predominant:", 74,
              x0=63, width=213),
        _line("He who strives for Liberation with", 87, x0=81, width=155),
        _line("The thought of 'I' will ne'er attain it.", 100,
              x0=81, width=165),
        _line("He who tries to loosen his mind-knots", 113,
              x0=81, width=170),
        _line("When his spirit is neither great nor free,", 126,
              x0=81, width=178),
        _line("Will but become more tense.", 139, x0=81, width=133),
        _line("Milarepa also expresses a theme which resonates", 159,
              x0=63, width=300),
        _line("with Muslim ethics in the following verses too.", 172,
              x0=63, width=300),
    ]
    cfg = _cfg(tmp_path, indent_threshold=10.0,
               blocks_verse=[VerseSpec(pages=[1], base=[18.0],
                                       note="single-level Milarepa songs")])
    res = build_flow(_doc([_page(1, lines)]), cfg, say=lambda *a: None)
    paras = _paras(res.flow)
    verse = [p for p in paras if p.block_class == "verse"]
    assert len(verse) == 1
    assert verse[0].text().count("\u2028") == 4
    assert verse[0].verse_turns == []
    assert verse[0].text().startswith("He who strives")
    assert verse[0].text().endswith("more tense.")


def test_verse_suspect_single_level_fires(tmp_path):
    # the uncalibrated witness's single-level rule: >=4 lines at ONE real
    # inset, ragged — the exact shape of I&B p.113's songs
    lines = [
        _line("Ordinary prose paragraph at full measure width to", 61,
              x0=72, width=290),
        _line("anchor the leading and the column edges properly.", 74,
              x0=72, width=290),
        _line("He who strives for Liberation with", 94, x0=90, width=155),
        _line("The thought of 'I' will ne'er attain it.", 107,
              x0=90, width=165),
        _line("He who tries to loosen his mind-knots", 120,
              x0=90, width=170),
        _line("Will but become more tense.", 133, x0=90, width=133),
        _line("Prose resumes after the song at full measure and", 153,
              x0=72, width=290),
        _line("continues to the end of the paragraph as usual.", 166,
              x0=72, width=290),
    ]
    res = build_flow(_doc([_page(1, lines)]), _cfg(tmp_path),
                     say=lambda *a: None)
    assert res.counts.get("verse-suspect") == 1


def test_emit_verse_group(tmp_path):
    # p.46-shaped page through flow AND emitter: one blockquote.verse with
    # z3998 semantics, stanza <p class="vs">, line spans joined by <br/>,
    # turn line carrying vt; prose before/after stays ordinary <p>
    from pdf2epub.core.emit_xhtml import Emitter
    from pdf2epub.core.roles import apply_roles

    cfg = _verse_cfg(tmp_path, [1])
    res = build_flow(_doc([_page(1, _p46_lines())]), cfg, say=lambda m: None)
    apply_roles(res.flow.blocks, {}, "p")
    out = Emitter(cfg, res.flow, say=lambda m: None).emit()
    body = "".join(part for f in out.files for part in f.body_parts)
    assert '<blockquote class="verse" epub:type="z3998:verse">' in body
    assert body.count('<p class="vs') == 1
    assert body.count('<span class="vl">') == 1       # base line
    assert body.count('<span class="vl vt">') == 1    # turn line
    assert "<br/>" in body
    assert "\u2028" not in body  # the separator never ships as a char
    # apply_roles rebuilt role/classes but block_class survived untouched
    assert '<span class="vl">Within the Kaaba' in body


def test_emit_verse_inline_anchor_and_formatting(tmp_path):
    # italic run spanning a U+2028 seam splits into per-line <i>; the
    # cross-page inline anchor lands inside the stanza between line spans
    from pdf2epub.core.emit_xhtml import Emitter

    p1 = _page(1, [
        _line("Prose introduces the poem at full measure width", 87,
              x0=72, width=290),
        _line("continuing to the couplet with a colon here:", 100,
              x0=72, width=290),
        _line("I dwell at your door always, like dirt—", 120,
              x0=81, width=170),
    ])
    p2 = _page(2, [
        _line("others come and go like the wind.", 87, x0=108, width=160),
        _line("Prose resumes after the poem at full measure and", 110,
              x0=72, width=290),
        _line("runs on to the end of the paragraph as usual.", 123,
              x0=72, width=290),
    ])
    # make both verse lines italic at the run level
    for pg in (p1, p2):
        for ln in pg.lines:
            if ln.x0 in (81.0, 108.0):
                for r in ln.runs:
                    r.italic = True
    cfg = _verse_cfg(tmp_path, [1, 2])
    res = build_flow(_doc([p1, p2]), cfg, say=lambda m: None)
    out = Emitter(cfg, res.flow, say=lambda m: None).emit()
    body = "".join(part for f in out.files for part in f.body_parts)
    assert body.count('<span class="vl">') == 1
    assert body.count('<span class="vl vt">') == 1
    # italic renders per line segment, not across the <br/>
    assert body.count("<i>") == 2
    # the page-2 anchor span sits INSIDE the stanza markup
    stanza = body[body.index('<p class="vs'):body.index("</blockquote>")]
    assert 'id="pg-2"' in stanza


def test_emit_two_adjacent_stanzas_one_blockquote(tmp_path):
    from pdf2epub.core.emit_xhtml import Emitter

    lines = [
        _line("Anchor prose at full measure for the modal column", 48,
              x0=72, width=290),
        _line("and a second full-measure line to hold the edges", 61,
              x0=72, width=290),
        _line("and a third, ending the paragraph a bit short.", 74,
              x0=72, width=250),
        _line("Seek refuge in the shape of your rosy cheek,", 94,
              x0=81, width=220),
        _line("have put rose into rosewater.", 107, x0=108, width=150),
        _line("Though my gold and silver are spent,", 127, x0=81, width=200),
        _line("I am rich in the coin of your love.", 140, x0=108, width=170),
        _line("The commentary resumes at full measure across the", 160,
              x0=81, width=281),
        _line("column and continues like ordinary prose text here.", 173,
              x0=72, width=290),
    ]
    cfg = _verse_cfg(tmp_path, [1])
    res = build_flow(_doc([_page(1, lines)]), cfg, say=lambda m: None)
    out = Emitter(cfg, res.flow, say=lambda m: None).emit()
    body = "".join(part for f in out.files for part in f.body_parts)
    assert body.count("<blockquote") == 1  # both stanzas coalesce
    assert body.count('<p class="vs') == 2


def test_verse_long_turn_line_kept_and_intro_prose_shed(tmp_path):
    # print-verified M&R notes p.370 (folio 343): the couplet's turn line
    # ends 4.4pt short of the column (full measure) and MUST stay verse;
    # the note paragraph's first line sits at the verse BASE offset directly
    # above the couplet and must be shed (strict-alternation split: B,B,T
    # -> [B],[B,T]); real raw geometry, offsets vs col_left 72
    from pdf2epub.config import VerseSpec

    lines = [
        _line("Anchor prose at full measure width for the modal", 48,
              x0=72, width=290),
        _line("column and a second anchor line to hold the edge.", 61,
              x0=72, width=290),
        # note continuation prose at x0=98 (offset 26) — outside levels
        _line("animal soul, or the soul that commands to evil.", 74,
              x0=98, width=206),
        # note first line AT the verse base offset (x0=107, offset 35),
        # short — the alternation split sheds it
        _line("Water seeks a thirsty man. Compare M III 4398-99:", 87,
              x0=107, width=228),
        # the couplet: base short, turn nearly FULL measure (x1=352.6)
        _line("The thirsty man laments, O sweet water!", 107,
              x0=107, width=188),
        _line("The water too laments, Where is the drinker?", 120,
              x0=143, width=209.6),
    ]
    cfg = _cfg(tmp_path, indent_threshold=10.0,
               blocks_verse=[VerseSpec(pages=[1], base=[35.0], turns=[71.0],
                                       tol=3.0, note="notes couplets")])
    res = build_flow(_doc([_page(1, lines)]), cfg, say=lambda *a: None)
    paras = _paras(res.flow)
    verse = [p for p in paras if p.block_class == "verse"]
    assert len(verse) == 1
    assert verse[0].text() == ("The thirsty man laments, O sweet water!\u2028"
                               "The water too laments, Where is the drinker?")
    assert verse[0].verse_turns == [1]
    intro = [p for p in paras if "Water seeks" in p.text()]
    assert len(intro) == 1 and intro[0].block_class is None


def test_restore_spaces_prepress_classes_2026_07_10():
    # print-verified M&R prepress lost-space classes (proofread pass)
    cases = [
        ("One would become empty,and they went", "empty, and"),
        ("sitting place of truthfulness,both here", "truthfulness, both"),
        ("He said,‘Helpless fellow!", "said, ‘"),
        ("denial and wonder:‘Since you are", "wonder: ‘"),
        ("Koran 2:255:“God, there is", "2:255: “"),
        ("the words “gnosis”and “dervishhood”have", "“gnosis” and"),
        ("What does “I”have to do", "“I” have"),
        ("as but one soul [31:28].Where is", "[31:28]. Where"),
        ("upon the Throne [20:5];His words", "[20:5]; His"),
        ("kill your souls [2:54],just as", "[2:54], just"),
        ("in two volumes, 1990).Those who", "1990). Those"),
        ("I found ease.(641)", "ease. (641)"),
        ("give me two hundred dirhems.”(343)", "dirhems.” (343)"),
        ("mentions on occasion.*They have no", "occasion.* They"),
        ("4.With me you're like duck eggs", "4. With"),
        ("52.Muhammad the Arab", "52. Muhammad"),
        ("translated by W. M.Thackston", "W. M. Thackston"),
        # the wrong-side-of-the-quote swap
        ("like this. ”These people talk", "this.” These"),
        ("protect them! ”This is the Sunnah", "them!” This"),
        ("keep on denying. ’And that's my", "denying.’ And"),
    ]
    for src, want in cases:
        out, n = restore_spaces(src)
        assert want in out, (src, out)
        assert n >= 1, src


def test_restore_spaces_negative_guards():
    # transliteration apostrophes, decimals, citations, abbreviations,
    # and ordinary prose must pass through byte-identical
    for src in [
        "Sana'i and Ruba'iyyat and wa'llah and Abi'l-Khayr",
        "Sana’i and Ruba’iyyat and wa’llah and Abi’l-Khayr",
        "don’t and it’s and we’ll and I’m and you’ve",
        "see 3.176 and compare 2.254 and M II 3766 ff.",
        "i.e., the prophet; e.g., the saint; d. 1083",
        "a normal sentence, with commas, stays as printed.",
        "“A quoted phrase,” she said, “stays.”",
        "passage 2.14 and note 42.5 and Koran 66:3",
    ]:
        out, n = restore_spaces(src)
        assert out == src, (src, out)
        assert n == 0, src


def test_restore_space_seam_quote_swap():
    from pdf2epub.textfix import restore_space_seam

    # closing quote opens the NEXT run ('copper. ' + '”He beat')
    p, n, k = restore_space_seam("cucumbers for a copper. ", "”He beat")
    assert (p, n, k) == ("cucumbers for a copper.", "” He beat", 1)
    # quote ends the PREVIOUS run ('copper. ”' + 'He beat')
    p, n, k = restore_space_seam("cucumbers for a copper. ”", "He beat")
    assert (p, n, k) == ("cucumbers for a copper.”", " He beat", 1)
    # BOTH-sided spaces at the seam (the collapse pass would otherwise fuse
    # them into the residual '. ”' shape)
    p, n, k = restore_space_seam("of the believer. ", " ”The servants")
    assert (p, n, k) == ("of the believer.", "” The servants", 1)
    p, n, k = restore_space_seam("of the believer.", " ”The servants")
    assert (p, n, k) == ("of the believer.", "” The servants", 1)
    # apostrophe continuations across seams stay untouched
    p, n, k = restore_space_seam("he said don", "’t go")
    assert (p, n, k) == ("he said don", "’t go", 0)


def test_quote_swap_after_line_join(tmp_path):
    # print puts the closing quote at the NEXT line's start; the join's
    # separator creates 'sun. ”The' inside one run — the close_para swap
    # pass is the only walker that sees the joined text
    lines = [
        _line('whose name is “sun.', 100, x0=72, width=290),
        _line('”The triumph of this sun became clear over', 113,
              x0=72, width=290),
    ]
    res = build_flow(_doc([_page(1, lines)]),
                     _cfg(tmp_path, restore_spaces=True), say=lambda *a: None)
    text = _paras(res.flow)[0].text()
    assert 'sun.” The triumph' in text
    # the swap lands via the in-run pass or the seam branch depending on
    # whether the join produced one run or two — either counter is fine
    assert (res.counts.get("quote-side-swaps", 0)
            + res.counts.get("spaces-restored-crossrun", 0)) >= 1


def test_dehyphenate_keeps_compound_chains():
    # print-verified M&R proofread class: 'so-/and-so', 'such-/and-such',
    # 'face-to-/face', 'hundred-/thousand-year' are compound chains whose
    # line-end hyphen is lexical
    assert dehyphenate_join("so-", "and-so a dervish") == ("so-", "", False)
    assert dehyphenate_join("such-", "and-such") == ("such-", "", False)
    assert dehyphenate_join("face-to-", "face") == ("face-to-", "", False)
    # ordinary breaks still join closed — INCLUDING breaks inside
    # hyphenated compounds (round-2 proofread findings)
    assert dehyphenate_join("tradi-", "tion") == ("tradi", "", True)
    assert dehyphenate_join("com-", "munity") == ("com", "", True)
    assert dehyphenate_join("faint-hearted-", "ness") == \
        ("faint-hearted", "", True)
    assert dehyphenate_join("know-noth-", "ing") == ("know-noth", "", True)
    assert dehyphenate_join("bro-", "ken-head kept") == ("bro", "", True)
    assert dehyphenate_join("One-col-", "ored words") == \
        ("One-col", "", True)
    assert dehyphenate_join("man-throw-", "ing") == ("man-throw", "", True)


def test_center_lines_respect_gap_rule(tmp_path):
    # M&R copyright page: every line 9pt /center under join_center_lines,
    # but the 22pt block gaps are paragraph breaks (leading 13pt; threshold
    # gap_factor x max(med_lead, 1.35 x the line's OWN size) = 20.8 at 9pt)
    lines = [
        _line("Anchor prose at full measure for the modal column", 27,
              x0=72, width=290),
        _line("and a second full-measure line to hold the edges,", 40,
              x0=72, width=290),
        _line("plus a third and a fourth anchor line so that the", 53,
              x0=72, width=290),
        _line("median leading of the page stays at thirteen too.", 66,
              x0=72, width=290),
        _line("(c) 2004 William C. Chittick", 200, x0=166, width=100,
              font=SMALL),
        _line("This edition printed and distributed by", 222,
              x0=146, width=140, font=SMALL),
        _line("Fons Vitae, Louisville, Kentucky", 235, x0=160, width=112,
              font=SMALL),
        _line("All rights reserved. No part of this book", 257,
              x0=110, width=212, font=SMALL),
    ]
    res = build_flow(_doc([_page(1, lines)]),
                     _cfg(tmp_path, join_center_lines=True),
                     say=lambda *a: None)
    paras = [p.text() for p in _paras(res.flow)]
    center = [t for t in paras if "Chittick" in t or "edition" in t
              or "rights" in t]
    assert any(t.startswith("(c) 2004") and "edition" not in t
               for t in center)          # 22pt gap broke
    assert any("distributed by Fons Vitae" in t for t in center)  # 13pt joined
    assert any(t.startswith("All rights") for t in center)


def test_restore_spaces_display_amp():
    assert restore_spaces("Me &Rumi")[0] == "Me & Rumi"
    assert restore_spaces("Me&Rumi")[0] == "Me & Rumi"
    assert restore_spaces("AT&T stays")[0] == "AT&T stays"
    assert restore_spaces("R&D stays")[0] == "R&D stays"


def test_bare_ampersand_run_gets_spaces(tmp_path):
    from pdf2epub.core.model import Paragraph as P, SourceRef, TextRun
    from pdf2epub.flowbuilder import _restore_cross_run_spaces
    from collections import Counter
    from pdf2epub.core.model import RunFormat

    p = P(style="s", src=SourceRef("p", 0), items=[
        TextRun("Me", RunFormat()), TextRun("&", RunFormat(italic=True)),
        TextRun("Rumi", RunFormat())])
    _restore_cross_run_spaces(p, Counter())
    assert p.text() == "Me & Rumi"


def test_toc_part_title_with_separate_folio_line(tmp_path):
    # M&R printed TOC: part titles carry their folio as a bare right-edge
    # line on (almost) the same baseline; without pairing they fused into
    # the previous entry as a fake wrapped-title continuation
    from pdf2epub.pdfmodel import PdfLine, PdfRun

    def _run(text, x0, y, x1, font=BODY):
        return PdfRun(text=text, font_id=font, superscript=False,
                      x0=x0, y0=y, x1=x1, y1=y + 12)

    def _entry_line(title, folio, y):
        return PdfLine(runs=[_run(title, 82, y, 250),
                             _run(folio, 346, y, 352)],
                       x0=82, y0=y, x1=352, y1=y + 12)

    lines = [
        _line("Contents", 89, x0=177, width=74, font=BIG),
        _entry_line("Foreword", "ix", 123),
        _entry_line("Translator's Introduction", "xi", 137),
        # part title: no folio on the line…
        PdfLine(runs=[_run("My Years without Mawlana", 71, 162.7, 210)],
                x0=71, y0=162.7, x1=210, y1=174),
        # …the folio is its own bare line 2.3pt below at the right edge
        PdfLine(runs=[_run("1", 346.4, 165, 351.8)],
                x0=346.4, y0=165, x1=351.8, y1=177),
        _entry_line("Childhood", "3", 179),
    ]
    cfg = _cfg(tmp_path, toc_source="printed", toc_printed_pages=[1])
    res = build_flow(_doc([_page(1, lines)]), cfg, say=lambda *a: None)
    toc = [p.text() for p in _paras(res.flow) if p.style == "__toc__"]
    assert "My Years without Mawlana\t1" in toc
    assert "Translator's Introduction\txi" in toc
    assert not any("Introduction My Years" in t for t in toc)


def test_center_gap_scales_with_display_size(tmp_path):
    # a two-line 21pt part title leads ~26pt — body-scaled gaps would split
    # it into two h1 spine files (the HU Chapter-55 defect shape)
    lines = [
        _line("Anchor prose at full measure for the modal column", 40,
              x0=72, width=290),
        _line("and a second full-measure line to hold the edges.", 53,
              x0=72, width=290),
        _line("My Years", 200, x0=160, width=110, font=BIG),
        _line("without Mawlana", 226, x0=140, width=150, font=BIG),
    ]
    res = build_flow(_doc([_page(1, lines)]),
                     _cfg(tmp_path, join_center_lines=True),
                     say=lambda *a: None)
    titles = [p.text() for p in _paras(res.flow) if "My Years" in p.text()]
    assert titles == ["My Years without Mawlana"]


# --------------------------------------------------------------- blocks.quotes

def _quote_cfg(tmp_path, pages, left=18.0, right=18.0, **kw):
    from pdf2epub.config import QuoteSpec
    return _cfg(tmp_path, blocks_quotes=[QuoteSpec(
        pages=pages, left_inset=left, right_inset=right,
        note="test quotes")], **kw)


def _ib_p51_lines():
    # I&B p.51-shaped page (synthetic column 72..362): body full measure at
    # x0=72/width 290; the body's own first-line indent is ALSO 18pt (x0=90),
    # exactly the quote inset -- the justified right cluster is the only
    # discriminator between them
    return [
        _line("Anchor prose at full measure holds the column edge", 48,
              x0=72, width=290),
        _line("and a second full-measure line anchors the right.", 61,
              x0=72, width=290),
        _line("An indented body paragraph opens here and runs to", 74,
              x0=90, width=272),
        _line("the full body measure on its continuation line and", 87,
              x0=72, width=290),
        _line("closes short.", 100, x0=72, width=80),
        _line("Through your kindness towards others, your mind xx", 113,
              x0=90, width=254),
        _line("will open to peace and expanding this inner state", 126,
              x0=90, width=254.4),
        _line("brings unity and harmony.", 139, x0=90, width=140),
        _line("One is reminded here of the verse at full measure", 152,
              x0=72, width=290),
        _line("closing the page.", 165, x0=72, width=100),
    ]


def test_quote_run_classified_joins_untouched(tmp_path):
    # the doctrine cell: blocks.quotes stamps block_class ONLY -- the flow's
    # paragraphs are IDENTICAL with and without the spec; the body's own
    # first-line indent at the quote offset (run of one, no justified right)
    # never matches
    pages = [_page(1, _ib_p51_lines())]
    plain = build_flow(_doc(pages), _cfg(tmp_path), say=lambda *a: None)
    res = build_flow(_doc([_page(1, _ib_p51_lines())]),
                     _quote_cfg(tmp_path, [1]), say=lambda *a: None)
    assert [p.text() for p in _paras(plain.flow)] == \
        [p.text() for p in _paras(res.flow)]
    paras = _paras(res.flow)
    assert len(paras) == 4
    quoted = [p for p in paras if p.block_class == "quote"]
    assert len(quoted) == 1
    assert quoted[0].text().startswith("Through your kindness")
    assert "brings unity" in quoted[0].text()
    # the indented body paragraph shares the quote's x0 but stays prose
    assert paras[1].block_class is None
    assert res.counts.get("quote-runs") == 1
    assert res.counts.get("quote-lines") == 3
    assert res.counts.get("quote-paras") == 1


def test_quote_boundary_breaks_and_explicit_join_demotes(tmp_path):
    # class entry/exit is a block boundary in print: a quote whose last
    # justified line runs FULL still separates from the resuming prose (the
    # I&B italic-scripture seam the geometric joiner cannot see). An
    # explicit join override is a recorded judgment: the mixed paragraph
    # ships OUTSIDE the blockquote, silently.
    def _lines():
        return [
            _line("Anchor prose at full measure holds the column edge", 48,
                  x0=72, width=290),
            _line("and ends short here.", 61, x0=72, width=120),
            _line("A justified quotation line reaching its margin xxx", 81,
                  x0=90, width=254),
            _line("and a second one reaching exactly the same margin.", 94,
                  x0=90, width=254.4),
            _line("Prose resumes flush left after the full-width exit", 107,
                  x0=72, width=290),
            _line("before ending.", 120, x0=72, width=90),
        ]
    res = build_flow(_doc([_page(1, _lines())]), _quote_cfg(tmp_path, [1]),
                     say=lambda *a: None)
    paras = _paras(res.flow)
    quoted = [p for p in paras if p.block_class == "quote"]
    assert len(quoted) == 1 and quoted[0].text().startswith("A justified")
    assert "Prose resumes" not in quoted[0].text()  # boundary broke
    assert res.counts.get("quote-paras") == 1

    cfg2 = _quote_cfg(tmp_path, [1])
    cfg2.flow_overrides = [
        FlowOverride(page=1, line=4, action="join", note="recorded judgment")]
    res2 = build_flow(_doc([_page(1, _lines())]), cfg2, say=lambda *a: None)
    paras2 = _paras(res2.flow)
    fused = [p for p in paras2 if "Prose resumes" in p.text()]
    assert len(fused) == 1 and fused[0].text().startswith("A justified")
    assert fused[0].block_class is None  # mixed: ships outside blockquote
    assert res2.counts.get("quote-paras", 0) == 0


def test_quote_stale_spec_fails_build(tmp_path):
    lines = [_line("Ordinary full-measure prose only on this page so", 87,
                   x0=72, width=290),
             _line("the quote spec matches nothing at all anywhere.", 100,
                   x0=72, width=290)]
    with pytest.raises(SystemExit, match="stale blocks.quotes"):
        build_flow(_doc([_page(1, lines)]), _quote_cfg(tmp_path, [1]),
                   say=lambda *a: None)


def test_quote_class_overrides(tmp_path):
    # class:quote forces a lone inset line (no justified witness possible);
    # class:prose ejects a detected line from the run
    lines = _ib_p51_lines()
    cfg = _quote_cfg(tmp_path, [1])
    cfg.flow_overrides = [
        FlowOverride(page=1, line=7, action="class:prose", note="not quote")]
    res = build_flow(_doc([_page(1, lines)]), cfg, say=lambda *a: None)
    quoted = [p for p in _paras(res.flow) if p.block_class == "quote"]
    assert len(quoted) == 1
    assert "brings unity" not in quoted[0].text()

    lines2 = [
        _line("Anchor prose at full measure holds the column edge", 48,
              x0=72, width=290),
        _line("and a second full-measure line anchors the right.", 61,
              x0=72, width=290),
        _line("A single inset quotation line, ragged.", 81,
              x0=90, width=160),
        _line("Prose resumes at the full measure after the single", 101,
              x0=72, width=290),
        _line("inset line and closes.", 114, x0=72, width=130),
    ]
    cfg2 = _quote_cfg(tmp_path, [1])
    cfg2.flow_overrides = [
        FlowOverride(page=1, line=2, action="class:quote", note="single")]
    res2 = build_flow(_doc([_page(1, lines2)]), cfg2, say=lambda *a: None)
    quoted2 = [p for p in _paras(res2.flow) if p.block_class == "quote"]
    assert len(quoted2) == 1
    assert quoted2[0].text() == "A single inset quotation line, ragged."


def test_quote_verse_precedence_same_page(tmp_path):
    # a page carrying BOTH: verse (ragged two-level) keeps its class; the
    # justified run becomes the quote; neither poaches the other
    lines = [
        _line("Anchor prose at full measure for the modal column", 48,
              x0=72, width=290),
        _line("and a second full-measure line to hold the edges", 61,
              x0=72, width=290),
        _line("and a third full-measure anchor ends a bit short.", 74,
              x0=72, width=250),
        _line("True couplet first line at the base,", 94, x0=81, width=190),
        _line("and its turn line completes it.", 107, x0=108, width=155),
        _line("A justified quote line set at the quote offset xx", 127,
              x0=90, width=254),
        _line("second justified line reaching the same margin yy", 140,
              x0=90, width=254.4),
        _line("and its closing line ends short.", 153, x0=90, width=140),
        _line("Full-measure prose closes the page after the quote", 173,
              x0=72, width=290),
        _line("so nothing dangles at the bottom of this test page.", 186,
              x0=72, width=290),
    ]
    from pdf2epub.config import QuoteSpec
    cfg = _verse_cfg(tmp_path, [1], blocks_quotes=[QuoteSpec(
        pages=[1], left_inset=18.0, right_inset=18.0, note="test quotes")])
    res = build_flow(_doc([_page(1, lines)]), cfg, say=lambda *a: None)
    paras = _paras(res.flow)
    verse = [p for p in paras if p.block_class == "verse"]
    quoted = [p for p in paras if p.block_class == "quote"]
    assert len(verse) == 1 and verse[0].text().startswith("True couplet")
    assert len(quoted) == 1 and quoted[0].text().startswith("A justified")


def test_emit_quote_group_with_anchor(tmp_path):
    # two quote paragraphs spanning a page turn emit as ONE
    # <blockquote class="quote"> with <p class="bq"> each and the page-2
    # anchor div between them; surrounding prose stays ordinary <p>
    from pdf2epub.core.emit_xhtml import Emitter

    p1 = _page(1, [
        _line("Anchor prose at full measure holds the column edge", 48,
              x0=72, width=290),
        _line("and a second full-measure line anchors the right,", 61,
              x0=72, width=290),
        _line("while a third one introduces the quotation and", 74,
              x0=72, width=290),
        _line("ends short here.", 87, x0=72, width=100),
        _line("First quoted paragraph line one reaching margin xx", 107,
              x0=90, width=254),
        _line("line two also reaches the same justified margin yy", 120,
              x0=90, width=254.4),
        _line("and line three ends the paragraph early.", 133,
              x0=90, width=180),
    ])
    p2 = _page(2, [
        _line("Second quoted paragraph on the next page, again a", 87,
              x0=90, width=254),
        _line("justified pair of lines sharing the same margin xx", 100,
              x0=90, width=254.4),
        _line("ending shorter.", 113, x0=90, width=90),
        _line("Prose resumes at the full measure after the block", 133,
              x0=72, width=290),
        _line("quotation ends and closes the little page nicely.", 146,
              x0=72, width=290),
        _line("A final full-measure anchor line holds the modal", 159,
              x0=72, width=290),
        _line("column against the six quote-inset lines above it.", 172,
              x0=72, width=290),
    ])
    cfg = _quote_cfg(tmp_path, [1, 2])
    res = build_flow(_doc([p1, p2]), cfg, say=lambda m: None)
    out = Emitter(cfg, res.flow, say=lambda m: None).emit()
    body = "".join(part for f in out.files for part in f.body_parts)
    assert body.count('<blockquote class="quote">') == 1
    assert body.count('<p class="bq') == 2
    bq = body[body.index('<blockquote class="quote">'):]
    bq = bq[:bq.index("</blockquote>")]
    assert 'aria-label="2"' in bq  # the page anchor sits INSIDE the group
    assert "First quoted paragraph" in bq and "Second quoted" in bq
    assert "Prose resumes" not in bq


def test_blockshapes_quote_helpers():
    # body_anchors and quote_shape_suspects on the real I&B p.51 numbers:
    # body 63..362.8, quotes x0=81 justified at 344.8 -> insets 18/18
    from pdf2epub.blockshapes import (body_anchors, justified_rights,
                                      quote_shape_suspects)

    class _Ln:
        def __init__(self, x0, x1):
            self.x0, self.x1 = x0, x1
            self.vertical = False

    lines = [
        _Ln(63.0, 362.8), _Ln(63.0, 362.8), _Ln(63.0, 141.8),
        _Ln(81.0, 344.8), _Ln(81.0, 344.7), _Ln(81.0, 344.8),
        _Ln(81.0, 131.4),
        _Ln(63.0, 362.8), _Ln(63.0, 167.7),
    ]
    assert body_anchors(lines, 11.0) == (63.0, 362.8)
    rights = justified_rights(lines)
    assert rights[3] == 344.8 and rights[6] == 344.8  # short last line too
    assert rights[2] == 362.8  # body run's own justified margin
    runs = quote_shape_suspects(lines, 11.0)
    assert len(runs) == 1
    r = runs[0]
    assert (r.start, r.end) == (3, 7)
    assert r.left_offset == 18.0 and r.right_offset == 18.0


def test_quote_dropcap_wrap_vetoed(tmp_path):
    # BoK shape: a wide 32pt initial pushes its wrap lines to a 36pt inset
    # justified to the body right -- the SAME shape as the book's left-only
    # quotes. The wrap lines (starting AT the letter's right edge) must not
    # classify; the real quote further down the page must.
    lines = [
        _line("K", 95, x0=72, width=36, font=BIG),
        _line("now that the wrap line beside the initial runs", 100,
              x0=108, width=254),
        _line("to the full body measure just like a real quote", 113,
              x0=108, width=254.4),
        _line("and continues at the column edge like ordinary prose", 126,
              x0=72, width=290),
        _line("before the paragraph closes somewhat short.", 139,
              x0=72, width=200),
        _line("A real left-inset quotation starts well below the", 165,
              x0=108, width=254),
        _line("initial and reaches the very same justified margin", 178,
              x0=108, width=254.4),
        _line("before ending early.", 191, x0=108, width=120),
        _line("Prose resumes at the full measure and anchors the", 211,
              x0=72, width=290),
        _line("modal column with another full-measure line here.", 224,
              x0=72, width=290),
    ]
    cfg = _quote_cfg(tmp_path, [1], left=36.0, right=0.0)
    res = build_flow(_doc([_page(1, lines)]), cfg, say=lambda *a: None)
    quoted = [p for p in _paras(res.flow) if p.block_class == "quote"]
    assert len(quoted) == 1
    assert quoted[0].text().startswith("A real left-inset")
    # the dropcap paragraph (letter + wraps + continuation) stays prose
    drop = [p for p in _paras(res.flow) if "wrap line beside" in p.text()]
    assert all(p.block_class is None for p in drop)


def test_quote_full_page_carried_anchors(tmp_path):
    # BoK p.260 shape: a mid-quotation page that is almost ALL quote lines
    # has no body-left cluster of its own -- its apparent body left IS the
    # quote target. The carried anchors from the previous spec page classify
    # it; the quote paragraph spans the page seam as ONE p.bq.
    p1 = _page(1, [
        _line("Anchor prose at full measure holds the column edge", 48,
              x0=72, width=290),
        _line("and a second full-measure line anchors the right,", 61,
              x0=72, width=290),
        _line("introducing the quotation and ending a bit short.", 74,
              x0=72, width=200),
        _line("Hearts are vessels and the best of them contain a", 94,
              x0=108, width=254),
        _line("great deal, so people are of three distinct kinds", 107,
              x0=108, width=254.4),
    ])
    p2 = _page(2, [
        _line("those learned in the affairs of their Lord, those", 87,
              x0=108, width=254),
        _line("who seek knowledge along the path of salvation and", 100,
              x0=108, width=254.4),
        _line("the common folk that follow after every brayer.", 113,
              x0=108, width=200),
    ])
    cfg = _quote_cfg(tmp_path, [1, 2], left=36.0, right=0.0)
    res = build_flow(_doc([p1, p2]), cfg, say=lambda *a: None)
    quoted = [p for p in _paras(res.flow) if p.block_class == "quote"]
    assert len(quoted) == 1
    assert quoted[0].text().startswith("Hearts are vessels")
    assert quoted[0].text().endswith("every brayer.")
    assert res.counts.get("quote-lines") == 5


# ---------------------------------------------------------------- blocks.lists

def _list_cfg(tmp_path, pages, marker="decimal", hang=27.0, **kw):
    from pdf2epub.config import ListSpec
    return _cfg(tmp_path, blocks_lists=[ListSpec(
        pages=pages, marker=marker, hang=hang,
        note="test lists")], **kw)


def _mr_notes_lines():
    # M&R notes-apparatus shape (p.340): entries "43.<lemma>" at the body
    # left, hang turnovers 27pt deeper, sub-lemma paragraphs at 36pt with
    # their own first-line indent. The shipped damage: turnovers SPLIT from
    # their entry (the indent-break fires: prev line sits at the column
    # edge), and a note ending on a FULL turnover FUSES with the next entry.
    return [
        _line("43.Necessary in existence by His Essence. Shaykh M", 90,
              x0=72, width=285),
        _line("is represented as criticizing this expression, and", 103,
              x0=99, width=258),
        _line("proves of it.", 116, x0=99, width=60),
        _line("45.He does not know. This is a philosophical claim", 129,
              x0=72, width=285),
        _line("position criticized by both theologians and Sufis.", 142,
              x0=99, width=200),
        _line("Those people destroy the souls. For some remarks", 155,
              x0=108, width=249),
        _line("on false teachers, see SPL 145-47 and elsewhere.", 168,
              x0=99, width=230),
        _line("47.He's reading his own page. See the note on 1.37", 181,
              x0=72, width=250),
    ]


def test_list_apparatus_heals_splits_and_fusions(tmp_path):
    res = build_flow(_doc([_page(1, _mr_notes_lines())]),
                     _list_cfg(tmp_path, [1]), say=lambda *a: None)
    paras = _paras(res.flow)
    items = [p for p in paras if p.block_class == "list"]
    entries = [p for p in items if p.list_entry]
    # three notes; the hang turnover after entry 43 JOINED (no first-line
    # split), and entry 45's FULL second line did not fuse into the
    # sub-lemma or the next entry
    assert len(entries) == 3
    assert entries[0].text().startswith("43.Necessary")
    assert "criticizing this expression" in entries[0].text()
    assert "proves of it." in entries[0].text()
    assert entries[1].text().startswith("45.He does not know")
    assert entries[2].text().startswith("47.He's reading")
    # the sub-lemma is its own paragraph INSIDE the item (list, not entry)
    sub = [p for p in items if not p.list_entry]
    assert len(sub) == 1 and sub[0].text().startswith("Those people")
    assert res.counts.get("list-items") == 3
    assert res.counts.get("list-paras") == 4


def test_list_fusion_healed_after_full_width_note_end(tmp_path):
    # a note whose LAST turnover runs full-measure fused into the next
    # entry in the shipped M&R (nothing told the joiner to break); the
    # marker line now always opens its own item
    lines = [
        _line("148. The tale-bearer is God. There is an allusion", 90,
              x0=72, width=285),
        _line("in Koran 66:3 and this line runs the full measure x", 103,
              x0=99, width=258),
        _line("149. Companion of the heart. A standard expression", 116,
              x0=72, width=285),
        _line("who lives in the awareness of God, a true dervish.", 129,
              x0=99, width=200),
    ]
    res = build_flow(_doc([_page(1, lines)]), _list_cfg(tmp_path, [1]),
                     say=lambda *a: None)
    entries = [p for p in _paras(res.flow)
               if p.block_class == "list" and p.list_entry]
    assert len(entries) == 2
    assert entries[0].text().endswith("full measure x")
    assert entries[1].text().startswith("149. Companion")
    # decimal numbering increased: no gap warning
    assert res.counts.get("list-marker-gap", 0) == 0


def test_list_cross_page_item_and_hang_only_page(tmp_path):
    # a long note spans the page turn onto a page that is ONLY turnovers
    # (no entry, no body-left line): carried anchors + carried_open classify
    # it and the item continues as one paragraph
    p1 = _page(1, [
        _line("151. God is greater. Compare passages 2.104, 105.", 77,
              x0=72, width=224),
        _line("152. Lote Tree of the Far Boundary. A tree growing", 90,
              x0=72, width=285),
        _line("most limit of paradise from which the Prophet had x", 103,
              x0=99, width=258),
    ])
    p2 = _page(2, [
        _line("a vision of God during his miraj according to the", 87,
              x0=99, width=258),
        _line("commentators (Koran 53:14) and much more besides.", 100,
              x0=99, width=200),
    ])
    res = build_flow(_doc([p1, p2]), _list_cfg(tmp_path, [1, 2]),
                     say=lambda *a: None)
    items = [p for p in _paras(res.flow) if p.block_class == "list"]
    assert len(items) == 2 and all(p.list_entry for p in items)
    assert items[1].text().startswith("152. Lote Tree")
    assert items[1].text().endswith("much more besides.")
    assert res.counts.get("list-lines") == 5


def test_list_negative_cells(tmp_path):
    # a body paragraph OUTDENTED below the entry stop ends the item span;
    # a wrapped line opening with a year at the hang column after it stays
    # prose (it is neither at the entry stop nor inside an open item)
    lines = [
        _line("Body prose at the full measure anchors the column", 61,
              x0=72, width=285),
        _line("and introduces the little list with a colon here:", 74,
              x0=72, width=280),
        _line("1. Real item at the entry stop starts the list ok", 94,
              x0=103.5, width=200),
        _line("2. Second real item keeps the spec from going bad", 107,
              x0=103.5, width=202),
        _line("The bibliography discusses the year and then wraps", 127,
              x0=72, width=285),
        _line("1983. The year opens this WRAPPED line and must x", 140,
              x0=126, width=200),
    ]
    res = build_flow(_doc([_page(1, lines)]),
                     _list_cfg(tmp_path, [1], hang=22.5),
                     say=lambda *a: None)
    paras = _paras(res.flow)
    entries = [p for p in paras if p.block_class == "list" and p.list_entry]
    assert len(entries) == 2
    biblio = [p for p in paras if "bibliography" in p.text()]
    assert biblio and biblio[0].block_class is None
    year = [p for p in paras if "1983. The year" in p.text()]
    assert year and year[0].block_class is None  # prose, never an item


def test_list_marker_gap_warns_on_decrease(tmp_path):
    lines = [
        _line("7. Seventh note of the chapter ends here quickly.", 90,
              x0=72, width=270),
        _line("1. Numbering restarts for the next chapter's notes", 103,
              x0=72, width=280),
    ]
    res = build_flow(_doc([_page(1, lines)]), _list_cfg(tmp_path, [1]),
                     say=lambda *a: None)
    assert res.counts.get("list-marker-gap") == 1
    assert any(getattr(w, "code", "") == "list-marker-gap"
               for w in res.warns)


def test_list_stale_spec_fails_build(tmp_path):
    lines = [_line("Ordinary full-measure prose only on this page and", 90,
                   x0=72, width=285),
             _line("nothing that looks like a marker list at all here.", 103,
                   x0=72, width=285)]
    with pytest.raises(SystemExit, match="stale blocks.lists"):
        build_flow(_doc([_page(1, lines)]), _list_cfg(tmp_path, [1]),
                   say=lambda *a: None)


def test_emit_list_group_ol_li_structure(tmp_path):
    from pdf2epub.core.emit_xhtml import Emitter

    res = build_flow(_doc([_page(1, _mr_notes_lines())]),
                     _list_cfg(tmp_path, [1]), say=lambda *a: None)
    out = Emitter(_list_cfg(tmp_path, [1]), res.flow,
                  say=lambda m: None).emit()
    body = "".join(part for f in out.files for part in f.body_parts)
    assert body.count('<ol class="plist">') == 1
    assert body.count('<li class="li1">') == 3
    assert body.count('<p class="lp">') == 3   # one per entry paragraph
    assert body.count('<p class="lp lpc') == 1  # the sub-lemma
    # the sub-lemma paragraph sits INSIDE note 45's li
    li45 = body.split('<li class="li1">')[2]
    assert "Those people destroy" in li45
    assert "43.Necessary" in body and "</ol>" in body


def test_emit_list_bullet_ul_and_anchor_span(tmp_path):
    from pdf2epub.core.emit_xhtml import Emitter

    p1 = _page(1, [
        _line("Intro prose at full measure introduces the listing", 74,
              x0=72, width=290),
        _line("and ends short:", 87, x0=72, width=90),
        _line("• First bullet item of the run ends this page x", 107,
              x0=90, width=230),
    ])
    p2 = _page(2, [
        _line("• Second bullet item opens the following page ok", 87,
              x0=90, width=240),
        _line("Prose resumes at the full measure after the listing", 107,
              x0=72, width=290),
        _line("and anchors the modal column with one more line xx.", 120,
              x0=72, width=290),
    ])
    cfg = _list_cfg(tmp_path, [1, 2], marker="bullet", hang=0.0)
    res = build_flow(_doc([p1, p2]), cfg, say=lambda m: None)
    out = Emitter(cfg, res.flow, say=lambda m: None).emit()
    body = "".join(part for f in out.files for part in f.body_parts)
    assert body.count('<ul class="plist">') == 1
    assert body.count('<li class="li1">') == 2
    ul = body[body.index('<ul class="plist">'):]
    ul = ul[:ul.index("</ul>")]
    assert 'aria-label="2"' in ul       # the page anchor span sits in a li
    assert "<div" not in ul             # never a div child inside the list
    assert "Prose resumes" not in ul


def test_list_paragraph_roundtrip():
    from pdf2epub.core.model import (Paragraph, RunFormat, SourceRef,
                                     TextRun, _paragraph_from_dict)
    from dataclasses import asdict

    p = Paragraph(style="s", items=[TextRun("1. item", RunFormat())],
                  src=SourceRef("p0001", 0), block_class="list",
                  list_entry=True)
    d = asdict(p)
    q = _paragraph_from_dict(d)
    assert q.block_class == "list" and q.list_entry is True


def test_restore_spaces_apparatus_classes():
    # M&R notes-apparatus prepress classes, print-verified 2026-07-10
    # (renders pp.174/229: semicolons and digit-comma seams ARE spaced in
    # print; every other note number is followed by a space)
    assert restore_spaces("84.O you who died")[0] == "84. O you who died"
    assert restore_spaces("38.I’ve never seen")[0] == \
        "38. I’ve never seen"
    assert restore_spaces("M II 2218-51;Attar gives")[0] == \
        "M II 2218-51; Attar gives"
    assert restore_spaces("is manyness;it is for")[0] == \
        "is manyness; it is for"
    assert restore_spaces("to 2.41,Shams is")[0] == "to 2.41, Shams is"
    assert restore_spaces("inheritor. . .”.The word")[0] == \
        "inheritor. . .”. The word"
    # negatives: initials, tight caps, thousands, spaced refs stay
    assert restore_spaces("R.A. Nicholson")[0] == "R.A. Nicholson"
    assert restore_spaces("1,000 dirhems")[0] == "1,000 dirhems"
    # the passage-citation seam normalizes to a spaced citation (round-1
    # _SPACE_BEFORE_PAREN, shipped through three accepted rounds; print
    # is mixed: 'eighteen. (209-10)' spaced, p.35 'dirhems.”(343)' tight)
    assert restore_spaces("dirhems.”(343)")[0] == "dirhems.” (343)"


def test_list_sub_lemma_breaks_after_full_line(tmp_path):
    # a member line DEEPER than the hang column is a first-line indent
    # WITHIN the item — it breaks even after a FULL-width line (the shape
    # behind 20+ fused M&R lemma glosses; every one starts its own print
    # line at hang+9)
    lines = [
        _line("47.He's reading his own page. See the note on 1.37", 90,
              x0=72, width=285),
        _line("and this turnover runs the full measure exactly xx", 103,
              x0=99, width=258),
        _line("Those people destroy the souls. For some remarks", 116,
              x0=108, width=249),
        _line("on false teachers, see SPL 145-47 and elsewhere.", 129,
              x0=99, width=230),
        _line("45.Another note keeps the page honest and full.", 142,
              x0=72, width=250),
    ]
    res = build_flow(_doc([_page(1, lines)]), _list_cfg(tmp_path, [1]),
                     say=lambda *a: None)
    items = [p for p in _paras(res.flow) if p.block_class == "list"]
    subs = [p for p in items if not p.list_entry]
    assert len(subs) == 1
    assert subs[0].text().startswith("Those people")
    assert subs[0].text().endswith("elsewhere.")
    entry = [p for p in items if p.list_entry][0]
    assert entry.text().endswith("exactly xx")


def test_list_range_marker_entries(tmp_path):
    # grouped-passage entries ("19-22. I have placed passages 19-22...")
    # are real markers; four-digit years can never match
    lines = [
        _line("18. Five-year old child. The note makes this point", 90,
              x0=72, width=285),
        _line("19-22. I have placed passages 19-22 in an order xx", 103,
              x0=72, width=285),
        _line("that differs from the edited text, as follows now.", 116,
              x0=99, width=200),
    ]
    res = build_flow(_doc([_page(1, lines)]), _list_cfg(tmp_path, [1]),
                     say=lambda *a: None)
    entries = [p for p in _paras(res.flow)
               if p.block_class == "list" and p.list_entry]
    assert len(entries) == 2
    assert entries[1].text().startswith("19-22. I have placed")
    assert entries[1].text().endswith("as follows now.")


def test_dehyphenation_arabic_article_and_compounds():
    # the Arabic article keeps its line-break hyphen when a capitalized or
    # diacritical word precedes it (13 of 14 corpus sites; the shipped BoK
    # carried 'Qut alqulub'-style damage at 12 of them); English syllable
    # breaks still dehyphenate — incl. 'teaching al-/lows' (I&B p.157)
    assert dehyphenate_join("Qūt al-", "qulūb, 1:135")[0] == "Qūt al-"
    assert dehyphenate_join("Mirsad al-", "ibad 92")[0] == "Mirsad al-"
    assert dehyphenate_join("teaching al-", "lows mistreatment")[0] == \
        "teaching al"
    assert dehyphenate_join("wa’t-", "tanbihat)")[0] == "wa’t-"
    assert dehyphenate_join("so “seven-", "colored” means")[0] == \
        "so “seven-"
    assert dehyphenate_join("and just-", "started.”")[0] == "and just-"
    assert dehyphenate_join("the author ad-", "vances an")[0] == \
        "the author ad"
    assert dehyphenate_join("an ar-", "row well steeped")[0] == "an ar"


def test_list_inset_block_interior_joins(tmp_path):
    # note 244's shape: an indented quotation INSIDE the item — inset
    # paragraphs at inset+18 first-line indents, bodies at the inset
    # column. Stepping INTO the inset breaks; interior lines join
    # geometrically (a per-line break shattered the quotation)
    lines = [
        _line("44. Establishing God. Fih 92 gives the anecdote at", 90,
              x0=72, width=250),
        _line("Someone said in the presence of Mawlana Shams ad-", 103,
              x0=126, width=232),
        _line("Din Tabrizi, “I have established God's existence", 116,
              x0=108, width=250),
        _line("with an incontrovertible proof over the night.”", 129,
              x0=108, width=220),
        _line("“Idiot! God is established. His existence needs", 142,
              x0=126, width=232),
        _line("no proof at all.”", 155, x0=108, width=90),
        _line("45. Abu Bakr Siddiq. For a short version see Lings.", 168,
              x0=72, width=270),
    ]
    res = build_flow(_doc([_page(1, lines)]), _list_cfg(tmp_path, [1]),
                     say=lambda *a: None)
    items = [p for p in _paras(res.flow) if p.block_class == "list"]
    texts = [p.text() for p in items]
    assert len(items) == 4
    assert texts[1].startswith("Someone said")
    assert texts[1].endswith("over the night.”")  # interior joined
    assert texts[2].startswith("“Idiot!")
    assert texts[2].endswith("no proof at all.”")
    # cross-boundary hyphen dehyphenated inside the joined paragraph
    assert "Shams ad-Din Tabrizi" in texts[1]


def test_list_hang_breaks_after_short_line(tmp_path):
    # p.341 shape: the entry ends SHORT ('…See SPL 220-26.'), and a flush
    # continuation paragraph opens at the hang column — a genuine
    # paragraph end still breaks even at the hang column
    lines = [
        _line("2.Intellect takes you to the threshold. See SPL 22.", 90,
              x0=72, width=220),
        _line("Intellect is a veil. Compare these lines of Rumi and", 103,
              x0=99, width=258),
        _line("the commentary that follows them in that chapter now", 116,
              x0=99, width=258),
        _line("and ends short.", 129, x0=99, width=80),
        _line("3. Another entry keeps the little page honest here,", 142,
              x0=72, width=285),
        _line("running to the full measure to anchor the column ok.", 155,
              x0=99, width=258),
    ]
    res = build_flow(_doc([_page(1, lines)]), _list_cfg(tmp_path, [1]),
                     say=lambda *a: None)
    items = [p for p in _paras(res.flow) if p.block_class == "list"]
    assert len(items) == 3
    assert items[0].text().endswith("See SPL 22.")
    assert items[1].text().startswith("Intellect is a veil")
    assert items[1].text().endswith("ends short.")  # its turnovers join


def test_verse_cross_page_full_base_line_kept(tmp_path):
    # M&R p.370->371: an accepted couplet ends the page; the SECOND couplet
    # opens the next page with a base line ending only ~7pt short — the
    # boundary-short trim must exempt the page-top continuation
    p1 = _page(1, [
        _line("Prose introduces the poem at full measure width and", 87,
              x0=72, width=290),
        _line("continues to the couplet with a colon here:", 100,
              x0=72, width=200),
        _line("The thirsty man laments, “O sweet water!”", 120,
              x0=81, width=190),
        _line("The water too laments, “Where is the drinker?”", 133,
              x0=108, width=210),
    ])
    p2 = _page(2, [
        _line("This thirst in our souls is the attraction of that w", 87,
              x0=81, width=283),
        _line("we belong to it and it belongs to us.", 100,
              x0=108, width=160),
        _line("Prose resumes after the poem at the full measure and", 120,
              x0=72, width=290),
        _line("runs on to the end of the paragraph as usual now.", 133,
              x0=72, width=290),
    ])
    res = build_flow(_doc([p1, p2]), _verse_cfg(tmp_path, [1, 2]),
                     say=lambda *a: None)
    verse = [p for p in _paras(res.flow) if p.block_class == "verse"]
    # the page-top couplet continues the open stanza (cross-page
    # default): ONE stanza of four verse lines, near-full base kept
    assert len(verse) == 1
    assert verse[0].text().count("\u2028") == 3
    assert "This thirst" in verse[0].text()


def test_restore_spaces_date_comma():
    # 'October 11,1244' — a thousands separator groups exactly three
    # digits, so comma + four digits is always a prepress seam
    assert restore_spaces("On October 11,1244, Shams")[0] == \
        "On October 11, 1244, Shams"
    assert restore_spaces("1,000 dirhems")[0] == "1,000 dirhems"
    assert restore_spaces("10,000 men")[0] == "10,000 men"


def test_list_false_center_lemma_stays_in_item(tmp_path):
    # p.371: a short lemma whose midpoint chances near the column center is
    # mislabeled /center — it must stay a member (the ol split in half),
    # while a genuinely centered divider at an arbitrary x0 still ends the
    # item and breaks the list
    lines = [
        _line("178. This is reversed. Shams explains what he mean", 90,
              x0=72, width=277),
        _line("He killed his mother. Women from Qazvin apparently", 103,
              x0=108, width=250),
        _line("did not have a good reputation in Persian humor ok.", 116,
              x0=99, width=200),
        # x0=108, width ~118 -> midpoint ~217 = column center of [72, 358]
        _line("He sits in front of me like a son. See 3.61.", 129,
              x0=108, width=213),
        _line("180. A sama in the east. Compare passage 1.9 there.", 142,
              x0=72, width=280),
        _line("When he died he was veiled. A reference to Abu Yazid", 155,
              x0=108, width=250),
        _line("who appears in 2.207 and ends the page a bit short.", 168,
              x0=99, width=230),
    ]
    res = build_flow(_doc([_page(1, lines)]), _list_cfg(tmp_path, [1]),
                     say=lambda *a: None)
    from pdf2epub.core.emit_xhtml import Emitter
    out = Emitter(_list_cfg(tmp_path, [1]), res.flow,
                  say=lambda m: None).emit()
    body = "".join(part for f in out.files for part in f.body_parts)
    assert body.count('<ol class="plist">') == 1  # never split in half
    items = [p for p in _paras(res.flow) if p.block_class == "list"]
    lemma = [p for p in items if "He sits in front" in p.text()]
    assert len(lemma) == 1 and not lemma[0].list_entry
    assert "/center" not in lemma[0].style


def test_emit_epigraph_role(tmp_path):
    # Phase E: emission-only epigraph semantics — a role: judgment ships a
    # real <blockquote class="epigraph"> with EPUB SSV + DPUB-ARIA types.
    # No detector exists (zero corpus instances).
    from pdf2epub.core.emit_xhtml import Emitter

    lines = [
        _line("Whoever knows himself knows his Lord, as it is", 90,
              x0=72, width=280),
        _line("related from the Prophet in the famous saying.", 103,
              x0=72, width=250),
        _line("Body prose follows the epigraph at the full measure", 123,
              x0=72, width=290),
        _line("and anchors the modal column with a second line ok.", 136,
              x0=72, width=290),
    ]
    cfg = _cfg(tmp_path)
    res = build_flow(_doc([_page(1, lines)]), cfg, say=lambda m: None)
    paras = _paras(res.flow)
    paras[0].role = "epigraph"
    paras[0].classes = ["Serif-11"]
    out = Emitter(cfg, res.flow, say=lambda m: None).emit()
    body = "".join(part for f in out.files for part in f.body_parts)
    assert ('<blockquote class="epigraph Serif-11" epub:type="epigraph" '
            'role="doc-epigraph"><p>') in body
    assert "knows his Lord" in body
    from pdf2epub.core import emit_css
    assert "blockquote.epigraph" in emit_css._BASE
