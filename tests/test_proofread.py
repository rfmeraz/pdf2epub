"""Proofread packets: rendering, escaping, chunking, lines formatter."""

from types import SimpleNamespace

from lxml import etree

import pdf2epub.proofread as pf
from pdf2epub.proofread import (Block, format_page_lines, render_packet,
                                split_chunks, walk_doc)

_NS = ('xmlns="http://www.w3.org/1999/xhtml" '
       'xmlns:epub="http://www.idpf.org/2007/ops"')


def _doc(href, inner):
    root = etree.fromstring(
        f'<html {_NS}><head/><body>{inner}</body></html>'.encode())
    return SimpleNamespace(href=href, root=root)


def _pb(label):
    return (f'<div id="pg-{label}" class="pagebreak" epub:type="pagebreak" '
            f'aria-label="{label}"></div>')


REF = '<a id="fnref3" class="noteref" href="notes.xhtml#fn3"><sup>3</sup></a>'
BACK = '<a href="b.xhtml#fnref3" class="backlink">↩</a>'


def test_walk_rendering():
    doc = _doc("ch.xhtml", (
        _pb("29")
        + "<h1>Part Two</h1>"
        + "<h3>Conceiving of the One</h3>"
        + f"<p>Say: He, God, is One{REF} and more text follows.</p>"
        + "<blockquote><p>An indented quotation line.</p></blockquote>"
        + '<p class="listpara">First list item</p>'
        + '<p class="caption">Figure one caption</p>'
        + '<p class="titletext">The Half Title</p>'
        + '<p class="toc-entry"><a href="x.xhtml">Chapter One</a></p>'))
    blocks, k = walk_doc(doc, is_notes=False, k_start=5)
    assert k == 6
    assert blocks[0].kind == "pagebreak" and blocks[0].label == "29" \
        and blocks[0].k == 5
    lines = [l for b in blocks[1:] for l in b.lines]
    assert "# Part Two" in lines
    assert "### Conceiving of the One" in lines
    assert any("One[3] and more text" in l for l in lines)   # ref + tail
    assert "> An indented quotation line." in lines
    assert "- First list item" in lines
    assert "{caption} Figure one caption" in lines
    assert "{titlepage} The Half Title" in lines
    assert "{toc} Chapter One" in lines


def test_escaping_and_wrap():
    doc = _doc("a.xhtml",
               "<p># not a heading, just book text that starts with a hash</p>"
               "<p>&gt; nor a quote line here</p>"
               "<p>" + "word " * 60 + "end.</p>")
    blocks, _ = walk_doc(doc, is_notes=False, k_start=0)
    assert blocks[0].lines[0].startswith("\\# not a heading")
    assert blocks[1].lines[0].startswith("\\> nor a quote")
    long_lines = blocks[2].lines
    assert all(len(l) <= 100 for l in long_lines)
    assert " ".join(long_lines) == "word " * 59 + "word end."


def test_figure_alt_in_packet():
    doc = _doc("f.xhtml",
               '<div class="chinese-page"><img src="image/page-0008.png" '
               'alt="Facsimile letter from the Dalai Lama"/></div>'
               "<p>Text after the plate.</p>")
    blocks, _ = walk_doc(doc, is_notes=False, k_start=0)
    assert blocks[0].lines[0].startswith("{figure} Facsimile letter")
    assert blocks[1].lines == ["Text after the plate."]


def test_backlink_dropped_notes_packet():
    doc = _doc("notes.xhtml",
               f'<ol class="notes"><li id="fn1"><p>First note text {BACK}'
               "</p></li><li><p>Second note.</p></li></ol>")
    blocks, _ = walk_doc(doc, is_notes=True, k_start=0)
    assert blocks[0].lines[0] == "{note 1} First note text"
    assert blocks[1].lines[0] == "{note 2} Second note."


def test_split_and_context_fences(monkeypatch):
    monkeypatch.setattr(pf, "SPLIT_OVER", 20)
    monkeypatch.setattr(pf, "CHUNK_TARGET", 15)
    blocks = [Block(kind="block", lines=[f"para {i} " + "w " * 9],
                    words=10) for i in range(6)]
    chunks = split_chunks(blocks)
    assert len(chunks) == 3 and sum(len(c) for c in chunks) == 6
    assert all(sum(b.words for b in c) == 20 for c in chunks)  # balanced
    header = {"packet": "002", "file": "packets/002-x-b.md",
              "spine": "x.xhtml (chunk 2 of 4)", "pages": "none",
              "words": 20, "protocol": "../PROTOCOL.md"}
    text = render_packet(chunks[1], header, chunks[0][-2:], chunks[2][:2])
    assert text.count(pf.CONTEXT_OPEN) == 2
    assert text.count(pf.CONTEXT_CLOSE) == 2
    assert text.startswith("---\npacket: 002\n")
    # context blocks sit inside the fences
    head, mid = text.split(pf.CONTEXT_CLOSE, 1)
    assert "para 0" in head or "para 1" in head


def test_pagebreak_marker_own_paragraph():
    doc = _doc("a.xhtml", "<p>Before.</p>" + _pb("xii") + "<p>After.</p>")
    blocks, _ = walk_doc(doc, is_notes=False, k_start=0)
    header = {"packet": "001", "file": "packets/001-a.md", "spine": "a.xhtml",
              "pages": "xii-xii", "words": 2, "protocol": "../PROTOCOL.md"}
    text = render_packet(blocks, header, [], [])
    assert "\nBefore.\n\n{p.xii}\n\nAfter.\n" in text


def test_walk_deterministic():
    inner = _pb("1") + "<p>Same content every time.</p><h2>Head</h2>"
    a1, _ = walk_doc(_doc("a.xhtml", inner), is_notes=False, k_start=0)
    a2, _ = walk_doc(_doc("a.xhtml", inner), is_notes=False, k_start=0)
    assert [(b.kind, b.lines, b.words, b.label) for b in a1] == \
        [(b.kind, b.lines, b.words, b.label) for b in a2]


def test_format_page_lines():
    from pdf2epub.analyze import ColumnGeometry
    from pdf2epub.pdfmodel import PdfDoc, PdfFont, PdfLine, PdfPage, PdfRun

    fonts = {0: PdfFont(0, "Serif", "AA+Serif", 11.0, "#000"),
             1: PdfFont(1, "Serif", "AA+Serif", 6.5, "#000")}
    lines = [
        PdfLine(runs=[PdfRun(text="Body line with control\x03char here",
                             font_id=0, x0=72, y0=100, x1=362, y1=112)],
                x0=72, y0=100, x1=362, y1=112),
        PdfLine(runs=[PdfRun(text="7", font_id=1, superscript=True,
                             x0=90, y0=98, x1=95, y1=104)],
                x0=90, y0=98, x1=95, y1=104),
    ]
    doc = PdfDoc(pdf_path="x", sha256="s", producer="p", n_pages=1,
                 pages=[PdfPage(number=1, label="ix", width=431, height=648,
                                trim=(0, 0, 431, 648), lines=lines)],
                 fonts=fonts)
    geo = ColumnGeometry(72.0, 362.0, body_size=11.0)
    out = format_page_lines(doc, geo, 1)
    assert out[0].startswith("page 1 label 'ix' trim 431x648pt")
    assert out[2].startswith("   0   72.0  362.0")
    assert "control·char" in out[2]
    assert out[3].endswith("[sup]")
