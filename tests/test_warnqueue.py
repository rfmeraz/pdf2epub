"""Warning queue (gate 22): derivation, auto-resolve, adjudications."""

from types import SimpleNamespace

import pytest

from pdf2epub.config import (
    Adjudication,
    ColumnSpec,
    FigurePages,
    FigureRegion,
    FlowOverride,
    PdfBookConfig,
)
from pdf2epub.core.model import Paragraph, RunFormat, SourceRef, TextRun
from pdf2epub.flowbuilder import _Warn
from pdf2epub.pdfmodel import PdfDoc, PdfPage
from pdf2epub.warnqueue import (
    CODES,
    CONTENT_RISK,
    apply_adjudications,
    auto_resolve,
    derive_warnings,
    render_queue,
    rtl_census,
)


def _page(number, image_only=False, agreement=None, n_images=0):
    return PdfPage(number=number, label=str(number), width=400, height=600,
                   trim=(0, 0, 400, 600), image_only=image_only,
                   engine_agreement=agreement, n_images=n_images)


def _doc(pages, warnings=(), uri=0):
    d = PdfDoc(pdf_path="x.pdf", sha256="s", producer="t",
               n_pages=len(pages), pages=pages)
    d.warnings = list(warnings)
    d.uri_link_count = uri
    return d


def _cfg(tmp_path, **kw):
    cfg = PdfBookConfig(path=tmp_path / "book.yaml")
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def _flow(blocks=(), style_usage=None):
    from collections import Counter

    return SimpleNamespace(blocks=list(blocks),
                           style_usage=Counter(style_usage or {}))


def test_derivation_from_fields_not_strings(tmp_path):
    # page lists come from doc fields — the display strings truncate at 15
    doc = _doc([_page(1, image_only=True), _page(2, agreement=55.0),
                _page(3, n_images=2)])
    aw = derive_warnings(doc, None, None, _cfg(tmp_path))
    codes = sorted(w.code for w in aw)
    assert codes == ["embedded-image-uncovered", "engine-agreement-low",
                     "image-only-page"]
    assert all(w.severity == CONTENT_RISK for w in aw)
    by = {w.code: w for w in aw}
    assert by["image-only-page"].pages == [1]
    assert by["engine-agreement-low"].pages == [2]
    assert by["embedded-image-uncovered"].pages == [3]


def test_string_classified_extract_warnings(tmp_path):
    # pinned against the literal emission formats in extract/mupdf.py
    doc = _doc([_page(1)], warnings=[
        "page 7 is rotated 90° — review renders",
        "outline entry 'Broken' has external/broken target; skipped",
        "page 9: unresolvable link annotation (kind 3, 'x')",
    ], uri=4)
    aw = derive_warnings(doc, None, None, _cfg(tmp_path))
    by = {w.code: w for w in aw}
    assert by["page-rotated"].pages == [7]
    assert by["page-rotated"].severity == CONTENT_RISK
    assert by["outline-broken-target"].severity == "advisory"
    assert by["link-unresolvable"].pages == [9]
    assert "4 external URI" in by["uri-links"].msg


def test_flow_warns_and_scans(tmp_path):
    res = SimpleNamespace(warns=[
        _Warn("p.4 line 0: unrecognized top-band line kept: 'X'", 4, 0,
              "{page: 4, line: 0, action: drop, note: FILL}",
              code="top-band-kept"),
        _Warn("future warning with no code yet", 5, -1),
    ])
    para = Paragraph(style="Serif@11",
                     items=[TextRun("live الله text",
                                    RunFormat())],
                     src=SourceRef("p0001", 0))
    flow = _flow([para], {"Serif@11": 3, "Odd@9": 1, "__toc__": 2})
    cfg = _cfg(tmp_path, pstyle_map={"Serif@11": object()})
    aw = derive_warnings(_doc([_page(1)]), res, flow, cfg)
    by = {w.code: w for w in aw}
    assert by["top-band-kept"].pages == [4] and by["top-band-kept"].line == 0
    assert by["top-band-kept"].snippet.startswith("{page: 4")
    assert by["flow-uncoded"].severity == CONTENT_RISK  # fail-safe
    assert "4 right-to-left" in by["rtl-live-text"].msg
    assert "Odd@9" in by["unmapped-pstyles"].msg
    assert "__toc__" not in by["unmapped-pstyles"].msg


def _head(text, role="h3"):
    return Paragraph(style="SC@11", role=role,
                     items=[TextRun(text, RunFormat())],
                     src=SourceRef("p0001", 0))


