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

import re

from pdf2epub.config import PdfBookConfig
from pdf2epub.core.emit_xhtml import Emitter
from pdf2epub.core.model import (
    FlowDoc,
    PageAnchor,
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


def test_duplicate_heading_prefers_target_page(tmp_path):
    # 'Appendix 1: ...' must link to the appendix chapter's own h1, not the
    # Notes subhead that merely echoes 'APPENDIX 1'. The colon defeated the
    # unfolded prefix match so the shorter subhead won; punctuation folding
    # ties them and the printed target page (145) breaks the tie — even though
    # the Notes subhead is emitted FIRST (finding #4).
    entry = _p("Appendix 1: Frithjof Schuon: General Considerations\t145",
               6, role="toc-entry")
    n_anchor = PageAnchor(ordinal=200, label="200")
    n_h3 = _p("APPENDIX 1", 200, role="h3")            # Notes subhead -> h001
    a_anchor = PageAnchor(ordinal=145, label="145")
    a_h1 = _p("APPENDIX 1 Frithjof Schuon", 145, role="h1")  # appendix -> h002
    em, body = _emit([entry, n_anchor, n_h3, a_anchor, a_h1], tmp_path)
    assert em.warnings == []
    m = re.search(r'class="toc-entry"><a href="([^"]+)"', body)
    assert m, body
    assert m.group(1).endswith("#h002"), m.group(1)


def test_folding_links_across_punctuation_without_page(tmp_path):
    # with no printed folio to compare, punctuation folding alone still lifts
    # the colon-separated entry onto the appendix heading (the notes subhead is
    # never present here — this isolates the folding half of the fix)
    entry = _p("Appendix 1: Frithjof Schuon: General Considerations",
               6, role="toc-entry")
    h1 = _p("APPENDIX 1 Frithjof Schuon", 145, role="h1")
    em, body = _emit([entry, h1], tmp_path)
    assert em.warnings == []
    assert '<a href="' in body and "#h001" in body
