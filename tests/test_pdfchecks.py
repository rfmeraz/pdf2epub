"""Pure-function QA checks (gates 7-11) on synthetic sequences."""

from pdf2epub.qa.pdfchecks import (
    check_furniture_leak,
    check_toc_agreement,
    hyphen_residue,
    lost_space_count,
    pua_residue,
)


def test_toc_agreement():
    nav = [(1, "Foreword"), (1, "Chapter 1"), (2, "The Virtue of Knowledge"),
           (3, "Deep Sub")]
    res = check_toc_agreement(nav, ["Foreword", "Chapter 1", "Missing One"], 2)
    assert res.matched == 2 and res.missing == ["Missing One"]
    assert not res.ok
    ok = check_toc_agreement(nav, ["Foreword", "Deep Sub"], 2)
    assert ok.ok  # present-but-deeper is tolerated


def test_furniture_leak():
    fur = {"#book of knowledge | chapter #"}
    leaks = check_furniture_leak(
        ["14book of knowledge | chapter 1", "Real paragraph text that stays.",
         "1-Main-text-v8.indd 44  12/7/15 5:53 PM"], fur)
    assert len(leaks) == 2


def test_residue_counters():
    assert hyphen_residue("a com- munity of readers") == 1
    assert hyphen_residue("well-known compound") == 0
    assert pua_residue("plain  text") == ["U+F048"]
    assert pua_residue("clean") == []
    assert lost_space_count('said.Then and say,"If and fine. Text') == 2
