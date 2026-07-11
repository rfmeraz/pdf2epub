"""Tests for the imprint transforms (pdf2epub.imprints).

Focus: the World Wisdom Editor's Notes relinker — leading print page numbers ->
#pg-<label> anchors (carry-forward), and "Note N" -> the resolved global author
footnote (chapter-aware, since the EPUB renumbers footnotes globally). Plus the
generic RunFormat.link plumbing and its emit-time resolution.
"""

from collections import Counter

import pytest

from pdf2epub.core.emit_xhtml import Emitter, OutFile, _run_html
from pdf2epub.core.model import (
    FlowDoc,
    InlinePageBreak,
    NoteRef,
    PageAnchor,
    Paragraph,
    RunFormat,
    SourceRef,
    TextRun,
)
from pdf2epub.flowbuilder import FlowResult
from pdf2epub.imprints import apply_imprint, parse_imprint
from pdf2epub.imprints import world_wisdom as ww


# ------------------------------------------------------------------ helpers

def _p(runs, role=None, style="s"):
    """Paragraph from a list of (text, bold) tuples or a plain string."""
    if isinstance(runs, str):
        runs = [(runs, False)]
    items = [TextRun(t, RunFormat(bold=b)) for t, b in runs]
    return Paragraph(style=style, items=items, src=SourceRef("st", 0), role=role)


def _result(blocks, notes=None):
    flow = FlowDoc(blocks=blocks, notes=notes or {}, style_usage=Counter(),
                   text_dests={})
    return FlowResult(flow=flow)


def _spec(heading="Editor's Notes", page=True, notes=True):
    return ww.EditorsNotesSpec(heading=heading, link_page_refs=page,
                               link_footnote_refs=notes, body_backlinks="off")


def _links(items):
    return [(it.text, it.fmt.link) for it in items if isinstance(it, TextRun)]


# ------------------------------------------------------------------ _norm

def test_norm_folds_apostrophe_case_and_punctuation():
    assert ww._norm("EDITOR’S NOTES") == ww._norm("Editor's Notes")
    assert ww._norm("Editor's Notes") == "editors notes"


def test_norm_folds_hyphen_and_diacritics():
    assert ww._norm("The Exo-Esoteric Symbiosis") == "the exoesoteric symbiosis"
    assert ww._norm("Esoterisḿ") == "esoterism"  # combining acute dropped


# ------------------------------------------------------------------ _apply_link

def test_apply_link_isolates_span_within_one_run():
    items = [TextRun("4: Note 2: text", RunFormat(bold=True))]
    out = ww._apply_link(items, 0, 1, "page:4")
    assert _links(out) == [("4", "page:4"), (": Note 2: text", None)]
    assert "".join(t for t, _ in _links(out)) == "4: Note 2: text"  # text intact


def test_apply_link_spans_run_boundary():
    items = [TextRun("Not", RunFormat()), TextRun("e 2: rest", RunFormat())]
    out = ww._apply_link(items, 0, 6, "note:x")  # "Note 2"
    linked = [t for t, ln in _links(out) if ln == "note:x"]
    assert "".join(linked) == "Note 2"
    assert "".join(t for t, _ in _links(out)) == "Note 2: rest"


def test_apply_link_stable_under_successive_calls():
    # page link then note link, both keyed off ORIGINAL offsets
    items = [TextRun("4", RunFormat(bold=True)), TextRun(": Note 2: x")]
    flat = ww._flat(items)
    items = ww._apply_link(items, 0, 1, "page:4")
    i = flat.index("Note 2")
    items = ww._apply_link(items, i, i + 6, "note:n2")
    got = {ln for _, ln in _links(items) if ln}
    assert got == {"page:4", "note:n2"}


# ------------------------------------------------------------------ _is_bold_range

def test_is_bold_range():
    items = [TextRun("4", RunFormat(bold=True)), TextRun(": rest", RunFormat())]
    assert ww._is_bold_range(items, 0, 1) is True
    assert ww._is_bold_range(items, 0, 3) is False  # extends into non-bold
    assert ww._is_bold_range([TextRun("4", RunFormat())], 0, 1) is False


# ------------------------------------------------------------------ _footnote_map

