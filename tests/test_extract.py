"""parse_page_dict: font interning, flags, baseline grouping, trim clipping."""

from pdf2epub.extract.mupdf import _FontTable, parse_page_dict


def _span(text, font="GADVFL+Gentium", size=11.0, flags=0, bbox=(100, 100, 200, 112),
          color=0x231F20):
    return {"text": text, "font": font, "size": size, "flags": flags,
            "bbox": bbox, "color": color}


def _page(blocks):
    return {"blocks": blocks}


def _text_block(*lines):
    return {"type": 0, "lines": list(lines)}


def _line(*spans, dir=(1.0, 0.0)):
    return {"spans": list(spans), "dir": dir}


TRIM = (24.0, 24.0, 455.0, 672.0)


def test_subset_prefix_stripped_and_fonts_interned():
    table = _FontTable()
    page = _page([_text_block(
        _line(_span("one", font="ABCDEF+Minion", size=11.3)),
        _line(_span("two", font="GHIJKL+Minion", size=11.3, bbox=(100, 120, 200, 132))),
    )])
    lines, _ = parse_page_dict(page, TRIM, table)
    assert len(lines) == 2
    fams = {f.family for f in table.fonts.values()}
    assert fams == {"Minion"}  # same cluster despite different subset prefixes
    assert len(table.fonts) == 1  # same (family, size, color) -> one id


def test_flags_mapped():
    table = _FontTable()
    page = _page([_text_block(_line(
        _span("plain"),
        _span("it", flags=2, bbox=(200, 100, 220, 112)),
        _span("9", flags=1, bbox=(220, 100, 226, 108)),  # superscript marker
        _span("bold", flags=16, bbox=(226, 100, 260, 112)),
    ))])
    lines, _ = parse_page_dict(page, TRIM, table)
    runs = lines[0].runs
    assert [r.italic for r in runs] == [False, True, False, False]
    assert [r.superscript for r in runs] == [False, False, True, False]
    assert [r.bold for r in runs] == [False, False, False, True]


def test_baseline_grouping_merges_folio_fragment():
    # heading and a right-margin folio arrive as separate blocks, same baseline
    table = _FontTable()
    page = _page([
        _text_block(_line(_span("Chapter One", bbox=(150, 80, 280, 95)))),
        _text_block(_line(_span("35", bbox=(400, 80.5, 415, 95)))),
    ])
    lines, _ = parse_page_dict(page, TRIM, table)
    assert len(lines) == 1
    assert lines[0].text() == "Chapter One35"  # runs kept distinct, x-sorted
    assert len(lines[0].runs) == 2


def test_trim_clip_moves_slug_lines_out():
    table = _FontTable()
    page = _page([
        _text_block(_line(_span("body text", bbox=(100, 300, 300, 312)))),
        _text_block(_line(_span("1-Main-text-v8.indd 44  12/7/15",
                                bbox=(30, 680, 200, 690)))),  # below trim bottom
    ])
    lines, clipped = parse_page_dict(page, TRIM, table)
    assert [ln.text() for ln in lines] == ["body text"]
    assert len(clipped) == 1 and ".indd" in clipped[0].text()


def test_vertical_line_not_merged_and_flagged():
    table = _FontTable()
    page = _page([_text_block(
        _line(_span("五", bbox=(400, 100, 415, 115)), dir=(0.0, 1.0)),
        _line(_span("horizontal", bbox=(100, 100, 200, 112))),
    )])
    lines, _ = parse_page_dict(page, TRIM, table)
    assert len(lines) == 2
    assert any(ln.vertical for ln in lines)
    assert any(not ln.vertical for ln in lines)


def test_dominant_font():
    table = _FontTable()
    page = _page([_text_block(_line(
        _span("mostly this font", size=11.0),
        _span("ﷺ", font="FGELLG+Honorifics", size=9.0, bbox=(300, 100, 310, 112)),
    ))])
    lines, _ = parse_page_dict(page, TRIM, table)
    fid = lines[0].dominant_font()
    assert table.fonts[fid].family == "Gentium"


def test_analyze_verse_suspect_evidence():
    # analyze surfaces verse-shaped blocks with measured base/turn offsets
    # (the blocks.verse judgment seed); same detector as the build witness
    from pdf2epub.analyze import analyze
    from test_flow import _doc, _line, _page

    lines = [
        _line("Ordinary prose paragraph at full measure width to", 74,
              x0=72, width=290),
        _line("anchor the leading and the column edges properly.", 87,
              x0=72, width=290),
        _line("I dwell at your door always, like dirt,", 107,
              x0=81, width=170),
        _line("others come and go like the wind.", 120, x0=108, width=160),
        _line("Whoever brings his heart to your door", 133,
              x0=81, width=232),
    ]
    a = analyze(_doc([_page(1, lines)]))
    assert len(a.verse_suspect_pages) == 1
    v = a.verse_suspect_pages[0]
    assert v["page"] == 1 and v["base"] == [9.0] and v["turns"] == [36.0]


def test_page_shift_vetoed_by_global_full_lines():
    # M&R p.165: a near-full-page ghazal outvotes the prose margin for the
    # page-modal left, but full-measure prose anchors still span the GLOBAL
    # column — their presence vetoes the bogus binding shift. A genuinely
    # shifted page (whole block slid, nothing at col_left) keeps its shift.
    from pdf2epub.analyze import column_geometry
    from test_flow import _doc, _line, _page

    anchor = [
        _line("Full measure prose line anchoring the modal column A", 40 + i * 13,
              x0=72, width=290) for i in range(6)]
    ghazal_page = _page(2, [
        _line("Prose one at full measure spanning the global col", 40,
              x0=72, width=290),
        _line("prose two at full measure spanning the global col", 53,
              x0=72, width=290),
        _line("prose three at full measure spanning the global c", 66,
              x0=72, width=290),
        # verse-dense rest: base 82 outvotes 72, one long line near full
        *[_line(f"verse base line number {i} of the long ghazal", 86 + i * 26,
                x0=82, width=200 + (i % 3) * 26) for i in range(4)],
        *[_line(f"verse turn line number {i} going deeper still", 99 + i * 26,
                x0=109, width=190) for i in range(4)],
        _line("a very long verse line reaching almost the column", 210,
              x0=82, width=277),
    ])
    shifted_page = _page(3, [
        _line("Whole block slid to the left by eighteen points aa", 40 + i * 13,
              x0=54, width=290) for i in range(5)])
    geo = column_geometry(_doc([_page(1, anchor), ghazal_page, shifted_page]))
    assert geo.col_left == 72.0
    assert geo.shift(2) == 0.0          # vetoed: global-full prose present
    assert geo.shift(3) == 18.0         # genuine: nothing stands at col_left
