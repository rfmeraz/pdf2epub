"""Layout witness — pure-logic tests that pass with the ML backend ABSENT.

Everything model-dependent is behind lazy imports; these exercise the coordinate
mapping, label bucketing, report/snippet generation, page-set resolution, and
import hygiene without loading torch/transformers.
"""

import subprocess
import sys
import types

import pytest
import yaml

from pdf2epub import layoutwitness as lw
from pdf2epub.analyze import Analysis


def _line(x0, x1):
    return types.SimpleNamespace(x0=x0, x1=x1)


def _page(number, n_images=0, trim=(50, 50, 400, 600), lines=(), n_chars=100):
    return types.SimpleNamespace(number=number, n_images=n_images, trim=trim,
                                 lines=list(lines), n_chars=n_chars)


def _doc(n_pages, sha="abcdef0123456789", pages=None, outline=()):
    if pages is None:
        pages = [_page(i) for i in range(1, n_pages + 1)]
    return types.SimpleNamespace(n_pages=n_pages, sha256=sha, pages=pages,
                                 outline=list(outline))


# --------------------------------------------------- coordinate mapping

def test_pixel_to_extract_space_scale():
    # 150 dpi -> point = pixel * 72/150 = pixel * 0.48
    boxes = lw._boxes_from_detections(
        scores=[0.9123], labels=[9], boxes_px=[[100, 200, 300, 500]],
        id2label={9: "Table"}, pno=7, dpi=150)
    assert len(boxes) == 1
    b = boxes[0]
    assert b.rect == (48.0, 96.0, 144.0, 240.0)
    assert b.label == "Table" and b.page == 7 and b.position == 0
    assert b.confidence == 0.912


def test_boxes_well_ordered_and_reading_sorted():
    boxes = lw._boxes_from_detections(
        scores=[0.5, 0.5], labels=[10, 10],
        boxes_px=[[0, 400, 100, 300], [0, 100, 100, 50]],  # note reversed y
        id2label={10: "Text"}, pno=1, dpi=72)               # scale 1.0
    for b in boxes:                                          # x0<x1, y0<y1 (config rule)
        assert b.rect[0] < b.rect[2] and b.rect[1] < b.rect[3]
    assert boxes[0].rect[1] < boxes[1].rect[1]              # top box first
    assert [b.position for b in boxes] == [0, 1]


def test_degenerate_boxes_dropped():
    boxes = lw._boxes_from_detections(
        scores=[0.9], labels=[10], boxes_px=[[10, 10, 10.2, 10.2]],
        id2label={10: "Text"}, pno=1, dpi=72)
    assert boxes == []


# --------------------------------------------------------- bucketing

def test_label_bucketing():
    assert lw._bucket("Table") == "figure"
    assert lw._bucket("Picture") == "figure"
    assert lw._bucket("Table-of-contents") == "toc"      # not swallowed by "table"
    assert lw._bucket("Page-header") == "header"
    assert lw._bucket("Page-footer") == "footer"
    assert lw._bucket("Section-header") == "heading"     # NOT furniture
    assert lw._bucket("Title") == "heading"
    assert lw._bucket("Footnote") == "footnote"
    assert lw._bucket("Text") == "text"
    assert lw._bucket("List-item") == "text"


# ------------------------------------------------ report / snippets

def _table(page, rect, conf=0.58):
    return lw.LayoutBox(page, "Table", rect, 0, conf)


def test_figure_region_snippet_is_schema_valid():
    boxes = {26: [_table(26, (70.0, 319.0, 367.0, 567.0))]}
    md = lw._report_md(_doc(30), Analysis(), boxes, scanned=[26], desc="explicit")
    assert "## Figure/table candidates" in md
    block = md.split("```yaml", 1)[1].split("```", 1)[0]
    fr = yaml.safe_load(block)["images"]["figure_regions"][0]
    # the same checks config.py applies to figure_regions
    assert fr["page"] == 26 and "alt" in fr
    r = fr["rect"]
    assert len(r) == 4 and r[0] < r[2] and r[1] < r[3]


def test_report_states_coverage_explicitly():
    md = lw._report_md(_doc(312), Analysis(), {26: []}, scanned=[26],
                       desc="flagged + structure-suspect")
    assert "scanned 1/312 pages" in md
    assert "NOT layout-checked" in md


def test_crosscheck_footnote_agreement():
    boxes = {50: [lw.LayoutBox(50, "Footnote", (70, 560, 220, 578), 0, 0.76)]}
    md = lw._report_md(_doc(60), Analysis(footnote_pages=[50]), boxes,
                       scanned=[50], desc="x")
    assert "Footnotes:" in md and "[50]" in md


