"""Shared geometric detectors for the semantic block grammar.

This module is the ONE derivation used by BOTH the flow classifier
(calibrated by ``blocks.verse`` specs) and the analyzer / suspect witness
(uncalibrated discovery) — the warnqueue lesson: a single code path so the
build's behavior and the evidence/QA view can never diverge.

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

from dataclasses import dataclass

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
    dt = min(abs(off - t) for t in turns)
    return "base" if db <= dt else "turn"


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
            # prose — M&R p.165); interior and turn-level lines are exempt
            while run and levels[run[0]] == "base" and not _short(run[0]):
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
            ok = len(run) >= 2 and _ragged(run)
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
