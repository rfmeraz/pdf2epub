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


def test_excise_note_removes_body_and_delimiter():
    """A '1. body' note: excise the body AND the orphaned '. ' delimiter the
    marker left, so only the bare marker '1' remains (removed by the caller) —
    review #424: the delimiter must not be left behind in the ground truth."""
    from pdf2epub.qa.groundtruth import _excise_note
    norm = "before 1. the note body long enough to be located after"
    new, removed = _excise_note(norm, "the note body long enough to be located", "1")
    assert "the note body" not in new
    assert ". " not in new                      # no orphaned delimiter
    assert new.strip().startswith("before 1")   # bare marker survives for the caller
    assert removed > 0


def test_excise_note_space_delimiter():
    """A '1 body' note (single-space marker, this book): excise body + the
    space; the bare marker survives, nothing orphaned."""
    from pdf2epub.qa.groundtruth import _excise_note
    norm = "x 1 the note body long enough to be located here now y"
    new, _ = _excise_note(norm, "the note body long enough to be located here now", "1")
    assert "the note body" not in new
    assert new.strip().startswith("x 1")


def test_excise_note_absent_returns_none():
    from pdf2epub.qa.groundtruth import _excise_note
    assert _excise_note("nothing here at all", "a wholly absent note body", "1") is None