def test_nav_numeric_bloat_prompt_and_autoresolve(tmp_path):
    # >=10 numeric-only headings among the flow's h1/h2/h3 -> the judgment
    # prompt the nav lacked (gate 7 only checked subset, never bloat)
    blocks = [_head("Childhood")] + [_head(f"{i}.") for i in range(1, 13)]
    doc, flow = _doc([_page(1)]), _flow(blocks)

    cfg = _cfg(tmp_path)                                  # flag OFF (default)
    aw = derive_warnings(doc, None, flow, cfg)
    bloat = [w for w in aw if w.code == "nav-numeric-bloat"]
    assert len(bloat) == 1
    w = bloat[0]
    assert w.severity == "advisory" and w.pages == [] and w.open
    assert "12 numeric-only headings" in w.msg
    assert auto_resolve(aw, cfg) >= 0 and w.open       # stays open, prompts

    cfg_on = _cfg(tmp_path, toc_drop_numeric_nav_entries=True)
    aw2 = derive_warnings(doc, None, flow, cfg_on)
    w2 = next(x for x in aw2 if x.code == "nav-numeric-bloat")
    auto_resolve(aw2, cfg_on)                            # flag records decision
    assert not w2.open and w2.resolved_by == "toc.drop_numeric_nav_entries set"


def test_nav_numeric_bloat_below_threshold(tmp_path):
    # <10 numeric headings, and numeric NON-headings, do not fire
    blocks = ([_head(f"{i}.") for i in range(1, 6)]      # 5 numeric heads
              + [_head("My Travels")]                    # named head — never counts
              + [_head("7.", role="p")])                 # numeric but not a heading
    aw = derive_warnings(_doc([_page(1)]), None, _flow(blocks), _cfg(tmp_path))
    assert not any(w.code == "nav-numeric-bloat" for w in aw)


def test_rtl_census_expected_vs_unexpected():
    ar = RunFormat(lang="ar")
    zh = RunFormat(lang="zh")
    para = Paragraph(style="s", items=[
        TextRun("صلى", ar),      # tagged: expected
        TextRun("ا", RunFormat()),          # untagged: unexpected
        TextRun("ل", zh),                   # CJK-tagged: unexpected
    ], src=SourceRef("p0001", 0))
    assert rtl_census(_flow([para])) == (3, 2)
    # U+FEFF (BOM/ZWNBSP prepress artifact) is NOT RTL text (HU title pages)
    bom = Paragraph(style="s", items=[TextRun("﻿", RunFormat())],
                    src=SourceRef("p0001", 0))
    assert rtl_census(_flow([bom])) == (0, 0)


def test_auto_resolve_rules(tmp_path):
    doc = _doc([_page(1, image_only=True), _page(2, image_only=True),
                _page(3, agreement=50.0), _page(4, agreement=50.0),
                _page(5, n_images=1), _page(6, n_images=1)])
    res = SimpleNamespace(warns=[
        _Warn("top band", 8, 2, code="top-band-kept"),
        _Warn("top band", 9, 1, code="top-band-kept"),
    ])
    cfg = _cfg(tmp_path,
               pages_cover=[1],
               figure_pages=[FigurePages(pages=[2])],
               flow_columns=[ColumnSpec(pages=[3], count=2)],
               figure_regions=[FigureRegion(page=5, rect=(0, 0, 9, 9), alt="x")],
               flow_overrides=[FlowOverride(page=8, line=2, action="drop")])
    aw = derive_warnings(doc, res, None, cfg)
    n = auto_resolve(aw, cfg)
    status = {(w.code, tuple(w.pages)): bool(w.resolved_by) for w in aw}
    assert status[("image-only-page", (1,))]          # cover
    assert status[("image-only-page", (2,))]          # figure page
    assert status[("engine-agreement-low", (3,))]     # flow.columns
    assert not status[("engine-agreement-low", (4,))]
    assert status[("embedded-image-uncovered", (5,))]  # figure_regions
    assert not status[("embedded-image-uncovered", (6,))]
    assert status[("top-band-kept", (8,))]            # exact override
    assert not status[("top-band-kept", (9,))]
    assert n == 5


def test_adjudications_matching_and_stale(tmp_path):
    doc = _doc([_page(4, n_images=1), _page(5, n_images=1)])
    aw = derive_warnings(doc, None, None, _cfg(tmp_path))
    cfg = _cfg(tmp_path, adjudications=[
        Adjudication(warning="embedded-image-uncovered", pages=[4, 5],
                     note="ornament flourishes, render-verified"),
    ])
    open_, adjudicated, stale = apply_adjudications(aw, cfg)
    assert not stale and len(adjudicated) == 2 and not open_
    assert adjudicated[0].adjudicated_by.startswith("ornament")
    # a page matching nothing open is stale, per page
    aw = derive_warnings(doc, None, None, _cfg(tmp_path))
    cfg2 = _cfg(tmp_path, adjudications=[
        Adjudication(warning="embedded-image-uncovered", pages=[4, 9],
                     note="n")])
    _, _, stale = apply_adjudications(aw, cfg2)
    assert len(stale) == 1 and "[9]" in stale[0]
    # wholesale (no pages) covers aggregate warnings; stale when none open
    aw = derive_warnings(doc, None, None, _cfg(tmp_path))
    cfg3 = _cfg(tmp_path, adjudications=[
        Adjudication(warning="rtl-live-text", pages=[], note="n")])
    _, _, stale = apply_adjudications(aw, cfg3)
    assert len(stale) == 1


