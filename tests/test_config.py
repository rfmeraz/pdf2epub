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


def test_fffd_repairs_parsing(tmp_path):
    p = tmp_path / "book.yaml"
    p.write_text(
        "source: {folder: p, pdf: b.pdf}\n"
        "glyphs:\n"
        "  fffd_repairs:\n"
        "    - {pages: [\"36-38\", 41], replace: \"\", note: render-verified blank}\n")
    cfg = load_config(p)
    assert cfg.fffd_repairs[0].pages == [36, 37, 38, 41]
    assert cfg.fffd_repairs[0].replace == ""
    with pytest.raises(ConfigError, match="requires a note"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "glyphs: {fffd_repairs: [{pages: [1], replace: \"\"}]}")
        load_config(p)
    with pytest.raises(ConfigError, match='requires "replace"'):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "glyphs: {fffd_repairs: [{pages: [1], note: n}]}")
        load_config(p)
    with pytest.raises(ConfigError, match="unknown key"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "glyphs: {fffd_repairs: [{pages: [1], replace: x, note: n, "
                     "font: y}]}")
        load_config(p)


def test_figure_regions_parsing(tmp_path):
    p = tmp_path / "book.yaml"
    p.write_text(
        "source: {folder: p, pdf: b.pdf}\n"
        "images:\n"
        "  figure_regions:\n"
        "    - {page: 26, rect: [70, 319, 367, 567], alt: legend table}\n")
    cfg = load_config(p)
    assert cfg.figure_regions[0].page == 26
    assert cfg.figure_regions[0].rect == (70.0, 319.0, 367.0, 567.0)
    with pytest.raises(ConfigError, match="requires alt"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "images: {figure_regions: [{page: 1, rect: [0, 0, 9, 9]}]}")
        load_config(p)
    with pytest.raises(ConfigError, match="rect must be"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "images: {figure_regions: [{page: 1, rect: [9, 0, 0, 9], alt: x}]}")
        load_config(p)


def test_blocks_verse_parsing(tmp_path):
    p = tmp_path / "book.yaml"
    p.write_text(
        "source: {folder: p, pdf: b.pdf}\n"
        "blocks:\n"
        "  verse:\n"
        "    - {pages: [\"28-30\", 35], base: [9], turns: [36], note: couplets}\n")
    cfg = load_config(p)
    assert cfg.blocks_verse[0].pages == [28, 29, 30, 35]
    assert cfg.blocks_verse[0].base == [9.0]
    assert cfg.blocks_verse[0].turns == [36.0]
    assert cfg.blocks_verse[0].tol == 2.0
    assert cfg.blocks_verse[0].stanza_gap == 1.4
    with pytest.raises(ConfigError, match="requires a note"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "blocks: {verse: [{pages: [1], base: [9], turns: [36]}]}")
        load_config(p)
    # turns is OPTIONAL (single-level I&B-style verse); base is required
    p.write_text("source: {folder: p, pdf: b.pdf}\n"
                 "blocks: {verse: [{pages: [1], base: [18], note: n}]}")
    assert load_config(p).blocks_verse[0].turns == []
    with pytest.raises(ConfigError, match="requires base"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "blocks: {verse: [{pages: [1], turns: [9], note: n}]}")
        load_config(p)
    with pytest.raises(ConfigError, match="unknown key"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "blocks: {verse: [{pages: [1], base: [9], turns: [36], "
                     "indent: 3, note: n}]}")
        load_config(p)
    # verse pages must not overlap flow.columns / figure_pages
    with pytest.raises(ConfigError, match="overlap"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "flow: {columns: [{pages: [35], count: 2, note: n}]}\n"
                     "blocks: {verse: [{pages: [35], base: [9], turns: [36], "
                     "note: n}]}")
        load_config(p)


def test_blocks_quotes_parsing(tmp_path):
    p = tmp_path / "book.yaml"
    p.write_text(
        "source: {folder: p, pdf: b.pdf}\n"
        "blocks:\n"
        "  quotes:\n"
        "    - {pages: [\"16-18\", 51], left_inset: 18, right_inset: 18,\n"
        "       note: I&B inset quotes}\n")
    cfg = load_config(p)
    assert cfg.blocks_quotes[0].pages == [16, 17, 18, 51]
    assert cfg.blocks_quotes[0].left_inset == 18.0
    assert cfg.blocks_quotes[0].right_inset == 18.0
    assert cfg.blocks_quotes[0].tol == 3.0
    # right_inset is OPTIONAL (BoK-style left-only inset, right = body edge)
    p.write_text("source: {folder: p, pdf: b.pdf}\n"
                 "blocks: {quotes: [{pages: [40], left_inset: 36, note: n}]}")
    assert load_config(p).blocks_quotes[0].right_inset == 0.0
    with pytest.raises(ConfigError, match="requires a note"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "blocks: {quotes: [{pages: [1], left_inset: 18}]}")
        load_config(p)
    # a quote at the body left edge has no detectable shape
    with pytest.raises(ConfigError, match="left_inset must be"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "blocks: {quotes: [{pages: [1], right_inset: 18, "
                     "note: n}]}")
        load_config(p)
    with pytest.raises(ConfigError, match="unknown key"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "blocks: {quotes: [{pages: [1], left_inset: 18, "
                     "indent: 3, note: n}]}")
        load_config(p)
    with pytest.raises(ConfigError, match="overlap"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "flow: {columns: [{pages: [35], count: 2, note: n}]}\n"
                     "blocks: {quotes: [{pages: [35], left_inset: 18, "
                     "note: n}]}")
        load_config(p)


def test_class_override_verbs(tmp_path):
    p = tmp_path / "book.yaml"
    p.write_text("source: {folder: p, pdf: b.pdf}\n"
                 "flow: {overrides: ["
                 "{page: 1, line: 2, action: \"class:verse\", note: n},"
                 " {page: 1, line: 3, action: \"class:prose\", note: n},"
                 " {page: 1, line: 4, action: \"class:quote\", note: n}]}")
    cfg = load_config(p)
    assert cfg.flow_overrides[0].action == "class:verse"
    assert cfg.flow_overrides[1].action == "class:prose"
    assert cfg.flow_overrides[2].action == "class:quote"
    with pytest.raises(ConfigError, match="action invalid"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "flow: {overrides: [{page: 1, line: 2, "
                     "action: \"class:poem\"}]}")
        load_config(p)


def test_blocks_lists_parsing(tmp_path):
    p = tmp_path / "book.yaml"
    p.write_text(
        "source: {folder: p, pdf: b.pdf}\n"
        "blocks:\n"
        "  lists:\n"
        "    - {pages: [\"337-373\"], marker: decimal, hang: 27,\n"
        "       note: notes apparatus}\n")
    cfg = load_config(p)
    assert cfg.blocks_lists[0].pages[0] == 337
    assert cfg.blocks_lists[0].marker == "decimal"
    assert cfg.blocks_lists[0].hang == 27.0
    with pytest.raises(ConfigError, match="marker invalid"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "blocks: {lists: [{pages: [1], marker: roman, "
                     "note: n}]}")
        load_config(p)
    with pytest.raises(ConfigError, match="requires a note"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "blocks: {lists: [{pages: [1], marker: bullet}]}")
        load_config(p)
    with pytest.raises(ConfigError, match="overlap"):
        p.write_text("source: {folder: p, pdf: b.pdf}\n"
                     "flow: {columns: [{pages: [35], count: 2, note: n}]}\n"
                     "blocks: {lists: [{pages: [35], marker: decimal, "
                     "note: n}]}")
        load_config(p)
