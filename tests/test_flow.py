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
    assert restore_spaces('lower,"case stays quoteless,next')[1] == 1  # a-z rule only
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
