"""Printed-Contents entry -> heading linking (Emitter.resolve_contents_links).

A numbered TOC entry ("4. Metaphysical and Spiritual Aesthetics") must still
link when the chapter heading joined its printed kicker into one h1
("CHAPTER FOUR Metaphysical and Spiritual Aesthetics"): the enumeration-less
entry text contained anywhere in the heading is a strong match. Frithjof
Schuon: Life and Teachings hit this — fuzz.ratio alone lands just under the
85 cutoff for the longest chapter title while chapters 1-3 pass, silently
leaving exactly one Contents entry unlinked.
"""

import re
from collections import Counter

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
    # ties them and the printed target page (145) breaks the tie. Anchors in
    # real document order (appendix 145 before the Notes subhead 200 —
    # review #96 rebuilt agreement on document page order).
    entry = _p("Appendix 1: Frithjof Schuon: General Considerations\t145",
               6, role="toc-entry")
    a_anchor = PageAnchor(ordinal=145, label="145")
    a_h1 = _p("APPENDIX 1 Frithjof Schuon", 145, role="h1")  # appendix -> h001
    n_anchor = PageAnchor(ordinal=200, label="200")
    n_h3 = _p("APPENDIX 1", 200, role="h3")            # Notes subhead -> h002
    em, body = _emit([entry, a_anchor, a_h1, n_anchor, n_h3], tmp_path)
    assert em.warnings == []
    m = re.search(r'class="toc-entry"><a href="([^"]+)"', body)
    assert m, body
    # an unfolded-match regression makes the shorter subhead outscore the h1
    # and win alone; folding ties them and page agreement picks the appendix
    assert m.group(1).endswith("#h001"), m.group(1)


def test_roman_folio_predecessor_agrees(tmp_path):
    # roman-folio targets must get the same predecessor slack as decimal ones:
    # the old abs(int-diff) agreement raised ValueError on 'ix'/'x' and fell
    # back to the first (wrong) duplicate (review #96)
    decoy_a = PageAnchor(ordinal=5, label="v")
    decoy = _p("FOREWORD", 5, role="h1")       # front-matter echo -> h001
    real_a = PageAnchor(ordinal=9, label="ix")
    real = _p("FOREWORD", 9, role="h1")        # heading anchor one early -> h002
    after_a = PageAnchor(ordinal=10, label="x")
    entry = _p("Foreword\tx", 3, role="toc-entry")
    em, body = _emit([entry, decoy_a, decoy, real_a, real, after_a], tmp_path)
    m = re.search(r'class="toc-entry"><a href="([^"]+)"', body)
    assert m, body
    assert m.group(1).endswith("#h002"), m.group(1)


def test_following_page_never_agrees(tmp_path):
    # the old abs(int-diff) accepted the FOLLOWING page as agreeing; document
    # order accepts only the target page or its predecessor (review #96)
    early_a = PageAnchor(ordinal=8, label="8")
    early = _p("NOTES", 8, role="h1")          # legitimately early -> h001
    t_a = PageAnchor(ordinal=10, label="10")
    f_a = PageAnchor(ordinal=11, label="11")
    following = _p("NOTES", 11, role="h1")     # following page -> h002
    entry = _p("Notes\t10", 3, role="toc-entry")
    em, body = _emit([entry, early_a, early, t_a, f_a, following], tmp_path)
    m = re.search(r'class="toc-entry"><a href="([^"]+)"', body)
    assert m, body
    # neither candidate agrees (8 is too early, 11 is late) -> first match,
    # NEVER the following-page heading the old test wrongly blessed
    assert m.group(1).endswith("#h001"), m.group(1)


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
