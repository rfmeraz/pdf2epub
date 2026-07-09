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
    pages = [_page(1, [_line("Page one text content here", 100)]),
             _page(2, [_line("Page two text content here", 100)])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    anchors = [b for b in res.flow.blocks if isinstance(b, PageAnchor)]
    assert [a.ordinal for a in anchors] == [1, 2]


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


def test_textfix_functions():
    assert expand_ligatures("ﬁnal ﬂow")[0] == "final flow"
    t, n = restore_spaces('say,"If I went.Then')
    assert t == 'say, "If I went. Then' and n == 2
    t, n = restore_spaces("W.M. Watt and op.cit. stay")
    assert n == 0
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
