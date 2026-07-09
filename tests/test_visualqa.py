"""Visual QA pure parts: sampler, slice planning, dHash, page checks."""

from types import SimpleNamespace

from PIL import Image

from pdf2epub.core.model import (Figure, NoteRef, PageAnchor, Paragraph,
                                 RunFormat, SourceRef, TextRun)
from pdf2epub.qa.visual import plan_slices
from pdf2epub.qa.visual_pixels import dhash, hamming
from pdf2epub.qa.visual_sample import (SampleEvidence, checks_by_page,
                                       sample_pages)

SHA = "abcdef0123456789" * 4


def _ev(**kw):
    n = kw.pop("n_pages", 40)
    ev = SampleEvidence(sha256=kw.pop("sha256", SHA), n_pages=n,
                        in_flow=kw.pop("in_flow", list(range(1, n + 1))))
    for k, v in kw.items():
        setattr(ev, k, v)
    return ev


def test_sampler_deterministic_and_seeded():
    ev = _ev(style_usage={"Serif@11": 100, "Serif@14": 3},
             page_styles={p: ["Serif@11"] for p in range(1, 41)} | {7: ["Serif@11", "Serif@14"]},
             dropcap_pages=[5], first_h1_page=3)
    a = sample_pages(ev, cap=10)
    b = sample_pages(ev, cap=10)
    assert [(s.page, s.reasons) for s in a] == [(s.page, s.reasons) for s in b]
    ev2 = _ev(sha256="f" * 64, style_usage=ev.style_usage,
              page_styles=ev.page_styles, dropcap_pages=[5], first_h1_page=3)
    c = sample_pages(ev2, cap=10)
    non_random = lambda smp: {s.page for s in smp if s.reasons != ["random"]}
    assert non_random(a) == non_random(c)      # only random picks may move


def test_sampler_strata_and_style_cover():
    ev = _ev(style_usage={"Serif@11": 90, "Rare@9": 1, "Head@14": 5},
             page_styles={1: ["Serif@11"], 2: ["Serif@11", "Head@14"],
                          3: ["Rare@9"], 4: ["Serif@11"]},
             in_flow=[1, 2, 3, 4], n_pages=4,
             dropcap_pages=[4], pua_first_page={"": 2},
             figure_pages=[1], note_pages=[2], first_h1_page=2)
    got = sample_pages(ev, cap=10)
    pages = {s.page for s in got}
    assert {1, 2, 3, 4} <= pages               # strata A + rare-style cover
    r3 = next(s for s in got if s.page == 3)
    assert any(x.startswith("pstyle:") for x in r3.reasons)
    r2 = next(s for s in got if s.page == 2)
    assert "first h1" in r2.reasons and "pua U+E000 first page" in r2.reasons


def test_sampler_cap_and_min_random():
    ev = _ev(style_usage={f"S{i}@11": 1 for i in range(30)},
             page_styles={p: [f"S{p}@11"] for p in range(1, 31)},
             in_flow=list(range(1, 31)), n_pages=30)
    got = sample_pages(ev, cap=8)
    assert len(got) <= 8
    assert sum(1 for s in got if "random" in s.reasons) >= 3


def _anchor(pg, label=None, approx=False):
    return PageAnchor(ordinal=pg, label=label or str(pg), approximate=approx)


def test_plan_slices_shapes():
    anchors = [_anchor(1), _anchor(2), _anchor(3, approx=True)]
    pbs = [("a.xhtml", "pg-1"), ("a.xhtml", "pg-2"), ("b.xhtml", "pg-3")]
    plans = plan_slices(anchors, pbs, [1, 2, 3], [1, 2, 3, 9])
    assert plans[1].same_file and plans[1].next_href == "a.xhtml"
    assert not plans[2].same_file and plans[2].next_href == "b.xhtml"
    assert plans[3].same_file is False and plans[3].next_href is None
    assert plans[3].approximate
    assert plans[9] is None                    # excluded page: no anchor
    # count mismatch -> every plan degrades to None (fail-safe)
    bad = plan_slices(anchors, pbs[:2], [1, 2, 3], [1, 2])
    assert bad[1] is None and bad[2] is None


def test_flow_anchors_document_order():
    from pdf2epub.core.model import InlinePageBreak
    from pdf2epub.qa.visual import _flow_anchors

    para = Paragraph(style="s", items=[TextRun("spans the turn"),
                                       InlinePageBreak(2, "2"),
                                       TextRun("and continues")],
                     src=SourceRef("p0001", 0))
    flow = SimpleNamespace(blocks=[_anchor(1), para, _anchor(3, approx=True)])
    anchors = _flow_anchors(flow)
    assert [(a.ordinal, a.approximate) for a in anchors] == \
        [(1, False), (2, False), (3, True)]
    # feeds plan_slices with no loose-compare note for the inline anchor
    pbs = [("a.xhtml", "pg-1"), ("a.xhtml", "pg-2"), ("a.xhtml", "pg-3")]
    plans = plan_slices(anchors, pbs, [1, 2, 3], [2])
    assert plans[2].approximate is False


def test_dhash_properties():
    a = Image.new("RGB", (64, 64), (255, 255, 255))
    for x in range(0, 64, 8):
        for y in range(64):
            a.putpixel((x, y), (0, 0, 0))
    same = dhash(a)
    assert hamming(same, dhash(a.resize((48, 48)))) <= 6   # mild resize
    inverted = Image.eval(a, lambda v: 255 - v)
    assert hamming(same, dhash(inverted)) > 20


def test_checks_by_page():
    from pdf2epub.pdfmodel import PdfDoc, PdfFont, PdfLine, PdfPage, PdfRun

    fmt = RunFormat()
    ar = RunFormat(lang="ar")
    para = Paragraph(style="Serif@11", role="p",
                     items=[TextRun("Body with a note", fmt), NoteRef("n1"),
                            TextRun(" (exalted)", ar)],
                     src=SourceRef("p0001", 0))
    head = Paragraph(style="Serif@14/center", role="h2",
                     items=[TextRun("Chapter One", fmt)],
                     src=SourceRef("p0001", 3))
    flow = type("F", (), {})()
    flow.blocks = [_anchor(1), head, para,
                   Figure(image_key="page-0001.png", source_basename="x",
                          pdf_page=1, page_ordinal=1, y_pt=0, x_pt=0,
                          width_pt=10, height_pt=10)]
    res = type("R", (), {})()
    res.dropcap_srcs = {("p0001", 0)}
    line = PdfLine(runs=[PdfRun(text="xy", font_id=0,
                                x0=0, y0=0, x1=10, y1=10)],
                   x0=0, y0=0, x1=10, y1=10)
    doc = PdfDoc(pdf_path="x", sha256="s", producer="p", n_pages=1,
                 pages=[PdfPage(number=1, label="1", width=100, height=100,
                                trim=(0, 0, 100, 100), lines=[line])],
                 fonts={0: PdfFont(0, "Serif", "Serif", 11.0, "#000")})
    got = checks_by_page(doc, flow, res, None, {1: "1"}, [1])
    c = got[1]
    assert c["pstyles"] == {"Serif@11": 1, "Serif@14/center": 1}
    assert c["headings"] == [{"role": "h2", "text": "Chapter One"}]
    assert c["dropcap"] and c["noterefs"] == 1 and c["figures"] == 1
    assert c["lang_spans"] == ["ar"] and c["pua"] == {"U+E000": 1}
