"""Tests for nav.xhtml nesting (_nest), especially heading-level jumps."""

import re
from types import SimpleNamespace

from pdf2epub.core.emit_xhtml import EmitResult, OutFile
from pdf2epub.core.nav import (
    _nest,
    _toc_entries,
    build_nav_xhtml,
    is_numeric_nav_title,
)
from pdf2epub.core.packager import _ncx


def _tree(entries):
    """Render _nest and return an indent-per-depth outline of titles, so the
    parent/child structure is asserted without matching exact tag soup."""
    html = _nest([(lvl, t, f"f#{t}") for lvl, t in entries])
    depth = 0
    out = []
    for tok in re.findall(r"<ol>|</ol>|<a[^>]*>([^<]*)</a>", html):
        pass
    # walk tokens preserving order
    depth = 0
    for tok in re.finditer(r"<ol>|</ol>|<li>|<a[^>]*>([^<]*)</a>", html):
        s = tok.group(0)
        if s == "<ol>":
            depth += 1
        elif s == "</ol>":
            depth -= 1
        elif s.startswith("<a"):
            out.append((depth, tok.group(1)))
    return out, html


def _wellformed(html):
    # tags balance
    return (html.count("<ol>") == html.count("</ol>")
            and html.count("<li>") == html.count("</li>"))


def test_same_level_after_jump_are_siblings():
    # the Sufism editor's-notes bug: EDITOR'S NOTES (h1) then several h3 subheads
    entries = [(1, "EDITORS NOTES"), (3, "Preface"), (3, "Ellipsis"),
               (3, "Exo-Esoteric"), (2, "Glossary")]
    tree, html = _tree(entries)
    assert _wellformed(html)
    d = {t: depth for depth, t in tree}
    # Preface and the chapters sit at the SAME depth (siblings under EN)
    assert d["Preface"] == d["Ellipsis"] == d["Exo-Esoteric"]
    # and one deeper than EDITOR'S NOTES (nested under it, not flat)
    assert d["Preface"] == d["EDITORS NOTES"] + 1


def test_standard_h1_h2_h3_nesting():
    entries = [(1, "A"), (2, "A1"), (3, "A1a"), (2, "A2"), (1, "B")]
    tree, html = _tree(entries)
    assert _wellformed(html)
    d = {t: depth for depth, t in tree}
    assert d["A"] == d["B"]              # h1 siblings
    assert d["A1"] == d["A2"] == d["A"] + 1
    assert d["A1a"] == d["A1"] + 1
    assert d["B"] == d["A"]


def test_first_heading_deeper_than_h1_is_top_level():
    # a document whose first heading is h2 must not emit <ol> directly in <ol>
    tree, html = _tree([(2, "X"), (2, "Y")])
    assert _wellformed(html)
    assert not re.search(r"<ol>\s*<ol>", html)
    d = {t: depth for depth, t in tree}
    assert d["X"] == d["Y"]  # siblings at the top


def test_jump_down_lands_as_sibling():
    # h1, h3, then h2: a nav <li> allows only ONE child <ol>, so h2 (shallower
    # than h3 but deeper than h1) joins h3's <ol> as a sibling under A, not a
    # second <ol> in A's <li>
    tree, html = _tree([(1, "A"), (3, "Aa"), (2, "Ab")])
    assert _wellformed(html)
    d = {t: depth for depth, t in tree}
    assert d["Aa"] == d["Ab"] == d["A"] + 1  # both children of A, siblings


def test_no_second_ol_in_one_li():
    # the exact epubcheck failure: EDITOR'S NOTES(h1) > h3 chapters, then
    # GLOSSARY(h2) must NOT open a second <ol> inside EN's <li>
    entries = [(1, "EN"), (3, "Preface"), (3, "Ellipsis"), (3, "Appendix"),
               (2, "GLOSSARY"), (1, "INDEX")]
    tree, html = _tree(entries)
    assert _wellformed(html)
    assert "</ol><ol>" not in html  # would be two ols as siblings (invalid)
    assert "<ol><ol>" not in html
    d = {t: depth for depth, t in tree}
    assert d["Preface"] == d["Ellipsis"] == d["GLOSSARY"] == d["EN"] + 1
    assert d["INDEX"] == d["EN"]  # back to top level


