"""Typography QA: anchor slicer, centering witness, gates 13-17 checks."""

from types import SimpleNamespace

from lxml import etree

from pdf2epub.analyze import ColumnGeometry
from pdf2epub.core.qa_cssresolve import parse_stylesheet
from pdf2epub.core.qa_pageslice import EpubBlock, slice_pages
from pdf2epub.pdfmodel import PdfDoc, PdfFont, PdfLine, PdfPage, PdfRun
from pdf2epub.qa.typography import (PdfParaGeo, check_emphasis,
                                    check_heading_census,
                                    check_signature_diff,
                                    check_size_fidelity, genuinely_centered,
                                    left_stops)

_NS = ('xmlns="http://www.w3.org/1999/xhtml" '
       'xmlns:epub="http://www.idpf.org/2007/ops"')


def _doc(href, inner):
    root = etree.fromstring(
        f'<html {_NS}><head/><body>{inner}</body></html>'.encode())
    return SimpleNamespace(href=href, root=root)


def _pb(label):
    return (f'<div id="pg-{label}" class="pagebreak" epub:type="pagebreak" '
            f'aria-label="{label}"></div>')


def test_slicer_pages_and_blockquote():
    docs = [_doc("001-a.xhtml",
                 '<p class="titletext">Half title</p>'      # before 1st anchor
                 + _pb("1")
                 + '<p class="Serif-11">Page one body.</p>'
                 + '<blockquote><p class="Serif-10">Quoted.</p></blockquote>'
                 + _pb("2")
                 + '<h2 class="Serif-14-center">Head</h2>'),
            _doc("002-b.xhtml",
                 _pb("3") + '<p class="Serif-11">Page three.</p>')]
    res = slice_pages(docs, [1, 2, 3], {1: "1", 2: "2", 3: "3"})
    assert res.ok
    assert [b.text for b in res.preamble] == ["Half title"]
    assert [b.tag for b in res.slices[1]] == ["p", "p"]
    assert res.slices[1][1].in_blockquote
    assert [b.tag for b in res.slices[2]] == ["h2"]
    assert res.slices[3][0].href == "002-b.xhtml"


def test_slicer_census():
    docs = [_doc("a.xhtml", _pb("1") + (
        '<p>Plain <i>ital tail</i> after <b>bold</b> '
        '<sup>9</sup><span class="smallcaps">Cap</span> '
        '<span lang="ar" xml:lang="ar">reading</span> end.</p>'))]
    res = slice_pages(docs, [1], {1: "1"})
    blk = res.slices[1][0]
    assert blk.italic_letters == len("italtail")
    assert blk.bold_letters == len("bold")
    assert blk.sc_letters == len("Cap")
    assert blk.lang_span_letters == len("reading")
    # sup and lang excluded from plain letters
    assert blk.letters == sum(1 for c in "Plain ital tail after bold Cap end"
                              if c.isalpha())


def _pb_inline(label):
    return (f'<span id="pg-{label}" class="pagebreak" epub:type="pagebreak" '
            f'role="doc-pagebreak" aria-label="{label}"></span>')


def test_slicer_inline_pagebreak_attribution():
    # a mid-paragraph pagebreak span: the enclosing paragraph belongs to the
    # page it STARTS on; everything after it belongs to the new page — the
    # same partition the old deferred block div produced
    docs = [_doc("a.xhtml",
                 _pb("1")
                 + f'<p>started on one{_pb_inline("2")} finished on two.</p>'
                 + '<p>page two proper.</p>')]
    res = slice_pages(docs, [1, 2], {1: "1", 2: "2"})
    assert res.ok
    assert [b.text for b in res.slices[1]] == ["started on one finished on two."]
    assert [b.text for b in res.slices[2]] == ["page two proper."]


