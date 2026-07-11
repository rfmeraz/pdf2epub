from pdf2epub.core.qa_ordercheck import check_heading_pages, check_orphan_headings

PAGE_ORDER = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
              "xxii", "xxiii", "1", "2"]


def test_headings_on_correct_pages_pass():
    seq = [
        ("page", "i"), ("page", "ii"),
        ("page", "ix"), ("heading", "Foreword"),
        ("page", "xxii"), ("heading", "Acknowledgment"),
        ("page", "1"), ("heading", "Chapter 1: The Origin"),
    ]
    toc = [("Foreword", "ix"), ("Acknowledgment", "xxii"), ("Chapter 1: The Origin", "1")]
    res = check_heading_pages(seq, toc, PAGE_ORDER)
    assert res.ok and res.matched_entries == 3


def test_paragraph_granularity_slack():
    # a heading may land just before its page's marker (one page early is OK)
    seq = [("page", "v"), ("heading", "Foreword"), ("page", "ix")]
    toc = [("Foreword", "ix")]
    # "v" is not the page before "ix" in PAGE_ORDER -> violation
    assert not check_heading_pages(seq, toc, PAGE_ORDER).ok
    seq2 = [("page", "v"), ("page", "ix"), ("heading", "Foreword")]
    assert check_heading_pages(seq2, toc, PAGE_ORDER).ok


def test_foreword_bug_shape_is_caught():
    # the pilot's actual incident: the Foreword heading emitted before ANY
    # page marker, its body far away — heading has no page context
    seq = [
        ("heading", "Foreword"),          # orphaned at the very front
        ("page", "i"), ("page", "ii"),
        ("page", "ix"),                    # body text follows here, headingless
        ("page", "xxii"), ("heading", "Acknowledgment"),
    ]
    toc = [("Foreword", "ix"), ("Acknowledgment", "xxii")]
    res = check_heading_pages(seq, toc, PAGE_ORDER)
    assert not res.ok
    assert any("Foreword" in v for v in res.violations)


def test_toc_entry_extends_heading_title():
    seq = [("page", "ix"), ("heading", "Foreword")]
    toc = [("Foreword by Wang Genming (王根明)", "ix")]
    res = check_heading_pages(seq, toc, PAGE_ORDER)
    assert res.ok and res.matched_entries == 1


def test_unmatched_toc_entry_is_info_not_failure():
    seq = [("page", "1"), ("heading", "Chapter 1: The Origin")]
    toc = [("Chapter 1: The Origin", "1"), ("Some Group Title", "2")]
    res = check_heading_pages(seq, toc, PAGE_ORDER)
    assert res.ok and res.matched_entries == 1 and res.notes


def test_folioless_part_divider_entry_is_skipped():
    # a printed-TOC part-divider label carrying no folio ('Appendix', via
    # toc.standalone_lines) cannot be page-verified — it must be skipped as
    # info, not reported as sitting on the wrong page
    seq = [("page", "1"), ("heading", "Chapter 1: The Origin"),
           ("page", "2"), ("heading", "Appendix")]
    toc = [("Chapter 1: The Origin", "1"), ("Appendix", "")]
    res = check_heading_pages(seq, toc, PAGE_ORDER)
    assert res.ok  # no violation despite 'Appendix' heading on page '2'
    assert res.matched_entries == 1  # the folio-less entry is not verified
    assert any("part-divider" in n for n in res.notes)


def test_orphan_heading_detector():
    files = [
        ("003-foreword.xhtml", True, 5, False),      # heading, no body: flagged
        ("009-chapter-1.xhtml", True, 4000, False),  # normal chapter
        ("012-plates.xhtml", True, 0, True),         # heading + figure only: fine
        ("002-title.xhtml", False, 10, False),       # no heading: fine
    ]
    bad = check_orphan_headings(files)
    assert len(bad) == 1 and "003-foreword" in bad[0]


def test_duplicate_headings_prefer_page_agreement():
    # a book may repeat a heading on two part-title pages; the entry must
    # bind to the occurrence on its printed page, not the first one found
    seq = [
        ("page", "x"), ("heading", "Chinese Text"),
        ("page", "1"), ("heading", "Chinese Text"),
    ]
    toc = [("Chinese Text", "1")]
    res = check_heading_pages(seq, toc, PAGE_ORDER)
    assert res.ok and res.matched_entries == 1


def test_grouping_entry_must_not_steal_exact_heading():
    # BoK back matter: the outline's 'Indexes' grouping bookmark (p.'i' here,
    # no printed heading of its own) must not fuzzy-claim the 'Index' heading
    # that belongs to the exact entry two pages later
    seq = [("page", "i"), ("heading", "Verses Cited"),
           ("page", "iii"), ("heading", "Index")]
    toc = [("Indexes", "i"), ("Index", "iii")]
    res = check_heading_pages(seq, toc, ["i", "ii", "iii", "iv"])
    assert res.ok, res.violations
    assert res.matched_entries == 1  # 'Index' exact; 'Indexes' is an info note
    assert any("Indexes" in n for n in res.notes)
