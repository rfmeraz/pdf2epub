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
    from test_flow import _doc, _line, _page

    from pdf2epub.analyze import analyze

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
    from test_flow import _doc, _line, _page

    from pdf2epub.analyze import column_geometry

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


# ---- TrimBox must land in the same space as the text (chapter-opening folios)

def _fitz_page(media, crop, trim):
    """A stand-in with the geometry fitz derives for these boxes: rect is the
    CROPBOX at origin 0; transformation_matrix flips y about the MEDIABOX."""
    import fitz

    class _P:
        mediabox = fitz.Rect(*media)
        cropbox = fitz.Rect(*crop)
        trimbox = fitz.Rect(*trim)
        rect = fitz.Rect(0, 0, crop[2] - crop[0], crop[3] - crop[1])
        transformation_matrix = fitz.Matrix(1, 0, 0, -1, -crop[0],
                                            media[1] + media[3])
    return _P()


def test_trim_in_text_space_conventional_pdf_is_unchanged():
    """CropBox == MediaBox: the trim already lands on its text — no-op."""
    from pdf2epub.extract.mupdf import trim_in_text_space
    page = _fitz_page(media=(0, 0, 432, 648), crop=(0, 0, 432, 648),
                      trim=(0, 0, 432, 648))
    assert trim_in_text_space(page) == (0.0, 0.0, 432.0, 648.0)


def test_trim_in_text_space_offset_cropbox_is_reanchored():
    """Keys (calibre): CropBox y0=9 sits ABOVE MediaBox y0=24. The
    MediaBox-referenced matrix would put the trim 24pt below the text it
    bounds — pushing chapter-opening drop folios out of the folio band, whose
    unstripped 10pt line then broke the 9pt footnote-region walk."""
    from pdf2epub.extract.mupdf import trim_in_text_space
    page = _fitz_page(media=(24, 24, 474, 690), crop=(36.6, 9, 468.6, 657),
                      trim=(36.6, 9, 468.6, 657))
    x0, y0, x1, y1 = trim_in_text_space(page)
    # the trim must equal page.rect — the space the text lines live in
    assert (round(x0), round(y0), round(x1), round(y1)) == (0, 0, 432, 648)


# ---- dot-below diacritics the font encodes as a bare period

def _rawspan(*chars, font="MinionPro-Regular", size=9.5):
    """chars: (glyph, x0, y0, x1) — y1 is derived; bbox is (x0,y0,x1,y1)."""
    return {"font": font, "size": size, "flags": 0, "color": 0,
            "bbox": (chars[0][1], chars[0][2], chars[-1][3], chars[0][2] + 10),
            "chars": [{"c": c, "bbox": (x0, y0, x1, y0 + 10)}
                      for c, x0, y0, x1 in chars]}


def _rawpage(*spans):
    return {"blocks": [{"type": 0, "lines": [{"dir": (1.0, 0.0),
                                              "spans": list(spans)}]}]}


def test_compose_dot_diacritics_recomposes_the_printed_letter():
    """Keys draws its emphatics as base glyph + a dot glyph whose ToUnicode
    says '.', so the text layer reads 'S.ah.īh.' where print shows 'Ṣaḥīḥ'.
    The dot sits BELOW the baseline and INSIDE the base letter's advance."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("S", 190.8, 376.7, 195.3), (".", 191.9, 378.7, 194.1),   # dot below S
        ("a", 195.2, 376.7, 199.9),
        ("h", 199.8, 376.7, 204.6), (".", 201.0, 378.7, 203.3),   # dot below h
    ))
    n = repair_span_text(page)[0]
    assert n == 2
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "Ṣaḥ"


def test_compose_dot_diacritics_leaves_a_real_period_alone():
    """A sentence period sits ON the baseline and AFTER the letter — it must
    survive untouched, or every citation in the corpus would be mangled."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("ā", 178.3, 376.7, 182.5),
        (".", 184.7, 376.7, 186.9),        # same baseline, clear of 'ā'
        (" ", 186.9, 376.7, 189.0),
        ("S", 190.8, 376.7, 195.3),
    ))
    assert repair_span_text(page)[0] == 0
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "ā. S"