def test_slicer_inline_equals_block_partition():
    # regression-matrix equivalence in miniature: old-style (div after the
    # straddling paragraph) and new-style (span inside it) slice identically
    old = [_doc("a.xhtml",
                _pb("1") + '<p>started on one finished on two.</p>'
                + _pb("2") + '<p>page two proper.</p>')]
    new = [_doc("a.xhtml",
                _pb("1")
                + f'<p>started on one{_pb_inline("2")} finished on two.</p>'
                + '<p>page two proper.</p>')]
    r_old = slice_pages(old, [1, 2], {1: "1", 2: "2"})
    r_new = slice_pages(new, [1, 2], {1: "1", 2: "2"})
    assert r_old.ok and r_new.ok
    for page in (1, 2):
        assert [b.text for b in r_old.slices[page]] == \
            [b.text for b in r_new.slices[page]]


def test_slicer_anchor_mismatch_failsafe():
    docs = [_doc("a.xhtml", _pb("1") + "<p>x</p>")]
    res = slice_pages(docs, [1, 2], {1: "1", 2: "2"})
    assert not res.ok and "1 pagebreak anchors vs 2" in res.detail
    # a single label drift is tolerated (fail-safe only at >=3)
    res2 = slice_pages(docs, [1], {1: "iv"})
    assert res2.ok


# ---------------------------------------------------------------- PDF side
# column: [72, 362], width 290, center 217, body 11pt (mirrors test_flow)

BODY, SMALL, BIG, SC = 0, 1, 2, 3
FONTS = {
    BODY: PdfFont(BODY, "Serif", "AA+Serif", 11.0, "#000000"),
    SMALL: PdfFont(SMALL, "Serif", "AA+Serif", 9.0, "#000000"),
    BIG: PdfFont(BIG, "Serif", "AA+Serif", 30.0, "#000000"),
    SC: PdfFont(SC, "Caps", "AA+Caps", 11.0, "#000000"),
}
GEO = ColumnGeometry(72.0, 362.0, body_size=11.0)


def _line(text, y=100.0, x0=72.0, font=BODY, width=290.0):
    x1 = x0 + width
    return PdfLine(runs=[PdfRun(text=text, font_id=font,
                                x0=x0, y0=y, x1=x1, y1=y + 12)],
                   x0=x0, y0=y, x1=x1, y1=y + 12)


def _pdoc(pages):
    return PdfDoc(pdf_path="x.pdf", sha256="s", producer="t",
                  n_pages=len(pages), pages=pages, fonts=dict(FONTS))


def _ppage(number, lines):
    return PdfPage(number=number, label=str(number), width=431.0, height=648.0,
                   trim=(0.0, 0.0, 431.0, 648.0), lines=lines,
                   n_chars=sum(len(l.text()) for l in lines))


def test_left_stops_from_full_right_lines():
    # col_left and the +14pt paragraph indent are attested by full lines;
    # a repeated CENTERED head x0 never becomes a stop (not full-right)
    lines = []
    for i in range(4):
        lines.append(_line("full body line at the column left edge", y=100 + i * 13))
        lines.append(_line("indented first line of a paragraph runs on",
                           y=200 + i * 13, x0=86.0, width=276.0))
        lines.append(_line("REPEATED HEAD", y=300 + i * 13, x0=160.0, width=114.0))
    doc = _pdoc([_ppage(1, lines)])
    stops = left_stops(doc, GEO, [1])
    assert 72.0 in stops and 86.0 in stops
    assert 160.0 not in stops


def _stops():
    return (72.0, 86.0)


def test_witness_bok206_replica():
    # single body-size line starting at the paragraph indent whose midpoint
    # happens to land near center: NOT genuinely centered; reason names the stop
    ln = _line("This should suffice as accidental centering", x0=86.0, width=262.0)
    ok, why = genuinely_centered([(ln, None)], _pdoc([_ppage(1, [ln])]), GEO,
                                 _stops(), "Serif")
    assert not ok and "stop" in why


