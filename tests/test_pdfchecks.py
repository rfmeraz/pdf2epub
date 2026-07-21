"""Pure-function QA checks (gates 7-11) on synthetic sequences."""

from pdf2epub.qa.pdfchecks import (
    check_furniture_leak,
    check_toc_agreement,
    count_numeric_nav_entries,
    hyphen_residue,
    lost_space_count,
    pua_residue,
)


def test_count_numeric_nav_entries():
    # a clean, named nav -> gate 7b GATE passes (empty), advisory quiet
    clean = [(1, "Foreword"), (3, "Childhood"), (3, "My Teaching Career")]
    assert count_numeric_nav_entries(clean) == []

    # passage-number pollution -> the offenders, in doc order (the gate names
    # these when a drop was requested; the advisory counts them)
    dirty = clean + [(3, "1."), (3, "2."), (3, "19.*")]
    leaked = count_numeric_nav_entries(dirty)
    assert leaked == ["1.", "2.", "19.*"]
    # gating decision = any leak; advisory floor = 10 (so 3 stays quiet, and a
    # lone 1/1 never fires)
    assert bool(leaked) and len(leaked) < 10
    assert count_numeric_nav_entries([(3, "1.")]) == ["1."]  # 1/1: below floor

    # the sufism shape: 22 bare integers clears the advisory floor
    sufism = clean + [(3, str(i)) for i in range(1, 23)]
    assert len(count_numeric_nav_entries(sufism)) == 22 >= 10


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


def test_lost_space_defects():
    from pdf2epub.qa.pdfchecks import lost_space_defects

    text = "the mirror of the believer.This means and fine. Text follows"
    defects, stale = lost_space_defects(text)
    assert len(defects) == 1 and not stale
    assert "believer.This means" in defects[0]     # context snippet
    # allowlisted exact snippet is removed before matching
    defects, stale = lost_space_defects(text, ["believer.This"])
    assert not defects and not stale
    # an allow entry matching nothing is stale (config rot is an error)
    defects, stale = lost_space_defects(text, ["etc.Cambridge"])
    assert len(defects) == 1 and len(stale) == 1
    assert "etc.Cambridge" in stale[0]
    # quote-comma pattern still covered
    assert lost_space_defects('they say,"If I went')[0]


def test_garble_residue():
    from pdf2epub.qa.pdfchecks import garble_residue

    assert garble_residue("clean text with ³ but unconfigured") == []
    hits = garble_residue("note prefix ��� then text")
    assert len(hits) == 1 and "U+FFFD" in hits[0] and "note prefix" in hits[0]
    hits = garble_residue("shifted\x0emarker")          # C0 = shift markers
    assert len(hits) == 1 and "U+000E" in hits[0]
    # configured per-book residue chars (I&B ³´«)
    hits = garble_residue("said, ³God knows best´ then", "³´«")
    assert len(hits) == 2 and "U+00B3" in hits[0] and "U+00B4" in hits[1]
    # a run of garble chars is ONE hit, all codepoints named
    hits = garble_residue("x³´y", "³´")
    assert len(hits) == 1 and "U+00B3" in hits[0] and "U+00B4" in hits[0]


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
