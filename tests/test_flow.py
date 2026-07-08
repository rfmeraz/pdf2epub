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


def test_anchor_per_page_monotone(tmp_path):
    pages = [_page(1, [_line("Page one text content here", 100)]),
             _page(2, [_line("Page two text content here", 100)])]
    res = build_flow(_doc(pages), _cfg(tmp_path), say=lambda m: None)
    anchors = [b for b in res.flow.blocks if isinstance(b, PageAnchor)]
    assert [a.ordinal for a in anchors] == [1, 2]


def test_textfix_functions():
    assert expand_ligatures("ﬁnal ﬂow")[0] == "final flow"
    t, n = restore_spaces('say,"If I went.Then')
    assert t == 'say, "If I went. Then' and n == 2
    t, n = restore_spaces("W.M. Watt and op.cit. stay")
    assert n == 0
    assert dehyphenate_join("tradi-", "tion") == ("tradi", "", True)
    assert dehyphenate_join("Kaccayanagotta-", "Sutta") == ("Kaccayanagotta-", "", False)
    assert dehyphenate_join("plain", "next") == ("plain", " ", False)