def test_witness_justified_block_last_line():
    # BoK p.185/p.193 shape: quote-indent / drop-cap-wrap last line whose
    # midpoint lands near center; the FULL previous line at the same x0
    # proves it's a paragraph line — refuted even though insets pass
    doc = _pdoc([_ppage(1, [])])
    prev = _line("and responsibilities are numerous; their varying",
                 y=100.0, x0=122.0, width=240.0)
    ln = _line("may be categorized under ten headings:",
               y=113.5, x0=122.0, width=174.0)   # mid=209, insets 50/66
    ok, why = genuinely_centered([(ln, prev)], doc, GEO, _stops(), "Serif")
    assert not ok and "justified block" in why
    # same line WITHOUT a full-right predecessor (stacked centered lines):
    # the veto stays out and the deep-inset path decides
    short_prev = _line("a short centered line", y=100.0, x0=140.0, width=154.0)
    ok, _ = genuinely_centered([(ln, short_prev)], doc, GEO, _stops(), "Serif")
    assert ok


def test_witness_accepts_genuine_cases():
    doc = _pdoc([_ppage(1, [])])
    # deep-inset single body line, off any stop (superset of line_pstyle rule)
    ln = _line("a genuinely centered epigraph", x0=107.0, width=220.0)
    assert genuinely_centered([(ln, None)], doc, GEO, _stops(), "Serif")[0]
    # display-size wide head: midpoint alone decides
    big = _line("CHAPTER HEAD WIDE", x0=80.0, width=274.0, font=BIG)
    assert genuinely_centered([(big, None)], doc, GEO, _stops(), "Serif")[0]
    # multi-line body block: varying widths, agreeing midpoints
    l1 = _line("longer centered line of a poem", x0=87.0, width=260.0)
    l2 = _line("short centered line", x0=97.0, width=240.0)
    assert genuinely_centered([(l1, None), (l2, l1)], doc, GEO, _stops(),
                              "Serif")[0]
    # full-width lines are neutral -> claim stands
    full = _line("a completely full width body line", x0=72.0, width=290.0)
    ok, why = genuinely_centered([(full, None)], doc, GEO, _stops(), "Serif")
    assert ok and "indistinguishable" in why


def test_witness_rejects_shallow_and_offcenter():
    doc = _pdoc([_ppage(1, [])])
    # shallow inset, not at a stop
    ln = _line("slightly indented ragged line", x0=95.0, width=244.0)
    ok, why = genuinely_centered([(ln, None)], doc, GEO, _stops(), "Serif")
    assert not ok and "inset" in why
    # off-center display line
    big = _line("HEAD", x0=72.0, width=100.0, font=BIG)
    ok, why = genuinely_centered([(big, None)], doc, GEO, _stops(), "Serif")
    assert not ok and "mid offset" in why


def test_line_pstyle_justified_block_veto():
    from pdf2epub.analyze import line_pstyle

    doc = _pdoc([_ppage(1, [])])
    prev = _line("full quote line reaching the right margin here",
                 y=100.0, x0=108.0, width=254.0)
    last = _line("be the first of your people to rise.", y=113.5,
                 x0=108.0, width=212.0)          # mid=214: false-center shape
    assert line_pstyle(last, doc, GEO, prev) == "Serif@11"
    assert line_pstyle(last, doc, GEO, None) == "Serif@11/center"
    # display-size lines keep the lenient rule even after a full line
    big = _line("WIDE HEAD", y=113.5, x0=130.0, width=174.0, font=BIG)
    assert line_pstyle(big, doc, GEO, prev).endswith("/center")


# ---------------------------------------------------------------- gate 13

RULES = parse_stylesheet("""
p { margin: 0; text-indent: 1.2em; text-align: justify; }
h1, h2, h3 { text-align: center; }
blockquote p { text-indent: 0; }
p.caption { text-indent: 0; text-align: center; font-size: 0.9em; }
.Serif-9 { font-size: 0.818em; }
.Serif-30 { font-size: 2.727em; }
.Serif-11-center { text-align: center; text-indent: 0; }
.Serif-Italic-11 { font-style: italic; }
""")


