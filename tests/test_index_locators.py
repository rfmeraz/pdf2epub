"""Linked index locators (pdf2epub.index_locators).

The transform wraps back-of-book index page numbers in #pg-<label> cross-ref
links (reusing the RunFormat.link chain) and tags the index for the DAISY
<section epub:type="index"> container — opt-in via flow.columns[].index or the
`index` role, byte-identical otherwise. It never rewrites text and only links a
number whose page anchor actually exists.
"""

from collections import Counter
from types import SimpleNamespace

from pdf2epub.config import ColumnSpec, PdfBookConfig
from pdf2epub.core.emit_xhtml import Emitter
from pdf2epub.core.model import (
    FlowDoc,
    PageAnchor,
    Paragraph,
    RunFormat,
    SourceRef,
    TextRun,
)
from pdf2epub.flowbuilder import FlowResult
from pdf2epub.index_locators import link_index_locators

# ------------------------------------------------------------------ helpers

def _p(text, page, role=None):
    """A one-run Paragraph that started on physical page `page`."""
    return Paragraph(style="s", items=[TextRun(text, RunFormat())],
                     src=SourceRef(f"p{page:04d}", 0), role=role)


def _result(blocks):
    flow = FlowDoc(blocks=blocks, notes={}, style_usage=Counter(), text_dests={})
    return FlowResult(flow=flow)


def _cols(*specs):
    return SimpleNamespace(flow_columns=list(specs))


def _links(items):
    return [(it.text, it.fmt.link) for it in items if isinstance(it, TextRun)]


# ------------------------------------------------------------------ tokenizer

def test_links_page_locators_and_skips_citation():
    # a Qurʾānic verse-index entry: link the page numbers, NOT the 35:8 citation
    entry = _p("35:8, 322, 322–323", 322)
    res = _result([PageAnchor(322, "322"), PageAnchor(323, "323"), entry])
    link_index_locators(res, _cols(ColumnSpec([322, 323], 3, index=True)),
                        say=lambda m: None)
    links = _links(entry.items)
    assert ("322", "page:322") in links          # single page
    assert ("322–323", "page:322") in links       # range -> first page
    assert ("35:8, ", None) in links              # sura:verse untouched


def test_out_of_range_locator_unlinked_and_warned():
    entry = _p("Zöllner, 999", 324)
    res = _result([PageAnchor(324, "324"), entry])
    link_index_locators(res, _cols(ColumnSpec([324], 2, index=True)),
                        say=lambda m: None)
    assert all(lk is None for _, lk in _links(entry.items))  # no pg-999 anchor
    assert [w.code for w in res.warns] == ["index-locator-unlinked"]


def test_note_suffix_and_word_digits_not_linked():
    # 189n.4 (note suffix) and 20th (digits inside a word) must not link
    entry = _p("faith, 189n.4; 20th century, 322", 322)
    res = _result([PageAnchor(189, "189"), PageAnchor(322, "322"), entry])
    link_index_locators(res, _cols(ColumnSpec([322], 2, index=True)),
                        say=lambda m: None)
    linked = {t: lk for t, lk in _links(entry.items) if lk}
    assert linked == {"322": "page:322"}


# ------------------------------------------------------------------ container tag

def test_block_class_set_on_entries_not_h1():
    h1 = _p("Index", 322, role="h1")
    entry = _p("Kaʿba, 322", 322)
    res = _result([PageAnchor(322, "322"), h1, entry])
    link_index_locators(res, _cols(ColumnSpec([322], 2, index=True)),
                        say=lambda m: None)
    assert h1.block_class is None        # the section's own title stays untagged
    assert entry.block_class == "index"


def test_role_index_single_column_path():
    entry = _p("Kaʿba, 322", 322, role="index")   # no columns; role opt-in
    res = _result([PageAnchor(322, "322"), entry])
    link_index_locators(res, _cols(), say=lambda m: None)
    assert entry.block_class == "index"
    assert ("322", "page:322") in _links(entry.items)


def test_role_index_bridges_headings_not_body_between_runs():
    # two separate single-column indexes with unrelated body prose between them:
    # the divider heading bridges INSIDE an index; the body prose must NOT be
    # tagged or locator-linked, even though its number matches a real anchor.
    e1 = _p("apple, 33", 33, role="index")
    div = _p("B", 33, role="h2")               # letter-group divider (bridged)
    e2 = _p("banana, 41", 41, role="index")
    body = _p("See page 33 for details.", 60)  # unrelated prose between indexes
    e3 = _p("Qurʾān, 33", 300, role="index")   # a second, separate index
    blocks = [PageAnchor(33, "33"), e1, div, e2, PageAnchor(60, "60"),
              body, PageAnchor(300, "300"), e3]
    res = _result(blocks)
    link_index_locators(res, _cols(), say=lambda m: None)

    assert div.block_class == "index"          # heading bridged into the section
    assert e1.block_class == e2.block_class == e3.block_class == "index"
    assert body.block_class is None            # untouched
    assert _links(body.items) == [("See page 33 for details.", None)]  # not linked
    assert ("33", "page:33") in _links(e1.items)


def test_no_op_without_flag():
    entry = _p("Kaʿba, 322", 322)
    res = _result([PageAnchor(322, "322"), entry])
    link_index_locators(res, _cols(ColumnSpec([322], 2, index=False)),
                        say=lambda m: None)
    assert entry.block_class is None
    assert _links(entry.items) == [("Kaʿba, 322", None)]
    assert res.warns == []


# ------------------------------------------------------------------ emit container

def test_emit_wraps_index_section_and_resolves(tmp_path):
    h1 = _p("Index", 322, role="h1")
    entry = _p("Kaʿba, 322", 322)
    res = _result([PageAnchor(322, "322"), h1, entry])
    cfg = PdfBookConfig(path=tmp_path / "book.yaml")
    cfg.flow_columns = [ColumnSpec([322], 2, index=True)]
    link_index_locators(res, cfg, say=lambda m: None)

    em = Emitter(cfg, res.flow, say=lambda m: None)
    out = em.emit()
    body = "".join(part for f in out.files for part in f.body_parts)
    assert '<section epub:type="index" role="doc-index">' in body
    assert "</section>" in body
    assert 'href="{XREF|page:322}"' in body     # placeholder before resolution

    em.resolve_crossref_links()
    body2 = "".join(part for f in out.files for part in f.body_parts)
    assert "#pg-322" in body2                    # resolved to the real anchor
    assert "{XREF|" not in body2
