"""Gate 25 page-aligned fidelity — mutation tests.

Synthetic fixtures (build/ir is not tracked, so real-book IR can't be reused).
Each page is drawn from a disjoint alphabet with a seeded PRNG, so distinct
pages share ~zero common subsequence (a dropped/foreign page scores near 0)
while a page is internally non-repetitive (no false duplication). Thresholds
are validated by the SEPARATION between these deliberate mutations (must FAIL)
and a clean baseline + a legitimate repeated epigraph (must PASS) — not by
fitting to the corpus.
"""

import random

from pdf2epub.qa.fidelity import FidelityThresholds, check_fidelity

TH = FidelityThresholds()
N = 12
PAGELEN = 700


def _page(i: int) -> str:
    rng = random.Random(1000 + i)
    alpha = [chr(0x100 + i * 25 + k) for k in range(20)]  # disjoint per page
    return "".join(rng.choice(alpha) for _ in range(PAGELEN))


def _assemble(in_flow, epub, gt, preamble="", trailer=""):
    parts = ([preamble] if preamble else []) \
        + [epub[p] for p in in_flow] + ([trailer] if trailer else [])
    candidate = " ".join(parts)
    per_page = []
    for p in in_flow:
        off = candidate.find(gt[p])           # full text (disjoint alphabets → unambiguous)
        matched = len(gt[p]) if off >= 0 else 0
        per_page.append((p, matched, len(gt[p]), off if off >= 0 else 10 ** 9))
    return candidate, per_page


def _run(epub, gt=None, preamble="", trailer=""):
    in_flow = list(range(N))
    gt = gt or {i: _page(i) for i in range(N)}
    candidate, per_page = _assemble(in_flow, epub, gt, preamble, trailer)
    return check_fidelity(gt, epub, in_flow, candidate, per_page, True, "", TH)


def test_clean_baseline_passes():
    epub = {i: _page(i) for i in range(N)}
    res = _run(epub)
    assert res.ok, res.lines


def test_adjacent_page_swap_fails_on_order():
    epub = {i: _page(i) for i in range(N)}
    epub[5], epub[6] = epub[6], epub[5]           # swap content
    res = _run(epub)
    assert not res.ok
    assert any("reorder" in ln or "before" in ln for ln in res.lines), res.lines


def test_duplicate_inside_page_fails_on_precision():
    epub = {i: _page(i) for i in range(N)}
    epub[3] = _page(3) + _page(3)[:400]           # inject a repeat into the page
    res = _run(epub)
    assert not res.ok
    assert any("precision" in ln or "duplicated span" in ln for ln in res.lines), res.lines


def test_duplicate_chapter_before_first_anchor_fails_on_dup():
    epub = {i: _page(i) for i in range(N)}
    preamble = _page(7) + " " + _page(8)          # chapter dup in the preamble
    res = _run(epub, preamble=preamble)
    assert not res.ok
    assert any("duplicated span" in ln for ln in res.lines), res.lines


def test_duplicate_after_final_anchor_fails_on_dup():
    epub = {i: _page(i) for i in range(N)}
    res = _run(epub, trailer=_page(4))            # page repeated after last anchor
    assert not res.ok
    assert any("duplicated span" in ln for ln in res.lines), res.lines


def test_dropped_page_fails_on_recall():
    epub = {i: _page(i) for i in range(N)}
    epub[5] = ""                                  # page content gone
    res = _run(epub)
    assert not res.ok
    assert any("recall" in ln for ln in res.lines), res.lines


def test_legitimate_repeated_epigraph_passes():
    epigraph = "".join(chr(0x2100 + (j * 7) % 90) for j in range(150))  # < dup_span
    gt = {i: _page(i) for i in range(N)}
    gt[2] = epigraph + gt[2]
    gt[8] = epigraph + gt[8]
    epub = dict(gt)                               # shipped == source (legit)
    res = _run(epub, gt=gt)
    assert res.ok, res.lines


def test_slice_failure_is_gating_not_advisory():
    epub = {i: _page(i) for i in range(N)}
    res = check_fidelity({}, epub, list(range(N)), "", [], False, "anchors != pages")
    assert not res.ok
    assert any("unverifiable" in ln for ln in res.lines)