def _blk(tag="p", classes=(), text="text", letters=0, italic=0, bold=0, sc=0,
         in_bq=False):
    return EpubBlock(tag=tag, classes=tuple(classes), in_blockquote=in_bq,
                     text=text, letters=letters, italic_letters=italic,
                     bold_letters=bold, sc_letters=sc)


def test_size_fidelity_missing_rule_fires():
    doc = _pdoc([_ppage(1, [])])
    # class Serif-30 has a rule (2.727em) -> silent; Serif-9 ok; a block whose
    # class SHOULD carry 2.727em but resolves 1.0 (rule missing) fires
    rules = parse_stylesheet("p { text-align: justify; }\n"
                             ".Serif-9 { font-size: 0.818em; }")
    slices = {1: [_blk(classes=("Serif-30",), text="giant text as body"),
                  _blk(classes=("Serif-9",), text="footnote sized")]}
    ok, summary, findings = check_size_fidelity(slices, [], rules, doc, 11.0)
    assert not ok and len(findings) == 1
    assert "Serif-30" in findings[0] and "2.727em" in findings[0]


def test_size_fidelity_caption_override_and_collision():
    doc = _pdoc([_ppage(1, [])])
    doc.fonts[10] = PdfFont(10, "Foo", "AA+Foo", 10.5, "#000000")
    doc.fonts[11] = PdfFont(11, "Foo-10", "AA+Foo-10", 5.0, "#000000")
    slices = {1: [
        _blk(classes=("Serif-9", "caption"), text="a designed caption"),
        _blk(classes=("Foo-10-5",), text="collided class block"),
    ]}
    ok, summary, findings = check_size_fidelity(slices, [], RULES, doc, 11.0)
    assert ok and not findings          # caption skipped, collision skipped
    assert "1 on collided classes" in summary


def test_size_fidelity_suppressed_rule_near_body_silent():
    # 11.1pt cluster: CSS suppresses the rule (|size-body| <= 0.2pt) and the
    # block resolves 1.0em == expected 1.009 within tolerance
    doc = _pdoc([_ppage(1, [])])
    doc.fonts[12] = PdfFont(12, "Serif", "AA+Serif", 11.1, "#000000")
    slices = {1: [_blk(classes=("Serif-11-1",), text="body text")]}
    ok, _, findings = check_size_fidelity(slices, [], RULES, doc, 11.0)
    assert ok and not findings


# ---------------------------------------------------------------- gate 15

def test_emphasis_lost_italics_fires():
    paras = [PdfParaGeo(start_page=1, role="p", style="Serif@11", lines=[],
                        letters=200, italic_letters=200, text="x")]
    slices = {1: [_blk(text="plain now", letters=200, italic=0)]}
    ok, summary, findings = check_emphasis(slices, paras, RULES, [1])
    assert not ok and findings and "italic" in findings[0]


def test_emphasis_css_italic_block_counts():
    paras = [PdfParaGeo(start_page=1, role="p", style="Serif-Italic@11",
                        lines=[], letters=200, italic_letters=200, text="x")]
    slices = {1: [_blk(classes=("Serif-Italic-11",), text="italic para",
                       letters=200, italic=0)]}
    ok, _, findings = check_emphasis(slices, paras, RULES, [1])
    assert ok and not findings


# ---------------------------------------------------------------- gate 16

def test_census_body_face_h3_fires_sc_and_toc_silent():
    line_a = _line("A subsection head set in body type", x0=72.0, width=200.0)
    line_b = PdfLine(runs=[PdfRun(text="TRUE SMALLCAPS HEAD", font_id=SC,
                                  x0=140, y0=120, x1=290, y1=132)],
                     x0=140, y0=120, x1=290, y1=132)
    line_c = _line("Acknowledgements", x0=72.0, width=130.0)
    doc = _pdoc([_ppage(1, [line_a, line_b, line_c])])
    slices = {1: [
        _blk(tag="h3", classes=("Serif-11",), text="A subsection head set in body type"),
        _blk(tag="h3", classes=("Caps-11",), text="TRUE SMALLCAPS HEAD"),
        _blk(tag="h3", classes=("Serif-11",), text="Acknowledgements"),
    ]}
    ok, summary, findings = check_heading_census(
        slices, doc, GEO, "Serif", {"Caps"}, ["Acknowledgements"], set(), {},
        [], 11.0, {})
    assert not ok
    assert len(findings) == 1 and "subsection head" in findings[0]


