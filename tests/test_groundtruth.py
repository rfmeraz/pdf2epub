"""Ground-truth note excision: the squeeze match tolerates the flow's
dehyphenation vs poppler's kept line-break hyphens."""

from pdf2epub.qa.groundtruth import _find_fuzzyish


def test_find_fuzzyish_exact():
    hay = "alpha beta gamma delta epsilon"
    assert _find_fuzzyish(hay, "beta gamma delta") == (6, 22)


def test_find_fuzzyish_squeeze_over_hyphenation():
    # flow note text is dehyphenated ('mercantile'); poppler keeps 'mer- cantile'
    hay = "a chivalrous and mer- cantile note about ransom and debt here"
    needle = "chivalrous and mercantile note about ransom"
    span = _find_fuzzyish(hay, needle)
    assert span is not None
    s, e = span
    # the excised span covers the hyphen-broken original text
    assert "chivalrous" in hay[s:e] and "cantile" in hay[s:e]


def test_find_fuzzyish_absent():
    assert _find_fuzzyish("nothing relevant here at all", "wholly absent phrase") is None