def test_empty_entries():
    assert _nest([]) == "<ol></ol>"


# --------------------------------------------------------------------------
# numeric-only nav filter (toc.drop_numeric_nav_entries)
# --------------------------------------------------------------------------

def test_is_numeric_nav_title():
    # bare passage/appendix numbers a printed Contents never lists — dropped
    for t in ("1.", "2.", "254.", "19.*", "22", "  7.  "):
        assert is_numeric_nav_title(t), t
    # lettered titles — always kept (never eaten by the filter)
    for t in ("Childhood", "Part 2.", "part 1", "Part 3",
              "Notes to the Passages", "1.2.3", "1a", ""):
        assert not is_numeric_nav_title(t), t


def _file(name, headings):
    return OutFile(file_id=name, file_name=f"{name}.xhtml", title=name,
                   body_parts=[], headings=headings, pagebreaks=[], landmark=None)


# one file mixing real section titles with bare passage numbers, in doc order
_MIXED = [_file("c", [
    ("h1", "h1", "Part One"),
    ("h3", "h2", "Childhood"),
    ("h3", "h3", "1."),
    ("h3", "h4", "2."),
    ("h3", "h5", "My Teaching Career"),
    ("h3", "h6", "19.*"),
    ("h3", "h7", "12."),
    ("h3", "h8", "Part 2."),
])]

# the exact (level, title, href) survivors once numerics are dropped
_SURVIVORS = [
    (1, "Part One", "c.xhtml#h1"),
    (3, "Childhood", "c.xhtml#h2"),
    (3, "My Teaching Career", "c.xhtml#h5"),
    (3, "Part 2.", "c.xhtml#h8"),
]


def test_toc_entries_drop_numeric_exact_sequence():
    # drop_numeric=True yields exactly the lettered entries, order preserved,
    # dropped headings' hids skipped (they still exist in the body)
    assert _toc_entries(_MIXED, drop_numeric=True) == _SURVIVORS


def test_toc_entries_default_keeps_everything():
    # default (False) reproduces every heading verbatim — the byte-identical
    # path every other book relies on
    got = _toc_entries(_MIXED)
    assert [t for _, t, _ in got] == [
        "Part One", "Childhood", "1.", "2.", "My Teaching Career",
        "19.*", "12.", "Part 2."]
    assert _toc_entries(_MIXED, drop_numeric=False) == got


def _cfg(drop):
    return SimpleNamespace(
        toc_drop_numeric_nav_entries=drop, language="en", title="T",
        identifier="test-id", isbn_epub="")


def _nav_seq(xml):
    """(title, href) pairs from the doc-toc nav only (not page-list/landmarks)."""
    toc = xml.split('epub:type="toc"', 1)[1].split("</nav>", 1)[0]
    return list(zip(re.findall(r"<a [^>]*>(.*?)</a>", toc),
                    re.findall(r'<a href="(.*?)"', toc)))


def _ncx_seq(xml):
    """(title, href) pairs from the ncx navMap."""
    return list(zip(re.findall(r"<navLabel><text>(.*?)</text></navLabel>", xml),
                    re.findall(r'<content src="(.*?)"/>', xml)))


def test_nav_and_ncx_sequences_match_and_drop_numeric():
    result = EmitResult(files=_MIXED, notes_file=None, noteref_count=0, warnings=[])
    nav = _nav_seq(build_nav_xhtml(result, _cfg(True), has_cover=False))
    ncx = _ncx_seq(_ncx(_cfg(True), result))
    expected = [(t, h) for _, t, h in _SURVIVORS]
    assert nav == expected            # exact title+href sequence, numerics gone
    assert ncx == expected
    assert nav == ncx                 # nav and ncx never diverge


def test_nav_default_keeps_numeric():
    result = EmitResult(files=_MIXED, notes_file=None, noteref_count=0, warnings=[])
    nav = _nav_seq(build_nav_xhtml(result, _cfg(False), has_cover=False))
    assert [t for t, _ in nav] == [
        "Part One", "Childhood", "1.", "2.", "My Teaching Career",
        "19.*", "12.", "Part 2."]
