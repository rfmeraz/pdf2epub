"""Gate 19: Qurʾānic citation index validation on synthetic XHTML docs."""

from types import SimpleNamespace

from lxml import etree

from pdf2epub.qa.quran import SURA_VERSES, check_quran_index

_NS = 'xmlns="http://www.w3.org/1999/xhtml"'


def _doc(inner):
    root = etree.fromstring(
        f'<html {_NS}><body>{inner}</body></html>'.encode())
    return SimpleNamespace(href="a.xhtml", root=root)


def test_sura_table_shape():
    assert len(SURA_VERSES) == 114
    assert sum(SURA_VERSES) == 6236  # canonical Ḥafṣ/Kufan total


def test_valid_index_passes():
    d = _doc("<h2>Qurʾānic Verses Cited</h2>"
             "<p>2:44, \t169, 183</p>"
             "<p>7:175–176,\t174</p>"
             "<p>35:28,\t 3, 67, 142, 229</p>"
             "<p>114:4, 12</p>"
             "<h2>Index</h2><p>ablutions, 33</p>")
    res = check_quran_index([d], {"3", "12", "67", "142", "169", "174",
                                  "183", "229"})
    assert res.found and res.n_entries == 4 and res.ok


def test_linked_locators_are_transparent_to_parse():
    # index_locators wraps page numbers in <a href="#pg-N">; gate 19 parses
    # entry text via itertext() (walks INTO the <a>), so the citation parse
    # must be byte-identical to the unwrapped form above.
    d = _doc('<h2>Qurʾānic Verses Cited</h2>'
             '<p>2:44, \t<a href="a.xhtml#pg-169">169</a>, 183</p>'
             '<p>7:175–176,\t<a href="a.xhtml#pg-174">174</a></p>'
             '<p>35:28,\t 3, <a href="a.xhtml#pg-67">67</a>, 142, 229</p>'
             '<p>114:4, 12</p>')
    res = check_quran_index([d], {"3", "12", "67", "142", "169", "174",
                                  "183", "229"})
    assert res.found and res.n_entries == 4 and res.ok


def test_interleaved_columns_fire():
    # the shipped BoK defect: three columns fused into one paragraph
    d = _doc("<h2>Qurʾānic Verses Cited</h2>"
             "<p>2:44, 169, 1836:91, 9318:67–68, 145 2:89, 1746:122, 249</p>")
    res = check_quran_index([d], set())
    assert res.found and not res.ok
    assert any("bad page ref" in x for x in res.defects)


def test_impossible_citations_fire():
    d = _doc("<h2>Qurʾānic Verses Cited</h2>"
             "<p>115:3, 12</p>"     # no sura 115
             "<p>2:287, 12</p>"     # al-Baqara has 286 verses
             "<p>1:2–9, 12</p>")    # range end beyond al-Fātiḥa's 7
    res = check_quran_index([d], {"12"})
    assert len(res.defects) == 3
    assert any("no sura 115" in x for x in res.defects)
    assert any("has 286 verses" in x for x in res.defects)


def test_order_violation_fires():
    # column interleaving reads 18:70 before 2:89
    d = _doc("<h2>Qurʾānic Verses Cited</h2>"
             "<p>18:70, 145</p><p>2:89, 174</p>")
    res = check_quran_index([d], {"145", "174"})
    assert any("order violation" in x for x in res.defects)


def test_unknown_page_label_fires():
    d = _doc("<h2>Qurʾānic Verses Cited</h2><p>2:44, 500</p>")
    res = check_quran_index([d], {"1", "2", "3"})
    assert any("not in the EPUB page-list" in x for x in res.defects)
    # without a page-list the check is skipped
    assert check_quran_index([d], set()).ok


def test_absent_index_is_silent():
    d = _doc("<h2>Bibliography</h2><p>Some entry, 2004.</p>")
    res = check_quran_index([d], set())
    assert not res.found and res.ok
    assert "no Qurʾānic verses index" in res.lines[0]