def test_census_fused_heading():
    doc = _pdoc([_ppage(1, [])])
    titles = ["Oneness: The Highest Common Denominator", "Foreword"]
    mk = lambda text: {1: [_blk(tag="h1", classes=("Serif-14-center",),
                                text=text)]}
    # part label fused into the title: gates (lands in audit)
    ok, summary, lines = check_heading_census(
        mk("Part Two Oneness: The Highest Common Denominator"), doc, GEO,
        "Serif", set(), titles, {1}, {}, [], 11.0, {})
    assert not ok and any("fused with part label" in l for l in lines)
    # heading exactly equal to the title: silent
    ok, _, _ = check_heading_census(
        mk("Oneness: The Highest Common Denominator"), doc, GEO,
        "Serif", set(), titles, {1}, {}, [], 11.0, {})
    assert ok
    # trailing extension ('Foreword by X') never matches endswith: silent
    ok, _, _ = check_heading_census(
        mk("Foreword by Professor Kamali"), doc, GEO,
        "Serif", set(), titles, {1}, {}, [], 11.0, {})
    assert ok
    # short folded title (<8 chars, 'Index') is never a fusion base: silent
    ok, _, _ = check_heading_census(
        mk("Part Two Index"), doc, GEO, "Serif", set(),
        ["Oneness: The Highest Common Denominator", "Index"], {1}, {},
        [], 11.0, {})
    assert ok
    # non-part-label lead: informational only, does not gate
    ok, _, lines = check_heading_census(
        mk("Amazing Oneness: The Highest Common Denominator"), doc, GEO,
        "Serif", set(), titles, {1}, {}, [], 11.0, {})
    assert ok and any("extends a TOC title" in l for l in lines)
    # I&B shape: the TOC itself writes 'Part Two — Title' (folds EQUAL), the
    # heading glues label to title with no separator: fires
    dash_titles = ["Part Two — Oneness: The Highest Common Denominator"]
    ok, _, lines = check_heading_census(
        mk("Part Two Oneness: The Highest Common Denominator"), doc, GEO,
        "Serif", set(), dash_titles, {1}, {}, [], 11.0, {})
    assert not ok and any("without separator" in l for l in lines)
    # separator present in the heading too: silent
    ok, _, _ = check_heading_census(
        mk("Part Two — Oneness: The Highest Common Denominator"), doc, GEO,
        "Serif", set(), dash_titles, {1}, {}, [], 11.0, {})
    assert ok


def test_census_h3_sentence_audit():
    doc = _pdoc([_ppage(1, [])])
    long_sent = "This should suffice for whoever has understanding and truth."
    assert len(long_sent) > 55
    short = "A fine short heading, quite terse."
    assert len(short) <= 55
    slices = {1: [
        _blk(tag="h3", classes=("Serif-11-center",), text=long_sent),
        _blk(tag="h3", classes=("Serif-11-center",), text=short),
        _blk(tag="h2", classes=("Serif-12",), text=long_sent),
    ]}
    ok, summary, lines = check_heading_census(
        slices, doc, GEO, "Serif", set(), [], {1}, {}, [], 11.0, {})
    audit_hits = [l for l in lines if "sentence-like" in l and not l.startswith("info:")]
    info_hits = [l for l in lines if l.startswith("info:")]
    assert not ok and len(audit_hits) == 1 and "<h3>" in audit_hits[0]
    assert len(info_hits) == 1 and "<h2>" in info_hits[0]


# ---------------------------------------------------------------- gate 17