def test_compose_dot_diacritics_needs_an_alpha_base():
    """A dot under a digit or punctuation is not a diacritic."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(("7", 100.0, 376.7, 104.0),
                             (".", 101.0, 378.7, 103.2)))
    assert repair_span_text(page)[0] == 0


def test_compose_dot_diacritics_drops_the_dots_phantom_space():
    """The dot's advance is narrower than its base, so MuPDF emits a leftover
    space carrying the DOT's lowered baseline and ending inside the base's
    advance ('H. ajjāj'). It is the dot's, not a word space."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("H", 162.79, 376.73, 170.07),
        (".", 165.49, 378.73, 167.65),      # dot below H
        (" ", 167.65, 378.73, 169.55),      # dot's leftover advance, inside H
        ("a", 169.55, 376.73, 173.72),
        ("j", 173.54, 376.73, 175.98),
    ))
    assert repair_span_text(page)[0] == 1
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "Ḥaj"


def test_compose_dot_diacritics_keeps_a_real_word_space():
    """A word space after a composed letter sits on the TEXT baseline and
    clear of the base — 'Ṣaḥ Muslim' must keep its space."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("h", 206.96, 376.72, 211.81),
        (".", 208.21, 378.72, 210.44),      # dot below h
        (" ", 212.00, 376.72, 214.00),      # text baseline, clear of 'h'
        ("M", 215.00, 376.72, 223.00),
    ))
    assert repair_span_text(page)[0] == 1
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "ḥ M"


# ---- ligature-pad spaces (Pray Without Ceasing)
# geometry below is measured from the book, not invented: a Minion ligature
# glyph advances less than its ink, and a space glyph pads the difference by
# being drawn back UNDERNEATH that ink.

def test_ligature_pad_space_is_dropped():
    """PWC p.4 prints 'The Library' but the text layer reads 'Th e Library':
    the 'Th' ligature (ink 77.40-88.11) advances only to 82.74, and the pad
    space is drawn there — entirely BEFORE the 'h' MuPDF split out of it."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("T", 77.40, 126.71, 88.11),     # the 'Th' ligature's real ink
        ("h", 88.11, 126.71, 93.45),     # MuPDF's synthetic continuation
        (" ", 82.74, 126.71, 85.00),     # pad: drawn behind the ligature
        ("e", 88.07, 126.71, 92.32),
        (" ", 92.32, 126.71, 94.59),     # a REAL word space, clear of 'e'
        ("L", 94.24, 126.71, 99.62),
    ))
    assert repair_span_text(page)[2] == 1
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "The L"


def test_ligature_pad_drops_both_pads_of_a_three_char_ligature():
    """The 'ffi' of 'affirmation' (PWC p.16) expands to three chars and pads
    TWICE. The second pad's neighbour is the first pad, so the scan must look
    back PAST it to the ligature's own glyph — otherwise 'affi rmation' ships."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("a", 229.55, 376.70, 234.38),
        ("f", 234.28, 376.70, 243.06),   # the 'ffi' ligature's real ink
        ("f", 243.06, 376.70, 246.32),   # synthetic continuation
        ("i", 243.06, 376.70, 246.01),   # synthetic continuation
        (" ", 237.27, 376.70, 239.77),   # pad 1
        (" ", 240.20, 376.70, 242.69),   # pad 2 — neighbour is pad 1
        ("r", 243.12, 376.70, 247.20),
    ))
    assert repair_span_text(page)[2] == 2
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "affir"


def test_ligature_pad_keeps_the_real_space_after_a_word_final_ligature():
    """'gift of' (PWC p.10) ends a word ON the 'ft' ligature, so the pad and a
    REAL word space sit side by side. Exactly one must go: the pad is drawn
    behind the ligature, the word space clear of it."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("g", 228.83, 376.70, 233.98),
        ("i", 233.98, 376.70, 236.93),
        ("f", 236.93, 376.70, 243.33),   # the 'ft' ligature's real ink
        ("t", 243.33, 376.70, 246.68),   # synthetic continuation
        (" ", 240.14, 376.70, 242.64),   # pad: behind the ligature
        (" ", 243.34, 376.70, 245.84),   # a REAL word space
        ("o", 246.37, 376.70, 251.98),
    ))
    assert repair_span_text(page)[2] == 1
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "gift o"


