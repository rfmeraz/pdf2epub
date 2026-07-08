"""Mini CSS resolver over the shapes emit_css.py actually generates."""

from pdf2epub.core.qa_cssresolve import (effective_font_size_em,
                                         parse_stylesheet, resolve_block)

SHEET = """\
@font-face {
  font-family: "Gentium Book Plus";
  font-style: normal;
  src: url("../font/GentiumBookPlus.woff2");
}
html, body { margin: 0; padding: 0; }
p { margin: 0; text-indent: 1.2em; text-align: justify; }
p.first, p.first-dropcap { text-indent: 0; }
p.first-dropcap::first-letter { float: left; font-size: 2.6em; }
h1, h2, h3 { font-weight: normal; text-align: center; }
blockquote p { text-indent: 0; }
p.caption { text-indent: 0; text-align: center; font-size: 0.9em; }
.Minion-9 { font-size: 0.818em; }
.Minion-22 { font-size: 2.000em; }
.Minion-11-center { text-align: center; text-indent: 0; }
.Minion-Italic-11 { font-style: italic; }
span.smallcaps { font-variant: small-caps; }
:lang(zh), span.zh { font-family: "Noto Serif CJK SC", serif; }
"""


def _rules():
    return parse_stylesheet(SHEET)


def test_tag_defaults_and_provenance():
    rules = _rules()
    got = resolve_block(rules, "p", set())
    assert got["text-align"] == ("justify", "tag")
    assert got["text-indent"] == ("1.2em", "tag")
    got = resolve_block(rules, "h2", set())
    assert got["text-align"] == ("center", "tag")


def test_class_beats_tag():
    rules = _rules()
    got = resolve_block(rules, "p", {"Minion-11-center"})
    assert got["text-align"] == ("center", "class:Minion-11-center")
    assert got["text-indent"] == ("0", "class:Minion-11-center")


def test_tag_class_beats_bare_class():
    # p.caption (1 class, 1 type) must beat .Minion-9 (1 class, 0 type)
    rules = _rules()
    got = resolve_block(rules, "p", {"caption", "Minion-9"})
    assert got["font-size"] == ("0.9em", "class:caption")


def test_ignored_selectors():
    rules = _rules()
    # ::first-letter, :lang(), @font-face never produce rules
    assert not any("float" in r.props for r in rules)
    assert not any("src" in r.props for r in rules)
    assert not any(r.props.get("font-family", "").startswith('"Noto')
                   and r.tag is None for r in rules)


def test_blockquote_descendant():
    rules = _rules()
    got = resolve_block(rules, "p", set(), ancestors=(("blockquote", set()),))
    assert got["text-indent"][0] == "0"
    # without the ancestor, base indent applies
    assert resolve_block(rules, "p", set())["text-indent"][0] == "1.2em"


def test_effective_font_size():
    rules = _rules()
    assert effective_font_size_em(rules, "p", set()) == 1.0
    assert effective_font_size_em(rules, "p", {"Minion-22"}) == 2.0
    assert effective_font_size_em(rules, "p", {"Minion-9"}) == 0.818
    # unstyled class -> 1.0 (a missing rule is exactly what gate 13 hunts)
    assert effective_font_size_em(rules, "p", {"Ghost-14"}) == 1.0
    # ancestor multiply (defensive: our blockquote carries no size today)
    extra = parse_stylesheet("blockquote { font-size: 0.9em; }")
    assert abs(effective_font_size_em(rules + extra, "p", {"Minion-9"},
               ancestors=(("blockquote", set()),)) - 0.818 * 0.9) < 1e-9


def test_font_style_and_variant():
    rules = _rules()
    assert resolve_block(rules, "p", {"Minion-Italic-11"})["font-style"][0] == "italic"
    assert resolve_block(rules, "span", {"smallcaps"})["font-variant"][0] == "small-caps"