def test_signature_wrong_cluster_fires():
    paras = [PdfParaGeo(start_page=1, role="p", style="Serif@11",
                        lines=[_line("x")], size_pt=11.0, letters=50,
                        text="an ordinary body paragraph")]
    slices = {1: [_blk(classes=("Serif-30",), text="rendered display sized",
                       letters=50)]}
    ok, summary, findings = check_signature_diff(slices, paras, RULES, 11.0, [1])
    assert not ok and "p.1" in findings[0]
    assert "body" in findings[0] and "display" in findings[0]


def test_signature_join_drift_invisible_after_rle():
    # PDF: three body paragraphs; EPUB: one (join drift) -> RLE equalizes
    paras = [PdfParaGeo(start_page=1, role="p", style="Serif@11",
                        lines=[_line("x")], size_pt=11.0, letters=50, text=f"p{i}")
             for i in range(3)]
    slices = {1: [_blk(text="all three joined", letters=150)]}
    ok, _, findings = check_signature_diff(slices, paras, RULES, 11.0, [1])
    assert ok and not findings


def test_signature_centered_claim_matches():
    # PDF /center pstyle vs EPUB -center class: consistent -> silent;
    # EPUB centered without a PDF /center claim -> fires
    paras = [PdfParaGeo(start_page=1, role="p", style="Serif@11/center",
                        lines=[_line("x")], size_pt=11.0, letters=20, text="c")]
    slices = {1: [_blk(classes=("Serif-11-center",), text="centered", letters=20)]}
    ok, _, findings = check_signature_diff(slices, paras, RULES, 11.0, [1])
    assert ok and not findings
    paras[0].style = "Serif@11"
    ok, _, findings = check_signature_diff(slices, paras, RULES, 11.0, [1])
    assert not ok and "·ctr" in findings[0]


def test_slicer_verse_stanza_one_block():
    # gate 17's 1 flow-Paragraph = 1 emitted block invariant, verse cell:
    # each stanza <p class="vs"> slices as ONE block (in_blockquote), its
    # text br->space joined so line ends never fuse
    from pdf2epub.core.qa_pageslice import slice_pages

    xhtml = (
        '<div class="pagebreak" epub:type="pagebreak" role="doc-pagebreak" '
        'aria-label="8" id="pg-8"></div>'
        '<blockquote class="verse" epub:type="z3998:verse">'
        '<p class="vs">'
        '<span class="vl">I dwell at your door always, like dirt—</span><br/>'
        '<span class="vl vt">others come and go like the wind.</span>'
        "</p></blockquote>")
    docs = [_doc("c1.xhtml", xhtml)]
    res = slice_pages(docs, [8], {8: "8"})
    assert res.ok
    blks = [b for b in res.slices[8] if b.tag == "p"]
    assert len(blks) == 1
    assert blks[0].in_blockquote
    assert "vs" in blks[0].classes
    assert blks[0].text == ("I dwell at your door always, like dirt— "
                            "others come and go like the wind.")


def test_verse_integrity_counts():
    # gate 23's evidence function: expected lines from the flow's U+2028
    # separators vs shipped span.vl count — a flattened poem (0 spans) or a
    # dropped line mismatches; matching markup is silent
    from pdf2epub.core.model import Paragraph, SourceRef, TextRun
    from pdf2epub.qa.runner import verse_integrity_counts

    stanza = Paragraph(style="s", src=SourceRef("p0035", 0),
                       block_class="verse", verse_turns=[1],
                       items=[TextRun("like dirt\u2028others come")])
    prose = Paragraph(style="s", src=SourceRef("p0035", 5),
                      items=[TextRun("ordinary prose")])
    good = _doc("c1.xhtml",
                '<blockquote class="verse"><p class="vs">'
                '<span class="vl">like dirt</span><br/>'
                '<span class="vl vt">others come</span></p></blockquote>')
    n, exp, got = verse_integrity_counts([stanza, prose], [good])
    assert (n, exp, got) == (1, 2, 2)
    flattened = _doc("c1.xhtml", "<p>like dirt others come</p>")
    n, exp, got = verse_integrity_counts([stanza, prose], [flattened])
    assert (n, exp, got) == (1, 2, 0)  # the old-EPUB promotion evidence