def test_zero_advance_space_between_letters_is_dropped():
    """PWC p.91 prints 'invocation' but the text layer reads 'invoca tion': the
    space has NO advance — the next letter is drawn at the space's own origin.
    Blind readers found these; no gate can, since both engines read one stream."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("c", 285.53, 376.70, 290.19),
        ("a", 290.18, 376.70, 295.01),
        (" ", 294.80, 376.70, 297.30),   # zero advance…
        ("t", 294.80, 376.70, 298.16),   # …the 't' starts at the space's origin
        ("i", 298.15, 376.70, 301.10),
    ))
    assert repair_span_text(page)[2] == 1
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "cati"


def test_zero_advance_rule_keeps_the_tightest_real_word_space():
    """M&R p.154 'seek You' is the corpus's tightest letter/letter word space
    and still advances 0.427pt — an order of magnitude past the tolerance."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("k", 300.00, 376.70, 304.50),
        (" ", 304.50, 376.70, 307.00),
        ("Y", 304.93, 376.70, 310.60),   # advances 0.427pt past the space
    ))
    assert repair_span_text(page)[2] == 0
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "k Y"


def test_zero_advance_rule_skips_rotated_lines():
    """A rotated line (PWC's spine, dir=(0,1)) advances in Y, so every glyph
    shares an x-box and every space reads as zero-advance — the whole spine
    would fuse into 'TheWayoftheInvocation'."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("e", 456.78, 100.00, 470.94),
        (" ", 456.78, 112.00, 470.94),
        ("W", 456.78, 124.00, 470.94),
    ))
    page["blocks"][0]["lines"][0]["dir"] = (0.0, 1.0)
    assert repair_span_text(page)[2] == 0
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "e W"


def test_ligature_pad_inside_a_presentation_form_ligature():
    """PWC's index sets 'Crucified' with a real U+FB01 ligature (ONE glyph, one
    char), so the pad has no continuation glyph to hide behind and overlaps the
    ligature's own ink instead — 'Cruciﬁ ed' shipped through the index, where
    gate 2 is blind (engine-disputed pages)."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("i", 230.23, 376.70, 233.04),
        ("ﬁ", 233.04, 376.70, 238.70),   # one glyph, one char
        (" ", 235.87, 376.70, 238.74),   # pad: inside the ligature's own ink
        ("e", 238.73, 376.70, 243.57),   # resumes at the ligature's ink end
        ("d", 243.57, 376.70, 249.13),
        font="WorldWisdomFont"))
    assert repair_span_text(page)[2] == 1
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "iﬁed"


