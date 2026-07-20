"""Gate 24: per-book regression assertions — machine-checkable tripwires.

Every print-verified defect we found and fixed (the `Now,however` fusions, the
`conJ stantly` cmap garble, the `9318:67` column-interleaved citation) becomes a
tiny assertion cell, so a future change that silently re-breaks it fails LOUDLY,
naming the spot. The gate-level FIRE matrices prove a gate still fires
*somewhere*; these cells pin that a *specific historical defect* stayed fixed.

Cells live in a per-book fixture ``books/<slug>/qa_assertions.yaml`` (a TEST
artifact — tracked, but NOT a build input: it is decoupled from book.yaml so the
build stays byte-reproducible and book.yaml stays a clean record of judgments).
Variant configs get ``qa_assertions.<stem>.yaml`` (the warnings.<stem>.md rule).

Matching is against the shipped EPUB's per-printed-page text (via
``slice_pages``), normalized through the SAME ``core.textnorm.normalize`` both QA
sides use — never a second normalizer. Entry schema::

    - {page: "138", type: present|absent|order|block_present,
       text: "...", text2: "..." (order only),
       boundary: true|false (optional), pno: 138 (optional), note: "..."}

Types:
  present        — the expected string must appear on the page
  absent         — a known-broken form must NOT appear
  order          — string ``text`` must precede ``text2`` on the page
  block_present  — the string must appear within a SINGLE block (structure-adjacent)

Boundary matching (``(?<!\\w)…(?!\\w)``, default ON for ``order``) keeps ``35:8``
from matching inside ``135:8`` without a full tokenizer.

NON-discriminable classes are deliberately excluded (``normalize`` folds them, so
no cell could tell a reverted fix from a good build): punctuation *shape* (curly
vs straight quotes, en/em-dash↔hyphen), whitespace-run (extra/doubled spaces,
NBSP — but a *missing* space IS expressible), soft-hyphen/BOM residue, and
structure loss (paragraph split/merge, blockquote-flatten). Those are owned by
gates 9/10/11/20 (residue) and 23/6 (structure). See specs/qa-methodology.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..core.qa_pageslice import SliceResult
from ..core.textnorm import normalize

_TYPES = ("present", "absent", "order", "block_present")
_ALLOWED_KEYS = {"page", "type", "text", "text2", "boundary", "pno", "note"}
# a non-boundary operand shorter than this is a substring-collision hazard
# (e.g. '4.' inside '164.'); require boundary matching to use one that short
_MIN_OPERAND = 4
_RANGE_RE = re.compile(r"^(.+?)\s*[-–—]\s*(.+)$")


class AssertionSchemaError(ValueError):
    """A malformed fixture — the gate FAILs on this rather than silently
    dropping every check (the worst failure mode for a QA gate)."""


@dataclass(slots=True)
class Assertion:
    page: str
    type: str
    text: str
    note: str
    text2: str = ""
    boundary: bool | None = None   # None => default (order: True, else False)
    pno: int | None = None

    def uses_boundary(self) -> bool:
        return self.boundary if self.boundary is not None else self.type == "order"


@dataclass(slots=True)
class AssertionOutcome:
    verdict: bool | None           # True/False gate; None = advisory (skipped)
    lines: list[str]


# ---------------------------------------------------------------- parsing

def parse_assertions(raw) -> list[Assertion]:
    """Validate the raw YAML sequence into Assertions. Raises
    AssertionSchemaError on any malformed entry."""
    if not isinstance(raw, list):
        raise AssertionSchemaError(
            f"file must be a YAML sequence, got {type(raw).__name__}")
    out: list[Assertion] = []
    for i, entry in enumerate(raw):
        w = f"entry {i}"
        if not isinstance(entry, dict):
            raise AssertionSchemaError(f"{w}: not a mapping")
        extra = set(entry) - _ALLOWED_KEYS
        if extra:
            raise AssertionSchemaError(f"{w}: unknown key(s) {sorted(extra)}")
        typ = entry.get("type")
        if typ not in _TYPES:
            raise AssertionSchemaError(
                f"{w}: type must be one of {list(_TYPES)}, got {typ!r}")
        page = entry.get("page")
        if not isinstance(page, str) or not page.strip():
            raise AssertionSchemaError(
                f"{w}: page must be a non-empty string — quote it, a bare 322 "
                f"parses as int, got {page!r}")
        note = entry.get("note")
        if not isinstance(note, str) or not note.strip():
            raise AssertionSchemaError(f"{w}: note is required (evidence discipline)")
        text = entry.get("text")
        if not isinstance(text, str) or not normalize(text):
            raise AssertionSchemaError(
                f"{w}: text must be a non-empty string (empty after normalize)")
        text2 = entry.get("text2", "")
        if typ == "order":
            if not isinstance(text2, str) or not normalize(text2):
                raise AssertionSchemaError(f"{w}: order requires a non-empty text2")
            nt, nt2 = normalize(text), normalize(text2)
            if nt == nt2:
                raise AssertionSchemaError(f"{w}: order text and text2 are identical")
            if nt in nt2 or nt2 in nt:
                raise AssertionSchemaError(
                    f"{w}: order operands must not be substrings of each other")
        elif text2:
            raise AssertionSchemaError(f"{w}: text2 is only valid for type order")
        boundary = entry.get("boundary")
        if boundary is not None and not isinstance(boundary, bool):
            raise AssertionSchemaError(f"{w}: boundary must be true or false")
        pno = entry.get("pno")
        if pno is not None and (not isinstance(pno, int) or isinstance(pno, bool)):
            raise AssertionSchemaError(f"{w}: pno must be an integer")
        a = Assertion(page=page.strip(), type=typ, text=text, note=note.strip(),
                      text2=text2 or "", boundary=boundary, pno=pno)
        if not a.uses_boundary():
            for lbl, s in (("text", text),
                           ("text2", text2 if typ == "order" else "")):
                if s and len(normalize(s)) < _MIN_OPERAND:
                    raise AssertionSchemaError(
                        f"{w}: {lbl} {s!r} is under {_MIN_OPERAND} normalized "
                        f"chars; set boundary: true to allow a short operand")
        out.append(a)
    return out


# ---------------------------------------------------------------- matching

def _find(needle_norm: str, hay_norm: str, boundary: bool) -> int:
    """First index of needle in hay; -1 if absent. Word-boundary guarded when
    ``boundary`` (``35:8`` will not match inside ``135:8``/``35:80``)."""
    if boundary:
        m = re.search(r"(?<!\w)" + re.escape(needle_norm) + r"(?!\w)", hay_norm)
        return m.start() if m else -1
    return hay_norm.find(needle_norm)


def _resolve(a: Assertion, inv: dict[str, list[int]],
             in_flow: list[int], pos: dict[int, int]) -> tuple[list[int], str]:
    """Resolve an assertion's page to in-flow source page number(s). Returns
    (pnos, error); error != '' means stale/undecidable (fail loudly)."""
    if a.pno is not None:
        if a.pno not in pos:
            return [], f"pno {a.pno} is not an in-flow page"
        return [a.pno], ""
    m = _RANGE_RE.match(a.page)
    if m:                                            # positional in-flow span
        la, lb = m.group(1).strip(), m.group(2).strip()
        pa, pb = inv.get(la, []), inv.get(lb, [])
        if len(pa) != 1 or len(pb) != 1:
            return [], (f"range endpoint(s) unresolved/ambiguous: "
                        f"{la!r}->{pa or 'none'}, {lb!r}->{pb or 'none'}")
        ia, ib = pos[pa[0]], pos[pb[0]]
        if ia > ib:
            return [], f"range {la!r}..{lb!r} is inverted in flow order"
        return in_flow[ia:ib + 1], ""
    pnos = inv.get(a.page, [])
    if not pnos:
        return [], f"page label {a.page!r} is not in the in-flow page-list"
    if len(pnos) > 1:
        return [], (f"page label {a.page!r} maps to multiple in-flow pages "
                    f"{pnos}; disambiguate with an explicit pno:")
    return pnos, ""


def _page_text(pnos: list[int],
               slices: dict[int, list]) -> tuple[str, list[str]]:
    """(normalized page text joined single-space, per-block normalized texts)."""
    blocks = [b for p in pnos for b in slices.get(p, [])]
    joined = " ".join(b.text for b in blocks)
    return normalize(joined), [normalize(b.text) for b in blocks]


def _check_one(a: Assertion, inv, in_flow, pos, slices) -> tuple[str, str]:
    """Returns (kind, message), kind in {'pass','fail','stale'}."""
    pnos, err = _resolve(a, inv, in_flow, pos)
    if err:
        return "stale", f"{a.note} [{a.page}]: {err}"
    page_norm, per_block = _page_text(pnos, slices)
    if not page_norm:
        return "stale", (f"{a.note} [{a.page}]: page has no shipped body text "
                         f"(figure-only or empty slice) — assertion undecidable")
    b = a.uses_boundary()
    nt = normalize(a.text)
    if a.type == "present":
        ok = _find(nt, page_norm, b) >= 0
        return ("pass" if ok else "fail",
                f"{a.note} [{a.page}]: expected {a.text!r} not found")
    if a.type == "absent":
        ok = _find(nt, page_norm, b) < 0
        return ("pass" if ok else "fail",
                f"{a.note} [{a.page}]: forbidden {a.text!r} is present")
    if a.type == "block_present":
        ok = any(_find(nt, blk, b) >= 0 for blk in per_block)
        return ("pass" if ok else "fail",
                f"{a.note} [{a.page}]: {a.text!r} not found within a single block")
    # order
    nt2 = normalize(a.text2)
    i1, i2 = _find(nt, page_norm, b), _find(nt2, page_norm, b)
    if i1 < 0 or i2 < 0:
        miss = a.text if i1 < 0 else a.text2
        return "fail", f"{a.note} [{a.page}]: order operand {miss!r} not found"
    ok = i1 < i2
    return ("pass" if ok else "fail",
            f"{a.note} [{a.page}]: {a.text!r} does not precede {a.text2!r}")


def evaluate(assertions: list[Assertion], sl: SliceResult,
             labels: dict[int, str], in_flow: list[int]) -> tuple[list[str], list[str]]:
    """Run parsed assertions against a SliceResult. Returns (failures, stale),
    failures in file order, stale sorted (determinism)."""
    inv: dict[str, list[int]] = {}
    pos: dict[int, int] = {}
    for idx, p in enumerate(in_flow):
        pos[p] = idx
        inv.setdefault(labels.get(p, str(p)), []).append(p)
    failures: list[str] = []
    stale: list[str] = []
    for a in assertions:
        kind, msg = _check_one(a, inv, in_flow, pos, sl.slices)
        if kind == "fail":
            failures.append(msg)
        elif kind == "stale":
            stale.append(msg)
    return failures, sorted(stale)


# ---------------------------------------------------------------- entry point

def fixture_path(cfg) -> Path:
    """The per-book fixture: qa_assertions.yaml for book.yaml, or
    qa_assertions.<stem>.yaml for a variant config (warnings.<stem>.md rule)."""
    name = ("qa_assertions.yaml" if cfg.path.name == "book.yaml"
            else f"qa_assertions.{cfg.path.stem}.yaml")
    return cfg.path.parent / name


def run_assertions(path: Path, sl: SliceResult, labels: dict[int, str],
                   in_flow: list[int]) -> AssertionOutcome:
    """Load + evaluate the fixture at ``path``. Missing file -> FAIL (the
    fixture is a tracked per-book deliverable; an authored empty file is the
    recorded "no print-verified fixes yet" decision — a missing one is the
    process hole); parse/schema error -> FAIL; slicing failure ->
    advisory-skip."""
    if not path.exists():
        return AssertionOutcome(False, [
            f"fixture missing: {path} — every converted book tracks its "
            "gate-24 regression fixture. Create it ([] records 'no "
            "print-verified fixes yet'); proofread lands one cell per "
            "accepted finding."])
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return AssertionOutcome(
            False, [f"assertions parse error ({path}): {e}"])
    if raw is None:
        return AssertionOutcome(True, [f"0 assertions configured ({path})"])
    try:
        assertions = parse_assertions(raw)
    except AssertionSchemaError as e:
        return AssertionOutcome(
            False, [f"assertions schema error ({path}): {e}"])
    if not assertions:
        return AssertionOutcome(True, [f"0 assertions configured ({path})"])
    if not sl.ok:
        return AssertionOutcome(None, [
            f"page slicing failed — {len(assertions)} assertion(s) NOT evaluated "
            f"(the pagebreak/anchor gate owns this): {sl.detail}"])
    failures, stale = evaluate(assertions, sl, labels, in_flow)
    ok = not failures and not stale
    head = (f"{len(assertions)} assertion(s) from {path.name}; "
            f"{len(failures)} failed, {len(stale)} stale/undecidable")
    return AssertionOutcome(
        ok, [head] + failures[:10]
        + ([f"… and {len(failures) - 10} more failures"]
           if len(failures) > 10 else [])
        + [f"STALE: {s}" for s in stale[:6]])
