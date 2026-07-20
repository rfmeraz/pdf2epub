"""Printed-Contents entry -> heading linking (Emitter.resolve_contents_links).

A numbered TOC entry ("4. Metaphysical and Spiritual Aesthetics") must still
link when the chapter heading joined its printed kicker into one h1
("CHAPTER FOUR Metaphysical and Spiritual Aesthetics"): the enumeration-less
entry text contained anywhere in the heading is a strong match. Frithjof
Schuon: Life and Teachings hit this — fuzz.ratio alone lands just under the
85 cutoff for the longest chapter title while chapters 1-3 pass, silently
leaving exactly one Contents entry unlinked.
"""

from collections import Counter

from pdf2epub.config import PdfBookConfig
from pdf2epub.core.emit_xhtml import Emitter
from pdf2epub.core.model import (
    FlowDoc,
    Paragraph,
    RunFormat,
    SourceRef,
    TextRun,
)


def _p(text, page, role=None):
    return Paragraph(style="s", items=[TextRun(text, RunFormat())],
                     src=SourceRef(f"p{page:04d}", 0), role=role)


def _emit(blocks, tmp_path):
    flow = FlowDoc(blocks=blocks, notes={}, style_usage=Counter(), text_dests={})
    cfg = PdfBookConfig(path=tmp_path / "book.yaml")
    em = Emitter(cfg, flow, say=lambda m: None)
    out = em.emit()
    em.resolve_contents_links()
    return em, "".join(part for f in out.files for part in f.body_parts)


def test_numbered_entry_links_kicker_joined_heading(tmp_path):
    entry = _p("4. Metaphysical and Spiritual Aesthetics", 8, role="toc-entry")
    h1 = _p("CHAPTER FOUR Metaphysical and Spiritual Aesthetics", 122, role="h1")
    em, body = _emit([entry, h1], tmp_path)
    assert em.warnings == []
    assert '<a href="' in body and ">4. Metaphysical and Spiritual Aesthetics</a>" in body


def test_unmatched_entry_still_warns(tmp_path):
    entry = _p("7. A Chapter That Does Not Exist", 8, role="toc-entry")
    h1 = _p("CHAPTER FOUR Metaphysical and Spiritual Aesthetics", 122, role="h1")
    em, body = _emit([entry, h1], tmp_path)
    assert any("without a matching heading" in w for w in em.warnings)
    assert "<a href=" not in body.split("toc-entry")[1][:120]
