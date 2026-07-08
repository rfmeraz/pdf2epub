"""Synthetic style catalog: sizes, centering, and the no-class-italic rule."""

from types import SimpleNamespace

from pdf2epub.config import CharStyleFlags
from pdf2epub.styles_synth import build_catalog


def _ctx(styles, charstyles=None):
    cfg = SimpleNamespace(body_pstyle="Serif@11", body_style="Serif@11",
                          charstyles=charstyles or {})
    flow = SimpleNamespace(style_usage={s: 1 for s in styles})
    return SimpleNamespace(cfg=cfg, flow=flow)


def test_catalog_size_and_center():
    cat = build_catalog(_ctx(["Serif@11", "Serif@14/center"]))
    assert cat["Serif@11"].point_size == 11.0
    st = cat["Serif@14/center"]
    assert st.point_size == 14.0
    assert st.justification == "CenterAlign" and st.first_line_indent == 0.0


def test_catalog_never_italicizes_by_family():
    # run-level italics carry <i>; a class-level italic would sweep the roman
    # runs of MIXED paragraphs along (BoK p.xx Qurʾān-quote paragraph)
    cat = build_catalog(_ctx(["Serif-Italic@11", "SerifItalic@10/center"]))
    assert cat["Serif-Italic@11"].font_style is None
    assert cat["SerifItalic@10/center"].font_style is None


def test_catalog_smallcaps_charstyle():
    cat = build_catalog(_ctx(["Caps@11"],
                             {"Caps": CharStyleFlags(smallcaps=True)}))
    assert cat["Caps@11"].capitalization == "SmallCaps"
