"""Tests for nav.xhtml nesting (_nest), especially heading-level jumps."""

import re

from pdf2epub.core.nav import _nest


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