def test_footnote_map_resets_per_chapter():
    blocks = [
        _p("Chapter A", role="h1"),
        Paragraph("s", [TextRun("x"), NoteRef("a1"), TextRun("y"), NoteRef("a2")],
                  SourceRef("st", 0)),
        PageAnchor(1, "2"),
        _p("Chapter B", role="h1"),
        Paragraph("s", [NoteRef("b1")], SourceRef("st", 0)),
    ]
    fnmap, labels = ww._footnote_map(blocks)
    assert fnmap[("chapter a", 1)] == "a1"
    assert fnmap[("chapter a", 2)] == "a2"
    assert fnmap[("chapter b", 1)] == "b1"  # counter reset at the new h1
    assert "2" in labels


# ------------------------------------------------------------------ _section_bounds

def test_section_bounds_between_h1s():
    blocks = [
        _p("Some Chapter", role="h1"),
        _p("body"),
        _p("EDITOR’S NOTES", role="h1"),
        _p("note a"),
        _p("note b"),
        _p("Index", role="h1"),
        _p("index entry"),
    ]
    assert ww._section_bounds(blocks, "Editor's Notes") == (2, 5)
    assert ww._section_bounds(blocks, "Nonexistent") is None


# ------------------------------------------------------------------ end-to-end

def _sufism_like_blocks():
    chap = "Ellipsis and Hyperbolism in Arab Rhetoric"
    return [
        # body chapter with two footnotes -> fn map (chap,1)->n1 (chap,2)->n2
        _p(chap, role="h1"),
        PageAnchor(20, "2"),
        Paragraph("s", [TextRun("body "), NoteRef("n1")], SourceRef("st", 0)),
        PageAnchor(22, "4"),
        Paragraph("s", [TextRun("more "), NoteRef("n2")], SourceRef("st", 0)),
        # back-matter Editor's Notes section
        _p("EDITOR’S NOTES", role="h1"),
        _p(chap, role="h3"),
        _p([("2", True), (": unconsidered oaths", False)]),           # page 2
        _p("continuation with no leading number"),                     # carries 2
        _p([("4", True), (": Note 2: ", False), ("citation", False)]),  # page 4 + Note 2
    ]


def test_link_editors_notes_end_to_end():
    blocks = _sufism_like_blocks()
    res = _result(blocks)
    ww._link_editors_notes(res, _spec(), say=lambda *a: None)

    # page 2 entry linked, continuation untouched, page 4 + Note 2 both linked
    en = blocks[7].items
    assert ("2", "page:2") in _links(en)
    assert all(ln is None for _, ln in _links(blocks[8].items))  # continuation
    en4 = _links(blocks[9].items)
    assert ("4", "page:4") in en4
    assert ("Note 2", "note:n2") in en4
    assert not res.warns  # everything resolved


def test_note_ref_resolves_chapter_aware():
    # Note 2 under the Ellipsis chapter must map to that chapter's 2nd footnote
    blocks = _sufism_like_blocks()
    res = _result(blocks)
    ww._link_editors_notes(res, _spec(), say=lambda *a: None)
    note_links = [ln for _, ln in _links(blocks[9].items) if ln == "note:n2"]
    assert note_links == ["note:n2"]


def test_unresolved_page_and_note_warn_but_ship_plain():
    chap = "Ellipsis and Hyperbolism in Arab Rhetoric"
    blocks = [
        _p(chap, role="h1"),
        Paragraph("s", [NoteRef("n1")], SourceRef("st", 0)),  # only ONE footnote
        _p("EDITOR’S NOTES", role="h1"),
        _p(chap, role="h3"),
        _p([("99", True), (": missing page", False)]),          # no pg-99 anchor
        _p([("5", True), (": Note 8: x", False)]),              # no 8th footnote
    ]
    # page 5 has no anchor either -> both entries warn
    res = _result(blocks)
    ww._link_editors_notes(res, _spec(), say=lambda *a: None)
    # nothing linked
    assert all(ln is None for b in blocks[4:6] if isinstance(b, Paragraph) for _, ln in _links(b.items))
    codes = {w.code for w in res.warns}
    assert codes == {"imprint-note-unlinked"}
    assert len(res.warns) >= 2


def test_disable_flags_skip_linking():
    blocks = _sufism_like_blocks()
    res = _result(blocks)
    ww._link_editors_notes(res, _spec(page=False, notes=False),
                           say=lambda *a: None)
    assert all(ln is None for b in blocks if isinstance(b, Paragraph) for _, ln in _links(b.items))


