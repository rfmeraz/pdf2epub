
from pdf2epub.core.lang import _split_run
from pdf2epub.core.model import RunFormat, TextRun


def _langs(text, han_lang="zh"):
    runs = _split_run(TextRun(text=text, fmt=RunFormat()), han_lang)
    return [(r.text, r.fmt.lang) for r in runs]


def test_han_only_is_zh():
    out = _langs("styled Jielian (介廉) and")
    assert ("介廉", "zh") in out
    assert out[0] == ("styled Jielian (", None)


def test_kana_cluster_is_ja():
    out = _langs("the title 五功の解説 here")
    assert ("五功の解説", "ja") in out


def test_cjk_punctuation_joins_cluster():
    out = _langs("劉智「五功釈義」第２６冊")
    cjk = [t for t, lang in out if lang]
    assert len(cjk) == 1  # one cluster, brackets included


def test_no_cjk_untouched():
    out = _langs("plain latin text")
    assert out == [("plain latin text", None)]

# NOTE: the former test_class_hints exercised idml2epub.mapping.styles.class_hint
# — sibling-repo code that pdf2epub/src never imports. A cross-repo parity check
# does not belong in this suite; it was removed for hermeticity (see
# specs/reliability-hardening.md §4).
