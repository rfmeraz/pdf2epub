"""EpubDoc.is_endnotes(): the generated endnotes file is identified by its
<section epub:type="endnotes"> marker, NOT by a 'notes' substring in the
filename — otherwise back-matter *sections* titled '…Notes' (Editor's Notes,
Biographical Notes) get wrongly dropped from the coverage/typography scope.
Regression guard for the Sufism: Veil and Quintessence conversion."""

from lxml import etree

from pdf2epub.core.qa_epubload import EpubDoc

_XHTML = "http://www.w3.org/1999/xhtml"
_OPS = "http://www.idpf.org/2007/ops"


def _doc(href: str, body_inner: str) -> EpubDoc:
    xml = (
        f'<html xmlns="{_XHTML}" xmlns:epub="{_OPS}">'
        f"<head><title>t</title></head><body>{body_inner}</body></html>"
    )
    return EpubDoc(href=href, root=etree.fromstring(xml.encode("utf-8")))


def test_generated_endnotes_file_is_endnotes():
    d = _doc(
        "notes.xhtml",
        '<section epub:type="endnotes" role="doc-endnotes">'
        '<ol><li id="fn1"><p>a note</p></li></ol></section>',
    )
    assert d.is_endnotes()


def test_editors_notes_section_is_not_endnotes():
    # filename contains 'notes' but it is a normal prose section
    d = _doc(
        "015-editors-notes.xhtml",
        '<h1>Editor’s Notes</h1><p>Numbers in bold indicate pages.</p>',
    )
    assert not d.is_endnotes()


def test_biographical_notes_section_is_not_endnotes():
    d = _doc(
        "017-biographical-notes.xhtml",
        "<h1>Biographical Notes</h1><p>Born in Basle in 1907.</p>",
    )
    assert not d.is_endnotes()


def test_plain_body_chapter_is_not_endnotes():
    d = _doc("007-chapter.xhtml", "<h1>A Chapter</h1><p>Body text.</p>")
    assert not d.is_endnotes()


def test_block_text_br_counts_as_space():
    from pdf2epub.core.qa_epubload import block_text

    d = _doc("c1.xhtml",
             "<p><span>like dirt—</span><br/><span>others come</span></p>")
    p = d.root.find(f"{{{_XHTML}}}body/{{{_XHTML}}}p")
    assert block_text(p) == "like dirt— others come"


def test_block_text_inline_joins_without_space():
    # the 'no- dharma' lesson: inline tags must NOT contribute whitespace
    from pdf2epub.core.qa_epubload import block_text

    d = _doc("c1.xhtml", "<p>no-<i>dharma</i> stays</p>")
    p = d.root.find(f"{{{_XHTML}}}body/{{{_XHTML}}}p")
    assert block_text(p) == "no-dharma stays"