def test_missing_section_warns_and_noops():
    blocks = [_p("Some Chapter", role="h1"), _p("body text")]
    res = _result(blocks)
    ww._link_editors_notes(res, _spec(), say=lambda *a: None)
    assert all(ln is None for b in blocks if isinstance(b, Paragraph) for _, ln in _links(b.items))
    assert res.warns and res.warns[0].code == "imprint-note-unlinked"


# ------------------------------------------------------------------ config parse

def test_parse_imprint_valid():
    spec = parse_imprint({"name": "world-wisdom",
                          "editors_notes": {"heading": "Editor's Notes"}})
    assert spec.name == "world-wisdom"
    en = spec.options.editors_notes
    assert en.link_page_refs is True and en.body_backlinks == "off"


def test_parse_imprint_rejects_unknown_name():
    from pdf2epub.config import ConfigError
    with pytest.raises(ConfigError):
        parse_imprint({"name": "penguin"})


def test_parse_imprint_rejects_unknown_subkey():
    from pdf2epub.config import ConfigError
    with pytest.raises(ConfigError):
        parse_imprint({"name": "world-wisdom", "editors_notes": {"bogus": 1}})


def test_parse_imprint_body_backlinks_bool_coercion():
    # YAML `off` -> False must become the "off" mode, not crash
    spec = parse_imprint({"name": "world-wisdom",
                          "editors_notes": {"body_backlinks": False}})
    assert spec.options.editors_notes.body_backlinks == "off"


def test_parse_imprint_rejects_unimplemented_backlinks():
    from pdf2epub.config import ConfigError
    with pytest.raises(ConfigError):
        parse_imprint({"name": "world-wisdom",
                       "editors_notes": {"body_backlinks": "lemma-exact"}})


# ------------------------------------------------------------------ no-op guard

def test_apply_imprint_noop_without_config():
    from pathlib import Path

    from pdf2epub.config import PdfBookConfig
    cfg = PdfBookConfig(path=Path("x"))  # imprint defaults to None
    blocks = [_p("EDITOR’S NOTES", role="h1"),
              _p([("2", True), (": text", False)])]
    res = _result(blocks)
    apply_imprint(res, cfg, None, say=lambda *a: None)
    assert all(ln is None for b in blocks if isinstance(b, Paragraph) for _, ln in _links(b.items))


# ------------------------------------------------------------------ emit plumbing

def test_run_html_wraps_linked_run():
    html = _run_html(TextRun("4", RunFormat(bold=True, link="page:4")))
    assert html == '<a class="xref xref-page" href="{XREF|page:4}"><b>4</b></a>'


def _emitter_with_files(files):
    em = Emitter.__new__(Emitter)  # bypass PDF-heavy __init__
    em.files = files
    em._note_order = ["nA", "nB"]  # global fn1, fn2
    em._notes_out = None
    em.warnings = []
    return em


def test_resolve_crossref_links_resolves_page_and_note():
    body = OutFile("f007", "007-chap.xhtml", "Chap")
    body.pagebreaks = [("4", "pg-4")]
    notes = OutFile("f015", "015-notes.xhtml", "Notes")
    notes.body_parts = [
        '<p><a class="xref xref-page" href="{XREF|page:4}"><b>4</b></a>: '
        '<a class="xref xref-note" href="{XREF|note:nB}">Note 2</a></p>'
    ]
    em = _emitter_with_files([body, notes])
    em.resolve_crossref_links()
    out = notes.body_parts[0]
    assert 'href="007-chap.xhtml#pg-4"' in out
    assert 'href="notes.xhtml#fn2"' in out  # nB is 2nd in _note_order
    assert "XREF" not in out
    assert not em.warnings


def test_resolve_crossref_links_unwraps_unresolvable():
    f = OutFile("f015", "015-notes.xhtml", "Notes")
    f.body_parts = ['<p><a class="xref xref-page" href="{XREF|page:999}">'
                    '<b>999</b></a>: text</p>']
    em = _emitter_with_files([f])
    em.resolve_crossref_links()
    out = f.body_parts[0]
    assert out == "<p><b>999</b>: text</p>"  # anchor unwrapped, text kept
    assert em.warnings  # reported
