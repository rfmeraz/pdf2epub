"""Shared geometric detectors for the semantic block grammar.

This module is the ONE derivation used by BOTH the flow classifier
(calibrated by ``blocks.verse``/``blocks.quotes`` specs) and the analyzer /
suspect witness (uncalibrated discovery) — the warnqueue lesson: a single
code path so the build's behavior and the evidence/QA view can never diverge.

Verse carries NO font/size signal on this corpus (Me & Rumi sets verse in
the body face at body size); the signals are purely geometric:

- two-level left-indent ALTERNATION — a base level and a deeper "turn"
  level the couplet's second line drops to. Justified prose never
  alternates its left edge this way.
- ragged right edges: verse line widths scatter by whole points (measured
  spread 18-215pt), while a justified inset block clusters its right edge
  to sub-point precision — that cluster VETOES verse (the discriminator
  behind flowbuilder._assign_block_right).
- every line ends short of the reference right edge.
- body-ish size (excludes display type and centered heads).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# list-item marker shapes at an entry stop. Decimal covers the corpus's
# print habits: "148. The" (space), "43.Necessary" (prepress lost the
# space — the marker abuts a capital/open quote), "1.·The" / "10.· The"
# (BoK's interpunct separator), and RANGE markers for grouped entries
# ("19-22. I have placed passages 19-22…", M&R). Four-digit years never
# match (d{1,3} cannot absorb them). Bullet covers "• " (I&B/HU) plus the
# common typographic bullets. Both are CALIBRATED signals: an entry line
# must also sit at the spec's entry stop, so a year opening a wrapped
# bibliography line never fires (its x0 is the hang column, not the stop).
LIST_MARKERS: dict[str, re.Pattern] = {
    "decimal": re.compile(
        "^\\d{1,3}(?:-\\d{1,3})?[.)]"
        "(?:[\\s\u00b7\u2027\u2219]|(?=[A-Z\u201c\u2018]))"),
    "bullet": re.compile("^[\u2022\u00b7\u2023\u25aa\u25cf-]\\s"),
}

# calibrated: every verse line must end at least this short of the column
# right (kills the full-width prose line at a base-level indent — M&R p.165)
SHORT_BY = 12.0
# uncalibrated discovery is stricter: the generic short-line margin the
# prose joiner uses, so a suspect is something the joiner would shred
_SUSPECT_SHORT_FLOOR = 18.0
_SUSPECT_SHORT_FRAC = 0.06
_LEVEL_SEP = 6.0      # discovered base/turn levels must differ by this
_LEVEL_CLUSTER = 2.0  # x0 values within this collapse to one level
_RAGGED_MIN = 6.0     # right-edge spread below this = justified, not verse


@dataclass(slots=True)
class VerseGroup:
    start: int                 # index into the page's line sequence
    end: int                   # exclusive
    levels: list[str]          # per line: "base" | "turn"
    stanza_starts: list[bool]  # per line: True opens a new stanza
    base_offsets: list[float] = None   # uncalibrated: discovered levels
    turn_offsets: list[float] = None


def _match_level(off: float, base: list[float], turns: list[float],
                 tol: float) -> str | None:
    if any(abs(off - b) <= tol for b in base):
        return "base"
    if any(abs(off - t) <= tol for t in turns):
        return "turn"
    return None


def _nearest_level(off: float, base: list[float], turns: list[float]) -> str:
    db = min(abs(off - b) for b in base)
    dt = min((abs(off - t) for t in turns), default=None)
    return "base" if dt is None or db <= dt else "turn"


def verse_shape_groups(lines, eff_left: float, ref_right: float,
                       body_size: float, med_lead: float,
                       base: list[float], turns: list[float],
                       tol: float = 2.0, stanza_gap: float = 1.4,
                       size_of=None, blocked=None, forced=None,
                       allow_turn_start: bool = False,
                       carry_levels: list[str] | None = None,
                       ) -> tuple[list[VerseGroup], VerseGroup | None]:
    """Calibrated classification of one page's kept lines against a
    blocks.verse spec. ``lines`` are PdfLine-likes (.x0/.x1/.y0); ``size_of``
    maps a line to its dominant pt size (None = unknown, passes); ``blocked``
    marks lines that can never be verse (figure-region lines, lines inside a
    justified right-edge cluster, class:prose overrides); ``forced`` marks
    class:verse overrides, which skip the geometric candidacy tests.

    Page-turn stitching: ``allow_turn_start`` relaxes the first-line-at-base
    rule when the previous in-flow page ended in ACCEPTED verse (a stanza's
    turn line can start the new page); ``carry_levels`` are the levels of the
    previous page's PENDING tail — a candidate run touching its page bottom
    that could not be accepted alone (e.g. a couplet's base line before the
    turn) — and acceptance of a page-top run is then decided on the UNION.

    Returns ``(groups, tail)``: accepted groups, plus this page's own pending
    tail (unaccepted candidate run ending at the last line) for the caller to
    stitch with the NEXT page — stamped only if that page accepts it."""
    n = len(lines)
    blocked = blocked or [False] * n
    forced = forced or [False] * n
    levels: list[str | None] = []
    for i, ln in enumerate(lines):
        if blocked[i]:
            levels.append(None)
            continue
        off = ln.x0 - eff_left
        lvl = _match_level(off, base, turns, tol)
        if lvl is None and forced[i]:
            lvl = _nearest_level(off, base, turns)
        if lvl is None:
            levels.append(None)
            continue
        if not forced[i]:
            sz = size_of(ln) if size_of else None
            if sz is not None and sz > body_size + 1.0:
                levels.append(None)
                continue
            # single-level specs keep the per-line short test (the ragged
            # inset IS the convention); two-level specs defer it to the
            # boundary trim below — verse lines legitimately run to full
            # measure mid-poem (M&R notes p.370: a turn line ends 4.4pt
            # short of the column right)
            if not turns and ln.x1 > ref_right - SHORT_BY:
                levels.append(None)
                continue
        levels.append(lvl)

    def _short(x) -> bool:
        return lines[x].x1 <= ref_right - SHORT_BY or forced[x]

    cont_top = allow_turn_start or carry_levels is not None
    groups: list[VerseGroup] = []
    tail: VerseGroup | None = None
    raw_runs: list[list[int]] = []
    i = 0
    while i < n:
        if levels[i] is None:
            i += 1
            continue
        j = i
        while j < n and levels[j] is not None:
            j += 1
        if turns:
            # two-level convention: strict base/turn ALTERNATION. Split the
            # candidate run at consecutive-same-level seams — a note
            # paragraph's first line sits at the verse base offset in the
            # M&R notes apparatus, and the split sheds it into a subrun of
            # one, which acceptance then rejects (print-verified p.370)
            k = i
            for x in range(i + 1, j):
                if levels[x] == levels[x - 1] and not forced[x]:
                    raw_runs.append(list(range(k, x)))
                    k = x
            raw_runs.append(list(range(k, j)))
        else:
            raw_runs.append(list(range(i, j)))
        i = j

    for run in raw_runs:
        if turns:
            # boundary trim: the first/last line of a poem at a BASE level
            # must end short (a full-measure line at the paragraph indent is
            # prose — M&R p.165); interior and turn-level lines are exempt,
            # and so is a PAGE-TOP line continuing the previous page's
            # verse — mid-poem base lines legitimately run near-full (M&R
            # p.371: 'This thirst in our souls…' ends 7.3pt short as the
            # second couplet of the poem the page turn interrupted)
            while run and levels[run[0]] == "base" and not _short(run[0]) \
                    and not (run[0] == 0 and cont_top):
                run = run[1:]
            while run and levels[run[-1]] == "base" and not _short(run[-1]):
                run = run[:-1]
        # trim leading turn lines: a group must open at a base level unless
        # it continues the previous page's verse across the page turn
        while run and levels[run[0]] == "turn" and not forced[run[0]] \
                and not (run[0] == 0 and cont_top):
            run = run[1:]
        if not run:
            continue
        continuation = cont_top and run[0] == 0
        lv = [levels[x] for x in run]
        # acceptance, two conventions:
        # - two-level spec (turns configured): >=2 lines including a turn —
        #   the alternation prose never produces;
        # - single-level spec (no turns, I&B-style): >=2 lines, ragged right
        #   edges (a justified block clusters; its block_right veto usually
        #   fires first, but 2-line insets can miss the cluster walker).
        # A page-top run continuing the previous page's verse is accepted
        # as-is (accepted verse above) or on the UNION with the carried
        # pending tail (its base line is on that page).
        single_level = not turns

        def _ragged(idxs) -> bool:
            if any(forced[x] for x in idxs):
                return True
            x1s = [lines[x].x1 for x in idxs]
            return max(x1s) - min(x1s) >= _RAGGED_MIN

        if continuation and carry_levels is not None:
            ok = len(carry_levels) + len(run) >= 2 and \
                (single_level or "turn" in lv or "turn" in carry_levels)
        elif continuation:
            ok = True
        elif single_level:
            # equal-length couplets fail the ragged test (I&B p.100's Jami
            # pair ends 0.33pt apart) but justified prose clusters AT its
            # block margin — a pair ending far short of the reference right
            # cannot be a justified block (the near-margin case is already
            # vetoed upstream by blocked/justified_rights)
            ok = len(run) >= 2 and (
                _ragged(run)
                or max(lines[x].x1 for x in run) <= ref_right - 40.0)
        else:
            ok = len(run) >= 2 and "turn" in lv
        if not ok:
            if run[-1] == n - 1:
                # candidate touches the page bottom: pending tail for the
                # caller to stitch with the next page's top run
                tail = VerseGroup(
                    start=run[0], end=run[-1] + 1, levels=lv,
                    stanza_starts=[pos == 0 or
                                   (lines[x].y0 - lines[run[pos - 1]].y0)
                                   > stanza_gap * med_lead
                                   for pos, x in enumerate(run)])
            continue
        starts = []
        for pos, x in enumerate(run):
            gap = (lines[x].y0 - lines[run[pos - 1]].y0) if pos else 0.0
            if pos == 0:
                # cross-page continuation joins the open stanza (the
                # _break_before cross-page default, mirrored); a fresh
                # group opens its own stanza
                starts.append(not continuation)
            else:
                starts.append(gap > stanza_gap * med_lead)
        groups.append(VerseGroup(
            start=run[0], end=run[-1] + 1, levels=lv, stanza_starts=starts))
    return groups, tail


def verse_shape_suspects(lines, eff_left: float, ref_right: float,
                         body_size: float, med_lead: float,
                         size_of=None, blocked=None,
                         centered=None) -> list[VerseGroup]:
    """Uncalibrated discovery: verse-shaped runs with NO spec — evidence for
    the analyzer and the build's verse-suspect witness. Deliberately stricter
    than the calibrated classifier (>=3 lines, discovered two-level structure,
    ragged right edges) so corpus-wide precision stays high: a firing is a
    render-verify queue item, never an auto-classification. ``centered``
    marks lines whose pstyle is /center (a centered title list is not verse)."""
    n = len(lines)
    blocked = blocked or [False] * n
    centered = centered or [False] * n
    col_w = max(1.0, ref_right - eff_left)
    short_by = max(_SUSPECT_SHORT_FLOOR, _SUSPECT_SHORT_FRAC * col_w)
    cand: list[bool] = []
    for i, ln in enumerate(lines):
        if blocked[i] or centered[i] or getattr(ln, "vertical", False):
            cand.append(False)
            continue
        sz = size_of(ln) if size_of else None
        if sz is not None and sz > body_size + 1.0:
            cand.append(False)
            continue
        if ln.x0 < eff_left - 2.0:  # left of the column = furniture/artifact
            cand.append(False)
            continue
        cand.append(ln.x1 <= ref_right - short_by)

    groups: list[VerseGroup] = []
    i = 0
    while i < n:
        if not cand[i]:
            i += 1
            continue
        j = i
        while j < n and cand[j]:
            j += 1
        run = list(range(i, j))
        i = j
        if len(run) < 3:
            continue
        # cluster left edges into levels
        offs = sorted(lines[x].x0 - eff_left for x in run)
        levels: list[float] = []
        for off in offs:
            if not levels or off - levels[-1] > _LEVEL_CLUSTER:
                levels.append(off)
        if len(levels) >= 2 and levels[1] - levels[0] >= _LEVEL_SEP \
                and levels[0] >= _LEVEL_SEP:
            # two-level convention (M&R): base/turn alternation. The base
            # must itself be a REAL inset (>= 6pt off the column left):
            # flush-left short lines whose "turn" equals the book's ordinary
            # paragraph indent are prose/dialogue, the corpus scan's one
            # systematic false-positive class (M&R base 0-2 / turn 9-11)
            base_off, turn_offs = levels[0], levels[1:]
            lv = ["base"
                  if lines[x].x0 - eff_left <= base_off + _LEVEL_CLUSTER
                  else "turn" for x in run]
            if lv[0] != "base" or "turn" not in lv:
                continue
        elif len(levels) == 1 and len(run) >= 4 and levels[0] >= _LEVEL_SEP:
            # single-level convention (I&B): every line at ONE real inset
            # (>= 6pt off the column left — flush-left short runs are prose
            # or apparatus); stricter length bar than two-level
            base_off, turn_offs = levels[0], []
            lv = ["base"] * len(run)
        else:
            continue
        # ragged right edges (a justified block clusters to sub-point)
        x1s = [lines[x].x1 for x in run]
        if max(x1s) - min(x1s) < _RAGGED_MIN:
            continue
        starts = []
        for pos, x in enumerate(run):
            gap = (lines[x].y0 - lines[run[pos - 1]].y0) if pos else 0.0
            starts.append(pos == 0 or gap > 1.4 * med_lead)
        groups.append(VerseGroup(
            start=run[0], end=run[-1] + 1, levels=lv, stanza_starts=starts,
            base_offsets=[round(base_off, 1)],
            turn_offsets=[round(t, 1) for t in turn_offs]))
    return groups


# ---------------------------------------------------------------------------
# Block quotes. The discriminating signal is the OPPOSITE of verse: a print
# block quote is a JUSTIFIED inset block — its lines share one left inset and
# cluster their right edge to sub-point precision (I&B: 18pt off both body
# edges; BoK: 36pt off the left only). The same cluster that vetoes verse IS
# the quote witness. A body paragraph's lone first-line indent sits at the
# same x0 as a quote line (I&B indents 18pt too) but is a run of ONE — it
# never earns a justified right, so the witness rejects it.

_JUST_LEFT_TOL = 3.0   # x0 spread that still reads as one left edge
_JUST_RIGHT_TOL = 2.0  # x1 spread that still reads as one justified margin
_ANCHOR_TOL = 2.0      # x0/x1 spread that still reads as one body edge


def justified_rights(lines) -> list[float | None]:
    """Per line: the justified right margin of the line's own inset block
    (the largest x1 that >=2 lines in its same-x0 run reach), or None when
    the line is not in a tight-clustered justified run — a lone inset line,
    or ragged verse. The ONE derivation behind flowbuilder's block_right and
    the quote detectors here."""
    out: list[float | None] = [None] * len(lines)
    i, n = 0, len(lines)
    while i < n:
        j = i + 1
        x0 = lines[i].x0
        while j < n and abs(lines[j].x0 - x0) <= _JUST_LEFT_TOL:
            j += 1
        if j - i >= 2:
            xs = [lines[x].x1 for x in range(i, j)]
            # a justified block puts MOST lines at its margin; two
            # coincidental edges in a long ragged run must not fire (13
            # ragged verse lines had a chance pair 0.9pt apart and the
            # whole poem was vetoed as a quote — I&B p.86)
            need = max(2, -(-2 * len(xs) // 5))  # ceil(0.4 * n)
            margin = next(
                (c for c in sorted(xs, reverse=True)
                 if sum(1 for x in xs
                        if abs(x - c) <= _JUST_RIGHT_TOL) >= need),
                None)
            if margin is not None:
                for x in range(i, j):
                    out[x] = margin
        i = j
    return out


def body_anchors(lines, body_size: float, size_of=None,
                 skip=None) -> tuple[float, float] | None:
    """The page's OWN body-block edges: the smallest x0 and the largest x1
    that >=2 body-size lines each share within a couple of points. Quote
    insets are measured from these, NOT from the modal column + shift frame —
    on quote-heavy pages the shift detector keys off the quote inset itself
    (I&B rectos: 22 quote lines at x0=81 outvote 10 body lines at 63).
    Returns None when the page has no such clusters (sparse/display pages)."""
    n = len(lines)
    skip = skip or [False] * n
    xs0, xs1 = [], []
    for i, ln in enumerate(lines):
        if skip[i] or getattr(ln, "vertical", False):
            continue
        sz = size_of(ln) if size_of else None
        if sz is not None and abs(sz - body_size) > 2.0:
            continue
        xs0.append(ln.x0)
        xs1.append(ln.x1)
    left = next((c for c in sorted(xs0)
                 if sum(1 for x in xs0 if abs(x - c) <= _ANCHOR_TOL) >= 2),
                None)
    right = None
    if left is not None:
        # the right edge is witnessed ONLY by lines STARTING at the left
        # anchor (body continuation lines): a cluster over ALL lines pairs
        # coincidental ragged edges (a verse base line + an intro's short
        # end 1pt apart dragged the anchor 90pt left). Prefer a >=2
        # cluster among at-left lines; a single full-measure body line
        # witnesses alone (quote-heavy pages) — underestimates only MISS.
        at_left = [x1 for x0, x1 in zip(xs0, xs1)
                   if abs(x0 - left) <= _JUST_LEFT_TOL]
        right = next((c for c in sorted(at_left, reverse=True)
                      if sum(1 for x in at_left
                             if abs(x - c) <= _ANCHOR_TOL) >= 2),
                     None)
        if right is None:
            right = max(at_left, default=None)
    if left is None or right is None or right - left < 100.0:
        return None
    return left, right


@dataclass(slots=True)
class QuoteRun:
    start: int   # index into the page's line sequence
    end: int     # exclusive
    left_offset: float = 0.0   # discovered inset off the body-left anchor
    right_offset: float = 0.0  # discovered inset off the body-right anchor


def _dropcap_wrap_veto(lines, body_size: float, size_of=None) -> list[bool]:
    """Lines sitting beside a drop-cap initial: a wide 32pt letter pushes its
    2-4 wrap lines to a deep inset, justified to the body right — exactly a
    left-only quote shape (BoK 'A'/'K'/'G' initials wrap at 36pt, the SAME
    inset as the book's real quotes). Veto any line whose vertical extent
    overlaps an oversized 1-2 letter line's."""
    n = len(lines)
    veto = [False] * n
    if size_of is None:
        return veto
    for i, ln in enumerate(lines):
        sz = size_of(ln)
        if sz is None or sz < 2 * body_size:
            continue
        t = ln.text().strip() if hasattr(ln, "text") else ""
        if not (1 <= len(t) <= 2 and t.isalpha()):
            continue
        for j, other in enumerate(lines):
            # a wrap line starts AT the initial's right edge; a quote line
            # under the letter's descender box does not (BoK p.259: the
            # hadith opens 8.5pt right of the 'ʿA' while still overlapping
            # its box vertically — it must stay classifiable)
            if j != i and other.y0 < ln.y1 and other.y1 > ln.y0 \
                    and abs(other.x0 - ln.x1) <= 6.0:
                veto[j] = True
    return veto


def quote_shape_runs(lines, left_anchor: float, right_anchor: float,
                     left_inset: float, right_inset: float,
                     body_size: float, tol: float = 3.0, size_of=None,
                     rights=None, blocked=None, forced=None,
                     allow_continuation_top: bool = False,
                     ) -> list[QuoteRun]:
    """Calibrated classification of one page's kept lines against a
    blocks.quotes spec: maximal runs of consecutive lines whose x0 sits at
    ``left_anchor + left_inset`` (+-tol) AND whose justified right margin
    (``rights``, from :func:`justified_rights`) sits at ``right_anchor -
    right_inset`` (+-tol). ``blocked`` marks lines that can never be quote
    (figure-region lines, class:prose overrides, lines already classified
    verse); ``forced`` marks class:quote overrides, which skip the geometric
    tests. A run needs >=2 candidate lines (a single inset line has no
    justified witness) unless it contains a forced line.

    Two shapes the bare cluster witness misses (I&B readers, Phase F):
    a quote PARAGRAPH's indented first line (a dialogue turn inside the
    quotation sits at lt + ~18, a run of one — it joins as candidate when
    an adjacent line is a base candidate and it stays inside the quote
    measure), and a 2-line quotation tail at the TOP of a page whose
    previous page ended mid-quote (``allow_continuation_top``: the page-top
    run qualifies without a cluster when every line fits the measure)."""
    n = len(lines)
    rights = rights if rights is not None else justified_rights(lines)
    blocked = blocked or [False] * n
    forced = forced or [False] * n
    dropcap = _dropcap_wrap_veto(lines, body_size, size_of)
    lt = left_anchor + left_inset
    rt = right_anchor - right_inset
    cand: list[bool] = []
    for i, ln in enumerate(lines):
        if blocked[i]:
            cand.append(False)
            continue
        if forced[i]:
            cand.append(True)
            continue
        if dropcap[i]:
            cand.append(False)
            continue
        sz = size_of(ln) if size_of else None
        if sz is not None and sz > body_size + 1.0:
            cand.append(False)
            continue
        cand.append(abs(ln.x0 - lt) <= tol and rights[i] is not None
                    and abs(rights[i] - rt) <= tol)
    # indented first lines of quote paragraphs: x0 in (lt+6 .. lt+30),
    # right edge inside the quote measure, adjacent to a base candidate.
    # A body paragraph's own indent sits at lt itself (body-left + indent =
    # the quote inset on this corpus) and its lines run PAST rt — rejected.
    for i, ln in enumerate(lines):
        if cand[i] or blocked[i] or dropcap[i]:
            continue
        sz = size_of(ln) if size_of else None
        if sz is not None and sz > body_size + 1.0:
            continue
        if 6.0 < ln.x0 - lt <= 30.0 and ln.x1 <= rt + tol and (
                (i > 0 and cand[i - 1]) or (i + 1 < n and cand[i + 1])):
            cand[i] = True
    if allow_continuation_top and n and not blocked[0] and not cand[0]:
        j = 0
        ok = True
        while j < n and not blocked[j] and lines[j].x0 >= lt - tol and \
                lines[j].x0 <= lt + 30.0 and lines[j].x1 <= rt + tol:
            sz = size_of(lines[j]) if size_of else None
            if sz is not None and sz > body_size + 1.0:
                ok = False
                break
            j += 1
        if ok and j >= 1 and abs(lines[0].x0 - lt) <= tol:
            for x in range(j):
                cand[x] = True
    runs: list[QuoteRun] = []
    i = 0
    while i < n:
        if not cand[i]:
            i += 1
            continue
        j = i
        while j < n and cand[j]:
            j += 1
        if j - i >= 2 or any(forced[x] for x in range(i, j)):
            runs.append(QuoteRun(start=i, end=j,
                                 left_offset=left_inset,
                                 right_offset=right_inset))
        i = j
    return runs


def quote_shape_suspects(lines, body_size: float, size_of=None,
                         skip=None) -> list[QuoteRun]:
    """Uncalibrated discovery for the analyzer: runs of >=3 consecutive
    lines sharing one justified right margin at a REAL left inset (>=6pt off
    the page's own body-left anchor) — evidence for drafting blocks.quotes
    specs, never an auto-classification. Left-only insets (right edge at the
    body margin, BoK-style) need >=4 lines: drop-cap wrap lines share that
    exact shape at 2-3 lines."""
    anchors = body_anchors(lines, body_size, size_of=size_of, skip=skip)
    if anchors is None:
        return []
    left, right = anchors
    rights = justified_rights(lines)
    n = len(lines)
    skip = skip or [False] * n
    dropcap = _dropcap_wrap_veto(lines, body_size, size_of)
    cand: list[bool] = []
    for i, ln in enumerate(lines):
        if skip[i] or dropcap[i] or rights[i] is None:
            cand.append(False)
            continue
        sz = size_of(ln) if size_of else None
        # quotes are set at (or a shade under) body size; well-below-body
        # runs at an inset are footnote hanging-indent turnovers (BoK's
        # 8.5pt notes fired 45 bogus 14/1pt runs) — the flow never sees
        # them (footnotes split first), but the DRAFT specs must not
        if sz is not None and not (body_size - 2.0 < sz <= body_size + 1.0):
            cand.append(False)
            continue
        cand.append(ln.x0 - left >= _LEVEL_SEP
                    and rights[i] <= right + _ANCHOR_TOL)
    out: list[QuoteRun] = []
    i = 0
    while i < n:
        if not cand[i]:
            i += 1
            continue
        j = i
        while j < n and cand[j] and abs(lines[j].x0 - lines[i].x0) <= \
                _JUST_LEFT_TOL:
            j += 1
        run = list(range(i, j))
        i = j
        l_off = round(min(lines[x].x0 for x in run) - left, 1)
        r_off = round(right - max(rights[x] for x in run), 1)
        if len(run) >= (3 if r_off >= _LEVEL_SEP else 4):
            out.append(QuoteRun(start=run[0], end=run[-1] + 1,
                                left_offset=l_off, right_offset=r_off))
    return out
