"""book.yaml loading: full schema round-trip + unknown-key rejection."""

import pytest

from pdf2epub.config import ConfigError, load_config

FULL = """\
source: {folder: package, pdf: book.pdf, sha256: abc123}
metadata:
  title: T
  creators: [{name: A, role: aut}]
  publisher: Somebody
  language: en
  additional_languages: [ar]
  isbn_print: 978-1-887752-52-8
  cover: assets/cover.jpg
  cover_render: {page: 1, box: trim, dpi: 300}
pages:
  cover: [1]
  front: {first: 2, last: 20}
  body: {first: 21, last: 300}
  exclude: [2]
  label_source: printed-folios
  label_overrides: {5: v}
  role_overrides: [{page: 4, role: title-page}]
furniture: {top_band: 60, repeat_min_pages: 3, extra: ["book title"], keep: []}
styles:
  body_pstyle: "Minion@11.3"
  pstyle_map:
    "Minion@11.3": {role: p}
    "Minion@12/center": h2
  charstyles:
    Bembo-SC: {smallcaps: true}
    Honorifics: {symbol: true}
  fail_on_unmapped: true
flow:
  indent_threshold: 10
  dehyphenate: lower-only
  restore_spaces: true
  overrides:
    - {page: 44, line: 12, action: "break", note: evidence}
    - {page: 50, line: 3, action: "role:blockquote", note: verse}
footnotes: {policy: markers, marker: asterisk}
toc: {source: printed, printed_pages: [6, 7], nav_depth: 2}
glyphs:
  pua_map:
    "\\uF048": {action: char, char: "\\uFDFA", lang: ar, note: verified p.44}
    "\\uF0A7": {action: drop, note: ornament}
  fail_on_unmapped_pua: true
fonts:
  embed:
    - {family: Amiri, file: /usr/share/fonts/amiri-fonts/Amiri-Regular.ttf, script: cjk, lang: ar}
  subset: true
languages: {cjk_han_only: zh}
split: {at_roles: [h1]}
images:
  raster_dpi: 300
  figure_pages: [{pages: ["88-90", 92], alt_template: "Page {label}", lang: zh}]
output: {slug: my-book}
"""


def test_full_config_round_trip(tmp_path):
    p = tmp_path / "book.yaml"
    p.write_text(FULL)
    cfg = load_config(p)
    assert cfg.title == "T"
    assert cfg.publisher == "Somebody"
    assert cfg.body_style == "Minion@11.3"  # alias for forked emit_css
    assert cfg.pstyle_map["Minion@12/center"].role == "h2"
    assert cfg.charstyles["Bembo-SC"].smallcaps
    assert cfg.pages_front.first == 2 and 300 in cfg.pages_body
    assert cfg.label_overrides == {5: "v"}
    assert cfg.flow_overrides[1].action == "role:blockquote"
    assert cfg.pua_map[""].char == "ﷺ"
    assert cfg.figure_pages[0].pages == [88, 89, 90, 92]
    assert cfg.in_flow_pages(5) == [3, 4, 5]  # cover 1 + excluded 2 dropped
    assert cfg.fonts_embed[0].lang == "ar"
    assert cfg.sha256 == "abc123"


@pytest.mark.parametrize("snippet,err", [
    ("source: {folder: p, pdf: b.pdf}\nstyles: {body_style: x}", "unknown key"),
    ("source: {folder: p, pdf: b.pdf}\nflow: {overrides: [{page: 1, line: 2, action: nope}]}",
     "action invalid"),
    ("source: {folder: p, pdf: b.pdf}\ntoc: {source: bookmarks}", "toc.source invalid"),
    ("source: {folder: p, pdf: b.pdf}\nglyphs: {pua_map: {\"\\uF048\": {action: char}}}",
     "requires 'char'"),
    ("source: {folder: p}", "source.pdf is required"),
])
def test_rejections(tmp_path, snippet, err):
    p = tmp_path / "book.yaml"
    p.write_text(snippet)
    with pytest.raises(ConfigError, match=err):
        load_config(p)


def test_flow_columns_parsing(tmp_path):
    p = tmp_path / "book.yaml"
    p.write_text(
        "source: {folder: p, pdf: b.pdf}\n"
        "flow:\n"
        "  columns:\n"
        "    - {pages: [322, 323], count: 3, note: quran index}\n"
        "    - {pages: [\"324-326\"], count: 2}\n")
    cfg = load_config(p)
    assert cfg.flow_columns[0].pages == [322, 323]
    assert cfg.flow_columns[0].count == 3
    assert cfg.flow_columns[1].pages == [324, 325, 326]
    with pytest.raises(ConfigError, match="count must be >= 2"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "flow: {columns: [{pages: [1], count: 1}]}")
        load_config(p)
    with pytest.raises(ConfigError, match="unknown key"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "flow: {columns: [{pages: [1], count: 2, gutter: 10}]}")
        load_config(p)
