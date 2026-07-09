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


def test_noteref_seam_defects():
    from types import SimpleNamespace

    from lxml import etree

    from pdf2epub.qa.pdfchecks import noteref_seam_defects

    ns = ('xmlns="http://www.w3.org/1999/xhtml" '
          'xmlns:epub="http://www.idpf.org/2007/ops"')

    def _doc(inner):
        root = etree.fromstring(
            f'<html {ns}><body><p>{inner}</p></body></html>'.encode())
        return SimpleNamespace(href="a.xhtml", root=root)

    ref = '<a class="noteref" href="notes.xhtml#fn3"><sup>3</sup></a>'
    # letter directly after the ref: always an artifact
    hits = noteref_seam_defects([_doc(f"word.{ref}The next part")])
    assert len(hits) == 1 and "[3]The next" in hits[0]
    # digit after the ref: artifact
    assert noteref_seam_defects([_doc(f"word.{ref}42 more")])
    # punctuation/quotes/dashes: legitimate
    for tail in (") more", ", and", "” said", "— dash", ". End"):
        assert not noteref_seam_defects([_doc(f"word.{ref}{tail}")])
    # space then letter: fine; no tail at all: fine
    assert not noteref_seam_defects([_doc(f"word.{ref} next")])
    assert not noteref_seam_defects([_doc(f"word.{ref}")])
    # backlink anchors are not noterefs
    back = '<a class="backlink" href="b.xhtml#fnref3">x</a>'
    assert not noteref_seam_defects([_doc(f"word.{back}Then")])
