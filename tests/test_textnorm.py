from pdf2epub.core.textnorm import int_to_roman, is_folio_line, normalize, strip_page_furniture


def test_normalize_quotes_and_spaces():
    assert normalize("“Hello”—‘world’  now") == '"Hello"-\'world\' now'


def test_normalize_dehyphenates_linebreaks():
    assert normalize("re-\nmembrance") == "remembrance"


def test_normalize_keeps_cjk():
    assert normalize("五功釈義　test") == "五功釈義 test"


def test_folio_lines():
    assert is_folio_line("  42 ")
    assert is_folio_line("xxiv")
    assert not is_folio_line("Chapter 42")


def test_strip_page_furniture_leading_only():
    page = "The Harmonious Unity\nreal text starts\nThe Harmonious Unity quoted mid-page\n17"
    out = strip_page_furniture(page, {"the harmonious unity"})
    # normalized furniture is compared case-sensitively against normalize() output
    out2 = strip_page_furniture(page, {normalize("The Harmonious Unity")})
    assert "real text starts" in out2
    assert "quoted mid-page" in out2  # mid-page repeat survives
    assert "\n17" not in out2  # folio stripped


def test_int_to_roman():
    assert int_to_roman(4) == "iv"
    assert int_to_roman(34) == "xxxiv"
    assert int_to_roman(118, lower=False) == "CXVIII"


def test_normalize_collapses_line_separator():
    # verse stanzas join lines with U+2028 LINE SEPARATOR; the normalize
    # chain must see it as whitespace or every verse seam becomes a
    # coverage/lost-space false positive (pinned: Python \s covers U+2028)
    assert normalize("like dirt\u2028others come") == "like dirt others come"