def test_column_suggestions_detects_two_columns():
    B = lw.LayoutBox
    boxes = {5: [
        B(5, "Text", (50, 100, 240, 300), 0, 0.6),
        B(5, "Text", (50, 320, 240, 500), 1, 0.6),
        B(5, "Text", (260, 100, 450, 300), 2, 0.6),   # right band, y-overlaps left
        B(5, "Text", (260, 320, 450, 500), 3, 0.6),
    ]}
    assert lw._column_suggestions(boxes) == [(5, 2)]


def test_column_suggestions_ignores_single_column():
    B = lw.LayoutBox
    boxes = {5: [B(5, "Text", (50, 100 + 40 * i, 450, 130 + 40 * i), i, 0.6)
                 for i in range(5)]}
    assert lw._column_suggestions(boxes) == []


def test_write_layout_evidence_files(tmp_path):
    boxes = {26: [_table(26, (70.0, 319.0, 367.0, 567.0))]}
    lw.write_layout_evidence(_doc(30), Analysis(), boxes, [26], "explicit", tmp_path)
    payload = yaml.safe_load((tmp_path / "layout.json").read_text())
    assert payload["coverage"]["n_scanned"] == 1
    assert payload["coverage"]["n_not_scanned"] == 29
    assert payload["pages"]["26"][0]["label"] == "Table"
    assert (tmp_path / "report.md").exists()


# --------------------------------------------------- page selection

def test_structure_suspect_uses_cheap_signals():
    pages = [_page(1),
             _page(2, n_images=3),                       # embedded image
             _page(3, lines=[_line(50, 90)] * 10),       # short lines -> tabular
             _page(4)]
    doc = _doc(4, pages=pages)
    s = lw.structure_suspect_pages(doc, Analysis(column_suspect_pages=[1]),
                                   drawings_dense={4})    # vector-ruled page
    assert s == {1, 2, 3, 4}


def test_toc_has_figure_list():
    assert lw.toc_has_figure_list(_doc(5), Analysis(toc_entries=[{"text": "List of Tables"}]))
    assert lw.toc_has_figure_list(_doc(5), Analysis(headings=[{"text": "List of Illustrations"}]))
    assert lw.toc_has_figure_list(
        _doc(5, outline=[types.SimpleNamespace(title="Table of Figures")]), Analysis())
    assert not lw.toc_has_figure_list(_doc(5), Analysis(toc_entries=[{"text": "Introduction"}]))


def test_auto_pages_rule():
    p, desc = lw.auto_pages(_doc(10), Analysis(flagged_pages=[2]))
    assert p == set(range(1, 11)) and "auto=all" in desc            # <=300pp

    big = _doc(400)
    p, desc = lw.auto_pages(big, Analysis(flagged_pages=[2]))
    assert p == {2} and desc == "auto=flagged+structure-suspect"    # no signal
    assert lw.auto_pages(big, Analysis(flagged_pages=[2]),
                         drawings_dense={150})[0] == set(range(1, 401))   # vector-ruled
    assert lw.auto_pages(big, Analysis(toc_entries=[{"text": "List of Figures"}]))[0] \
        == set(range(1, 401))                                        # TOC list


def test_resolve_pages_modes():
    big = _doc(400)
    a = Analysis(flagged_pages=[2], column_suspect_pages=[4])
    d, desc = lw.resolve_pages(None, big, a)               # default = auto
    assert set(d) == {2, 4} and "auto=" in desc
    f, fdesc = lw.resolve_pages("flagged", big, a)         # force subset
    assert set(f) == {2, 4} and "structure-suspect" in fdesc
    assert lw.resolve_pages("all", big, a)[0] == list(range(1, 401))
    assert lw.resolve_pages("3,5-7", big, a)[0] == [3, 5, 6, 7]


def test_sample_is_seeded_and_non_duplicating():
    doc = _doc(50, sha="deadbeefcafebabe")
    a = Analysis(flagged_pages=[1])
    s1, _ = lw.resolve_pages("+sample:5", doc, a)
    s2, _ = lw.resolve_pages("+sample:5", doc, a)
    assert s1 == s2                                       # deterministic
    extra = [p for p in s1 if p not in lw.default_pages(doc, a)]
    assert len(extra) == 5


# ------------------------------------------------------- isolation

def test_no_module_level_ml_imports():
    # torch/transformers must be function-local, never bound on the module
    assert not hasattr(lw, "torch")
    assert not hasattr(lw, "transformers")


def test_layout_available_false_when_backend_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)  # -> ImportError on import
    assert lw.layout_available() is False


def test_initcmd_import_does_not_pull_ml_backend():
    # a plain `init` (no --layout) must not import torch/transformers
    code = ("import sys, pdf2epub.initcmd\n"
            "assert 'transformers' not in sys.modules\n"
            "assert 'torch' not in sys.modules\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