def test_every_emitted_code_known(tmp_path):
    doc = _doc([_page(1, image_only=True, agreement=10.0, n_images=1)],
               warnings=["page 1 is rotated 90° — review renders"], uri=1)
    res = SimpleNamespace(warns=[_Warn("x", 1, 0, code="pua-unmapped")])
    para = Paragraph(style="s", items=[TextRun("ا", RunFormat())],
                     src=SourceRef("p0001", 0))
    aw = derive_warnings(doc, res, _flow([para], {"S@1": 1}), _cfg(tmp_path))
    assert all(w.code in CODES for w in aw)
    assert all(w.severity == CODES[w.code] for w in aw)


def test_snippet_parses_and_render_queue(tmp_path):
    import yaml

    from pdf2epub.warnqueue import adjudication_snippet

    snip = adjudication_snippet("top-band-kept", [21, 62])
    parsed = yaml.safe_load(snip)
    assert parsed[0]["warning"] == "top-band-kept"
    assert parsed[0]["pages"] == [21, 62]
    assert "note" in parsed[0]
    doc = _doc([_page(1, image_only=True), _page(2, image_only=True)])
    cfg = _cfg(tmp_path, pages_cover=[1])
    aw = derive_warnings(doc, None, None, cfg)
    auto_resolve(aw, cfg)
    lines = render_queue(aw, [])
    text = "\n".join(lines)
    assert "image-only-page [content-risk] — 1 open / 2 total" in text
    assert "auto-resolved: cover/excluded page" in text
    assert "adjudicate: `- {warning: image-only-page, pages: [2]" in text


def test_config_adjudications_parsing(tmp_path):
    from pdf2epub.config import ConfigError, load_config

    p = tmp_path / "book.yaml"
    p.write_text(
        "source: {folder: p, pdf: b.pdf}\n"
        "qa:\n"
        "  lost_space_allow:\n"
        "    - {snippet: etc.Cambridge, note: \"as printed, p.44 render\"}\n"
        "  garble_chars: \"\\u00B3\\u00B4\"\n"
        "adjudications:\n"
        "  - {warning: rtl-live-text, note: user-requested Arabic variant}\n"
        "  - {warning: top-band-kept, pages: [21, \"30-31\"], note: verified}\n")
    cfg = load_config(p)
    assert cfg.qa_lost_space_allow[0].snippet == "etc.Cambridge"
    assert cfg.qa_garble_chars == "³´"
    assert cfg.adjudications[0].warning == "rtl-live-text"
    assert cfg.adjudications[0].pages == []
    assert cfg.adjudications[1].pages == [21, 30, 31]
    with pytest.raises(ConfigError, match="warning code unknown"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "adjudications: [{warning: nonsense, note: n}]")
        load_config(p)
    with pytest.raises(ConfigError, match="requires a note"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "adjudications: [{warning: rtl-live-text}]")
        load_config(p)
    with pytest.raises(ConfigError, match="requires a note"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "qa: {lost_space_allow: [{snippet: x}]}")
        load_config(p)
    with pytest.raises(ConfigError, match="unknown key"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "qa: {lost_space_allowx: []}")
        load_config(p)


def test_index_locator_warning_derives_and_adjudicates(tmp_path):
    # QA parity (Schuon L&T): the build's queue carries index-locator-unlinked
    # from the index-locator pass; gate 22's re-derivation must too, or an
    # adjudication covering it reads stale at QA time while warnings.md shows
    # the warning it covers. The runner now runs link_index_locators after
    # build_flow; this pins the mechanism: a res.warns entry with that code
    # derives into the queue and its adjudication matches (not stale).
    from collections import Counter

    from pdf2epub.core.model import FlowDoc, PageAnchor
    from pdf2epub.flowbuilder import FlowResult
    from pdf2epub.index_locators import link_index_locators

    entry = Paragraph(style="s", role="index",
                      items=[TextRun("Buddhism, 515", RunFormat())],
                      src=SourceRef("p0207", 0))
    flow = FlowDoc(blocks=[PageAnchor(1, "1"), entry], notes={},
                   style_usage=Counter(), text_dests={})
    res = FlowResult(flow=flow)
    cfg = _cfg(tmp_path)
    link_index_locators(res, cfg, say=lambda m: None)
    assert any(w.code == "index-locator-unlinked" for w in res.warns)

    aw = derive_warnings(_doc([_page(1)]), res, flow, cfg)
    assert any(w.code == "index-locator-unlinked" for w in aw)
    cfg.adjudications = [Adjudication(warning="index-locator-unlinked",
                                      pages=[], note="as printed")]
    open_, adjudicated, stale = apply_adjudications(aw, cfg)
    assert not stale
    assert any(w.code == "index-locator-unlinked" for w in adjudicated)
