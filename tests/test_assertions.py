"""Gate 24: per-book regression assertions (qa/assertions.py)."""

import pytest

from pdf2epub.core.qa_pageslice import EpubBlock, SliceResult
from pdf2epub.qa.assertions import AssertionSchemaError, evaluate, parse_assertions, run_assertions


def _blk(text):
    return EpubBlock(tag="p", classes=(), in_blockquote=False, text=text)


def _sl(pages, ok=True, detail=""):
    """pages: {pno: [block text, ...]} -> a SliceResult."""
    slices = {p: [_blk(t) for t in texts] for p, texts in pages.items()}
    return SliceResult(ok=ok, detail=detail, slices=slices)


def _ev(entries, pages, labels, in_flow, sl_ok=True, detail=""):
    asserts = parse_assertions(entries)
    return evaluate(asserts, _sl(pages, ok=sl_ok, detail=detail), labels, in_flow)


# ----------------------------------------------------------- present / absent

def test_present_pass_and_fail():
    labels, in_flow = {1: "46"}, [1]
    fails, stale = _ev([{"page": "46", "type": "present",
                         "text": "Now, however", "note": "x"}],
                       {1: ["Well, Now, however true"]}, labels, in_flow)
    assert not fails and not stale
    fails, _ = _ev([{"page": "46", "type": "present",
                     "text": "Now, however", "note": "x"}],
                   {1: ["nothing here"]}, labels, in_flow)
    assert len(fails) == 1 and "expected" in fails[0]


def test_absent_catches_reintroduced_fusion():
    labels, in_flow = {1: "46"}, [1]
    entry = [{"page": "46", "type": "absent", "text": "Now,however", "note": "seam"}]
    fails, _ = _ev(entry, {1: ["ok Now, however ok"]}, labels, in_flow)
    assert not fails                                  # fixed build: passes
    fails, _ = _ev(entry, {1: ["oops Now,however oops"]}, labels, in_flow)
    assert len(fails) == 1 and "forbidden" in fails[0]  # reverted: fails


# ----------------------------------------------------------- order + boundary

def test_order_pass_fail_and_missing():
    labels, in_flow = {1: "322"}, [1]
    e = [{"page": "322", "type": "order", "text": "35:8", "text2": "35:28",
          "note": "monotone"}]
    assert _ev(e, {1: ["35:8, 3. 35:28, 9."]}, labels, in_flow) == ([], [])
    fails, _ = _ev(e, {1: ["35:28, 9. 35:8, 3."]}, labels, in_flow)
    assert len(fails) == 1 and "does not precede" in fails[0]
    fails, _ = _ev(e, {1: ["35:8 only"]}, labels, in_flow)
    assert len(fails) == 1 and "not found" in fails[0]


def test_boundary_blocks_substring_false_match():
    labels, in_flow = {1: "9"}, [1]
    # '35:8' must NOT match inside '135:8'
    present = [{"page": "9", "type": "present", "text": "35:8",
                "boundary": True, "note": "b"}]
    fails, _ = _ev(present, {1: ["ref 135:8 and 35:80"]}, labels, in_flow)
    assert len(fails) == 1                            # not found under boundary
    fails, _ = _ev(present, {1: ["ref 35:8 here"]}, labels, in_flow)
    assert not fails                                  # exact token found


def test_order_boundary_is_default_on():
    labels, in_flow = {1: "1"}, [1]
    # a bare '35:8' operand should not latch onto '135:8' when ordering
    e = [{"page": "1", "type": "order", "text": "35:8", "text2": "99:9",
          "note": "d"}]
    fails, _ = _ev(e, {1: ["135:8 then 99:9"]}, labels, in_flow)
    assert len(fails) == 1 and "35:8" in fails[0]     # 35:8 not found (boundary)


# ----------------------------------------------------------- ranges + blocks

def test_range_concatenates_positional_span():
    labels, in_flow = {1: "322", 2: "323"}, [1, 2]
    e = [{"page": "322-323", "type": "order", "text": "35:8", "text2": "35:28",
          "note": "seam"}]
    # operands straddle the page seam — single-page match would fail
    assert _ev(e, {1: ["… 35:8 tail"], 2: ["head 35:28 …"]}, labels, in_flow) == ([], [])


def test_block_present_needs_single_block():
    labels, in_flow = {1: "151"}, [1]
    e = [{"page": "151", "type": "block_present",
          "text": "Trustworthy persons have related", "note": "blockquote"}]
    # intact in one block -> pass
    assert _ev(e, {1: ["Trustworthy persons have related that"]},
               labels, in_flow) == ([], [])
    # shattered across blocks -> block_present fails (page concat would pass)
    fails, _ = _ev(e, {1: ["Trustworthy persons", "have related that"]},
                   labels, in_flow)
    assert len(fails) == 1 and "single block" in fails[0]


# ----------------------------------------------------------- staleness (loud)

def test_unresolvable_label_is_stale():
    _, stale = _ev([{"page": "999", "type": "present", "text": "hello world",
                     "note": "gone"}], {1: ["x"]}, {1: "46"}, [1])
    assert len(stale) == 1 and "not in the in-flow page-list" in stale[0]