def test_ligature_pad_keeps_a_word_space_after_a_final_ligature():
    """A REAL word space after a ligature is drawn CLEAR of it, so containment
    fails and the space survives — 'Sufi and' must not become 'Sufiand'."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("ﬁ", 233.04, 376.70, 238.70),
        (" ", 238.70, 376.70, 241.20),   # clear of the ligature: a real space
        ("a", 241.20, 376.70, 246.03),
        font="WorldWisdomFont"))
    assert repair_span_text(page)[2] == 0
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "ﬁ a"


def test_bidi_reorder_moves_closing_neutrals_across_an_rtl_run():
    """PWC p232 prints 'Yod-He-Vav-He (יהוה), which form…' but draws the ')',
    ',' and trailing space as a jump back out to the RIGHT of the Hebrew, so
    the stream emits them BEFORE it and the text layer reads '( ,)יהוה'.
    Geometry (measured from the book) says which glyphs are displaced."""
    from pdf2epub.extract.mupdf import reorder_bidi_lines
    page = _rawpage(
        _rawspan(("H", 351.30, 376.70, 359.73), ("e", 359.45, 376.70, 364.13),
                 (" ", 364.13, 376.70, 366.63), ("(", 369.66, 376.70, 373.47),
                 (" ", 396.00, 376.70, 398.50), (",", 393.49, 376.70, 396.00)),
        _rawspan((")", 389.83, 376.70, 393.49),      # closes the run, drawn right of it
                 ("י", 386.89, 376.70, 389.83), ("ה", 381.71, 376.70, 386.89),
                 ("ו", 378.64, 376.70, 381.71), ("ה", 373.46, 376.70, 378.64),
                 font="TimesNewRomanPSMT"))
    assert reorder_bidi_lines(page) == 3          # ')', ',' and the space moved
    spans = page["blocks"][0]["lines"][0]["spans"]
    assert "".join(s["text"] for s in spans) == "He (יהוה), "


def test_bidi_reorder_keeps_the_opening_paren_before_the_run():
    """The '(' is drawn LEFT of the RTL run, so it is not displaced and must
    stay where print puts it — 'vav (ו). According' (PWC p112)."""
    from pdf2epub.extract.mupdf import reorder_bidi_lines
    page = _rawpage(_rawspan(
        ("v", 267.03, 376.70, 271.95), (" ", 271.93, 376.70, 274.45),
        ("(", 275.10, 376.70, 278.91),
        (" ", 288.29, 376.70, 290.81), (".", 285.78, 376.70, 288.29),
        (")", 281.98, 376.70, 285.78), ("ו", 278.91, 376.70, 281.98),
    ))
    assert reorder_bidi_lines(page) == 3
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "v (ו). "


def test_bidi_reorder_leaves_lines_without_rtl_untouched():
    """The seven other corpus books have ZERO RTL in their text layers, so the
    pass must be a no-op for them — including on ligature-expanded glyphs whose
    synthetic bboxes a visual sort would scramble ('The' -> 'Teh')."""
    from pdf2epub.extract.mupdf import reorder_bidi_lines
    page = _rawpage(_rawspan(
        ("T", 77.40, 126.71, 88.11), ("h", 88.11, 126.71, 93.45),
        (" ", 82.74, 126.71, 85.00), ("e", 88.07, 126.71, 92.32),
    ))
    before = [c["c"] for c in page["blocks"][0]["lines"][0]["spans"][0]["chars"]]
    assert reorder_bidi_lines(page) == 0
    # the glyphs keep their stream order — repair_span_text (which runs next,
    # and drops the pad) is what builds the text
    after = [c["c"] for c in page["blocks"][0]["lines"][0]["spans"][0]["chars"]]
    assert after == before == ["T", "h", " ", "e"]


def test_ligature_pad_leaves_kerned_toc_dot_leaders_alone():
    """BoK's TOC leaders ('. . . .', p.6) are drawn with the same backward
    geometry — degenerate zero-width dot boxes — and fired 1225 times before
    the alphabetic guard. A leader is not a ligature: its dots must survive."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        (".", 345.00, 157.38, 347.28),
        (" ", 349.55, 157.38, 351.83),
        (".", 351.83, 157.38, 351.83),
        (" ", 351.83, 157.38, 351.83),
        (".", 351.83, 157.38, 351.83),
    ))
    assert repair_span_text(page)[2] == 0
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == ". . ."


def test_compose_dot_diacritics_handles_a_dot_ABOVE():
    """Which side the dot falls on is the print's to say: Keys sets ṅ in
    'Śaṅkarācārya' (correct Sanskrit) and a dot-ABOVE ṡ in 'Muṡṭafā' where the
    standard would set it below. Both ship exactly as drawn."""
    from pdf2epub.extract.mupdf import repair_span_text
    page = _rawpage(_rawspan(
        ("n", 329.76, 439.22, 334.68),
        (".", 331.39, 433.98, 333.44),      # dot ABOVE n, inside its advance
        ("k", 334.34, 439.22, 338.80),
    ))
    assert repair_span_text(page)[0] == 1
    assert page["blocks"][0]["lines"][0]["spans"][0]["text"] == "ṅk"
