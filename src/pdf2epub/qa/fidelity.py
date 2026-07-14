"""Gate 25 — page-aligned fidelity: recall + precision + order + duplication.

Gate 2 (coverage) is one-directional recall over the WHOLE candidate, so it
passes a reordered or duplicated book at ~100%. This gate closes that hole with
three independent, page-aligned checks — the structure-loss witness presence
coverage cannot be:

  1. Corresponding-page recall + precision — normalized ground-truth text of
     source page N vs the shipped EPUB slice for page N (positional, from the
     pagebreak anchors). Recall < min ⇒ page content dropped/misplaced;
     precision < min ⇒ extra/injected/duplicated text on the page.
  2. Order (monotonicity) — the actual candidate offset where each page's text
     best-matches (from paged_coverage per-page diagnostics) must be
     non-decreasing across reading order; a large backward jump ⇒ reorder.
  3. Global duplication — a long span repeated ≥2× anywhere in the shipped
     text (spine + notes, including the preamble before the first anchor and
     text after the last), which the per-page checks alone cannot see.

Sound-math note: paged_coverage's `matched` sums NON-contiguous SequenceMatcher
blocks, so `start..start+matched` is not a real span — order uses only the
first matched block's true offset, and precision/recall are computed
page-locally against the slice, never against the global candidate.

Thresholds are set from the separation margin between deliberate mutations
(test_fidelity.py) and legitimate corpus variation, NOT by fitting to the
corpus. The gating core (recall/precision + order + duplication) ships whole —
there is no advisory-weakening fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz.distance import LCSseq


@dataclass(slots=True)
class FidelityThresholds:
    # Calibrated 2026-07-12 from the SEPARATION margin, not corpus-fitting:
    # legitimate per-page floor across all 6 shipped books (±1-page window, LCS)
    # is min recall 0.840 (BoK chapter openers), min precision 0.822 (M&R);
    # synthetic mutations (test_fidelity.py) score near 0 for recall/precision.
    # Thresholds sit ~0.09 below the legit floor and far above the mutations.
    recall_min: float = 0.75       # page content mostly present in its slice
    precision_min: float = 0.72    # slice mostly justified by its page
    min_gt: int = 60               # skip per-page checks below this gt length
    min_epub: int = 60             # skip precision below this slice length
    trust_recall: float = 0.60     # a page's offset is trusted for order above this
    order_drop: int = 400          # backward offset jump that counts as a reorder
    dup_span: int = 400            # min length of a verbatim span repeated ≥2× to flag


@dataclass(slots=True)
class FidelityResult:
    ok: bool
    lines: list[str]


def _match_chars(a: str, b: str) -> int:
    """Chars of ``a`` present in ``b`` in reading order — the longest common
    subsequence length (rapidfuzz, bit-parallel: fast enough to run on ±1-page
    windows across a 360-page book as a gating check)."""
    if not a or not b:
        return 0
    return LCSseq.similarity(a, b)


def _duplicate_spans(text: str, th: FidelityThresholds) -> list[str]:
    """Verbatim spans of length >= dup_span that occur ≥2× anywhere in the
    shipped text. A Rabin-Karp rolling hash over every window of length
    dup_span (step 1) catches a repeat at ANY alignment — a fixed-stride
    shingle misses two copies whose offsets aren't stride-aligned. A short
    legitimate repeat (epigraph, boilerplate) is below dup_span and is not
    flagged; a duplicated chapter/page is long and is."""
    L = th.dup_span
    n = len(text)
    if n < 2 * L:
        return []
    base, mod = 257, (1 << 61) - 1
    h = 0
    for k in range(L):
        h = (h * base + ord(text[k])) % mod
    pow_l = pow(base, L - 1, mod)
    first: dict[int, int] = {h: 0}
    dup_starts: list[int] = []
    for i in range(1, n - L + 1):
        h = ((h - ord(text[i - 1]) * pow_l) * base + ord(text[i + L - 1])) % mod
        j = first.get(h)
        if j is None:
            first[h] = i
        elif text[i:i + L] == text[j:j + L]:   # verify (guard hash collision)
            dup_starts.append(i)
    spans: list[str] = []
    if dup_starts:
        s = p = dup_starts[0]
        for q in dup_starts[1:]:
            if q - p <= 1:                     # contiguous → same duplicated region
                p = q
            else:
                spans.append(text[s:p + L])
                s = p = q
        spans.append(text[s:p + L])
    return spans


def _order_inversions(per_page, th: FidelityThresholds) -> list[str]:
    """Actual candidate offsets must be non-decreasing across reading order.
    Only pages whose match is strong enough to trust their coordinate are
    considered, and only a jump larger than order_drop counts (small pages and
    repeated matter must not false-fire)."""
    inv: list[str] = []
    high = -1
    high_pno = None
    for pno, matched, plen, start in per_page:
        if plen == 0 or matched / plen < th.trust_recall:
            continue
        if high >= 0 and start < high - th.order_drop:
            inv.append(f"p.{pno} text appears before p.{high_pno} in shipped "
                       f"order (reorder): offset {start} < {high}")
        if start > high:
            high, high_pno = start, pno
    return inv


def check_fidelity(gt_pages: dict[int, str], epub_pages: dict[int, str],
                   in_flow: list[int], candidate: str, per_page,
                   sl_ok: bool, sl_detail: str,
                   th: FidelityThresholds = FidelityThresholds(),
                   dup_allow: list | None = None) -> FidelityResult:
    if not sl_ok:
        # can't align pages ⇒ fidelity is unverifiable ⇒ FAIL (never advisory)
        return FidelityResult(False, [f"page slicing failed — fidelity "
                                      f"unverifiable: {sl_detail}"])
    # ±1-page WINDOW comparisons: poppler's physical-page boundary and the
    # EPUB's inline pagebreak anchor legitimately disagree by up to a paragraph
    # (a page-spanning paragraph, a chapter-opener drop cap), so strict
    # single-page recall false-fires. Windowing tolerates that boundary slop
    # while still localizing to 3 pages — a dropped page (recall: gt absent from
    # its local window) and injected/duplicated text (precision: slice text not
    # justified by the local source window) are still caught; a swap/reorder is
    # caught by the order check, not here.
    idx = {p: i for i, p in enumerate(in_flow)}

    def window(pages: dict[int, str], pno: int) -> str:
        i = idx[pno]
        return " ".join(pages.get(in_flow[j], "")
                        for j in range(max(0, i - 1), min(len(in_flow), i + 2)))

    failures: list[str] = []
    recalls: list[float] = []
    precisions: list[float] = []
    for pno in in_flow:
        gt_text = gt_pages.get(pno, "")
        if len(gt_text) < th.min_gt:
            continue
        recall = _match_chars(gt_text, window(epub_pages, pno)) / len(gt_text)
        recalls.append(recall)
        if recall < th.recall_min:
            failures.append(f"p.{pno}: recall {recall:.3f} < {th.recall_min} "
                            f"(page content dropped)")
        epub_text = epub_pages.get(pno, "")
        if len(epub_text) >= th.min_epub:
            precision = _match_chars(epub_text, window(gt_pages, pno)) / len(epub_text)
            precisions.append(precision)
            if precision < th.precision_min:
                failures.append(f"p.{pno}: precision {precision:.3f} < "
                                f"{th.precision_min} (extra/duplicated text on page)")
    # qa.duplicate_allow: render-verified as-printed repeats (a book quoting
    # one passage twice). An allow licenses only the span it sits inside, and
    # a stale entry FAILS — it can never quietly cover real duplication.
    allows = list(dup_allow or [])
    dup_all = _duplicate_spans(candidate, th)
    dup = [s for s in dup_all
           if not any(a.snippet in s for a in allows)]
    used = {a.snippet for a in allows if any(a.snippet in s for s in dup_all)}
    stale = [f"stale qa.duplicate_allow (no such duplicated span): "
             f"{a.snippet[:60]!r}" for a in allows if a.snippet not in used]
    for span in dup[:5]:
        failures.append(f"duplicated span ({len(span)} chars): {span[:80]!r}…")
    failures += stale[:4]
    inversions = _order_inversions(per_page, th)
    failures += inversions[:5]

    ok = not failures
    lines = [f"{len(recalls)} pages checked; {len(failures)} failures "
             f"({len(dup)} dup spans, {len(inversions)} order inversions); "
             f"allowed repeats: {len(dup_all) - len(dup)} "
             f"({len(stale)} stale); "
             f"min recall {min(recalls, default=1):.3f}, "
             f"min precision {min(precisions, default=1):.3f}"]
    lines += failures[:12]
    return FidelityResult(ok, lines)