def test_ambiguous_label_is_stale_unless_pno_given():
    labels, in_flow = {1: "12", 2: "12"}, [1, 2]
    _, stale = _ev([{"page": "12", "type": "present", "text": "alpha beta",
                     "note": "dup"}], {1: ["alpha beta"], 2: ["z"]},
                   labels, in_flow)
    assert len(stale) == 1 and "multiple in-flow pages" in stale[0]
    # the pno: escape hatch disambiguates
    assert _ev([{"page": "12", "type": "present", "text": "alpha beta",
                 "pno": 1, "note": "dup"}], {1: ["alpha beta"], 2: ["z"]},
               labels, in_flow) == ([], [])


def test_empty_slice_is_stale_not_silent_pass():
    # an 'absent' on a text-less (figure-only) page must not vacuously pass
    _, stale = _ev([{"page": "26", "type": "absent", "text": "legend scramble",
                     "note": "figure page"}], {1: []}, {1: "26"}, [1])
    assert len(stale) == 1 and "undecidable" in stale[0]


def test_stale_messages_are_sorted():
    labels, in_flow = {1: "1"}, [1]
    e = [{"page": "zzz", "type": "present", "text": "aaaa", "note": "n1"},
         {"page": "aaa", "type": "present", "text": "aaaa", "note": "n2"}]
    _, stale = _ev(e, {1: ["x"]}, labels, in_flow)
    assert stale == sorted(stale)


# ----------------------------------------------------------- file-level paths

def test_missing_fixture_passes(tmp_path):
    ao = run_assertions(tmp_path / "nope.yaml", _sl({1: ["x"]}), {1: "1"}, [1])
    assert ao.verdict is True and "no assertions configured" in ao.lines[0]


def test_empty_fixture_passes(tmp_path):
    p = tmp_path / "qa_assertions.yaml"
    p.write_text("")
    ao = run_assertions(p, _sl({1: ["x"]}), {1: "1"}, [1])
    assert ao.verdict is True and "0 assertions" in ao.lines[0]


def test_parse_error_fails_loud(tmp_path):
    p = tmp_path / "qa_assertions.yaml"
    p.write_text("this: [unbalanced\n")
    ao = run_assertions(p, _sl({1: ["x"]}), {1: "1"}, [1])
    assert ao.verdict is False and "parse error" in ao.lines[0]


def test_schema_error_fails_loud(tmp_path):
    p = tmp_path / "qa_assertions.yaml"
    p.write_text("- {page: 322, type: present, text: hello world, note: n}\n")  # int page
    ao = run_assertions(p, _sl({1: ["x"]}), {1: "1"}, [1])
    assert ao.verdict is False and "schema error" in ao.lines[0]


def test_slicing_failure_is_advisory(tmp_path):
    p = tmp_path / "qa_assertions.yaml"
    p.write_text("- {page: '1', type: present, text: hello world, note: n}\n")
    ao = run_assertions(p, _sl({1: ["x"]}, ok=False, detail="anchor mismatch"),
                        {1: "1"}, [1])
    assert ao.verdict is None and "NOT evaluated" in ao.lines[0]


def test_valid_fixture_end_to_end(tmp_path):
    p = tmp_path / "qa_assertions.yaml"
    p.write_text(
        "- {page: '46', type: absent, text: 'Now,however', note: seam}\n"
        "- {page: '46', type: present, text: 'Now, however', note: fixed}\n")
    ao = run_assertions(p, _sl({1: ["Now, however true"]}), {1: "46"}, [1])
    assert ao.verdict is True
    ao = run_assertions(p, _sl({1: ["Now,however broken"]}), {1: "46"}, [1])
    assert ao.verdict is False


# ----------------------------------------------------------- schema validation

@pytest.mark.parametrize("entry, needle", [
    ({"page": 322, "type": "present", "text": "abcd", "note": "n"}, "page"),
    ({"page": "1", "type": "present", "text": "abcd"}, "note"),
    ({"page": "1", "type": "present", "text": "", "note": "n"}, "text"),
    ({"page": "1", "type": "bogus", "text": "abcd", "note": "n"}, "type"),
    ({"page": "1", "type": "order", "text": "abcd", "note": "n"}, "text2"),
    ({"page": "1", "type": "present", "text": "abcd", "text2": "xy", "note": "n"},
     "only valid for type order"),
    ({"page": "1", "type": "present", "text": "ab", "note": "n"}, "under 4"),
    ({"page": "1", "type": "present", "text": "abcd", "note": "n", "zzz": 1}, "unknown key"),
    ({"page": "1", "type": "order", "text": "same", "text2": "same", "note": "n"}, "identical"),
    ({"page": "1", "type": "order", "text": "abc", "text2": "abcd", "note": "n"},
     "substrings"),
])
def test_schema_rejections(entry, needle):
    with pytest.raises(AssertionSchemaError) as ei:
        parse_assertions([entry])
    assert needle in str(ei.value)


def test_short_operand_allowed_with_boundary():
    # '4.' is too short by default, but boundary matching makes it safe
    assert parse_assertions(
        [{"page": "1", "type": "present", "text": "4.", "boundary": True,
          "note": "marker"}])
    with pytest.raises(AssertionSchemaError):
        parse_assertions([{"page": "1", "type": "present", "text": "4.",
                           "note": "marker"}])
