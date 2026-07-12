# Forked from idml2epub src/idml2epub/qa/ordercheck.py @ 7eb7eac
"""Reading-order gate.

Closes the gate gap found in the pilot: the Foreword-split bug (a heading
orphaned from its body by a mis-spliced story) passed every other check —
text coverage sees presence, nav sees links, neither sees ORDER.

Two independent checks, pure functions over extracted sequences so they are
unit-testable without an EPUB:

1. Heading placement vs the printed table of contents. The book's own TOC
   pairs every entry with a printed page ("Foreword ... ix"). In the EPUB,
   the nearest page marker at-or-before each matching heading must be that
   page — or the one just before it, since page markers are placed with
   paragraph granularity. A heading with the wrong page context (or none at
   all, like the orphaned Foreword) is a reading-order violation.

2. Orphaned headings (informational, not gating): a spine file containing a
   heading but almost no body content and no figure. This is the signature
   of a heading separated from its text — but it is also what a legitimate
   part-title page looks like (the pilot has two), so it is reported for
   human eyes rather than failing the build. The page-agreement check is
   what actually gates the orphaned-heading bug when a TOC and page markers
   exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .qa_epubload import LoadedEpub
from .textnorm import normalize

_XHTML = "{http://www.w3.org/1999/xhtml}"
_EPUB = "{http://www.idpf.org/2007/ops}"

MATCH_THRESHOLD = 85.0


@dataclass
class OrderResult:
    checked: int = 0
    matched_entries: int = 0
    violations: list[str] = field(default_factory=list)
    orphan_headings: list[str] = field(default_factory=list)  # informational
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


# ---------------------------------------------------------------------------
# pure logic (unit-testable)


def _match(entry_title: str, heading: str) -> float:
    t, h = entry_title.lower().strip(), heading.lower().strip()
    score = fuzz.ratio(t, h)
    if h and (t.startswith(h) or h.startswith(t)):
        score = max(score, 90.0)
    return score


def check_heading_pages(
    spine_seq: list[tuple[str, str]],
    toc_entries: list[tuple[str, str]],
    page_order: list[str],
) -> OrderResult:
    """spine_seq: linear spine events, ('page', label) | ('heading', text).
    toc_entries: (title, printed label) from the book's printed contents.
    page_order: all printed labels in order (for the one-page slack)."""
    res = OrderResult()
    prev_of = {page_order[i]: page_order[i - 1] for i in range(1, len(page_order))}

    # heading -> label of nearest page marker at-or-before it
    heading_page: list[tuple[str, str | None]] = []
    current: str | None = None
    for kind, value in spine_seq:
        if kind == "page":
            current = value
        else:
            heading_page.append((value, current))

    used: set[int] = set()

    def _norm(s: str) -> str:
        return " ".join(s.lower().split())

    def process(title: str, label: str) -> None:
        if not label:
            # a printed-TOC part-divider label carrying no folio ('Appendix'):
            # there is no page in the source to verify it against, so it is out
            # of this gate's scope (it still ships + links via the contents pass)
            res.notes.append(
                f"TOC part-divider entry has no folio to verify (info): {title!r}")
            return
        res.checked += 1
        best_score = 0.0
        candidates: list[int] = []
        for i, (heading, _) in enumerate(heading_page):
            if i in used:
                continue
            score = _match(title, heading)
            if score > best_score:
                best_score, candidates = score, [i]
            elif score == best_score:
                candidates.append(i)
        if not candidates or best_score < MATCH_THRESHOLD:
            res.notes.append(f"TOC entry has no matching heading (info): {title!r}")
            return
        # a book may repeat a heading (part-title pages); among equally good
        # title matches, prefer the one on the page the contents assigns
        allowed = {label, prev_of.get(label)}
        best_i = next(
            (i for i in candidates if heading_page[i][1] in allowed), candidates[0]
        )
        used.add(best_i)
        res.matched_entries += 1
        heading, at_page = heading_page[best_i]
        if at_page not in allowed:
            res.violations.append(
                f"heading {heading!r} sits at printed page {at_page!r}, "
                f"but the book's contents places it on {label!r}"
            )

    # exact-title entries claim their headings FIRST: a grouping bookmark
    # with no printed heading of its own ('Indexes', BoK back matter) must
    # not fuzzy-steal another entry's heading ('Index') and report it as
    # sitting on the wrong page
    heading_norms = {_norm(h) for h, _ in heading_page}
    deferred = [e for e in toc_entries if _norm(e[0]) not in heading_norms]
    for title, label in toc_entries:
        if _norm(title) in heading_norms:
            process(title, label)
    for title, label in deferred:
        process(title, label)
    return res


def check_orphan_headings(
    files: list[tuple[str, bool, int, bool]],
) -> list[str]:
    """files: (href, has_heading, body_chars_excluding_headings, has_figure)."""
    return [
        f"{href}: contains a heading but almost no content "
        f"({chars} chars, no figure) — heading may be orphaned from its body"
        for href, has_heading, chars, has_figure in files
        if has_heading and not has_figure and chars < 20
    ]


# ---------------------------------------------------------------------------
# EPUB extraction


def _spine_sequence(ep: LoadedEpub) -> tuple[list[tuple[str, str]], list[tuple[str, bool, int, bool]]]:
    seq: list[tuple[str, str]] = []
    file_stats: list[tuple[str, bool, int, bool]] = []
    for doc in ep.spine_docs():
        has_heading = False
        heading_chars = 0
        body_chars = 0
        has_figure = False
        body = doc.root.find(f"{_XHTML}body")
        if body is None:
            continue
        for el in body.iter():
            tag = getattr(el, "tag", "")
            if not isinstance(tag, str) or not tag.startswith(_XHTML):
                continue
            local = tag[len(_XHTML):]
            if local in ("h1", "h2", "h3", "h4"):
                text = normalize(" ".join(el.itertext()))
                seq.append(("heading", text))
                has_heading = True
                heading_chars += len(text)
            elif (el.get(f"{_EPUB}type") or "") == "pagebreak":
                label = el.get("aria-label") or ""
                if label:
                    seq.append(("page", label))
            elif local == "img":
                has_figure = True
        body_chars = len(normalize(" ".join(body.itertext())))
        file_stats.append(
            (doc.href, has_heading, max(body_chars - heading_chars, 0), has_figure)
        )
    return seq, file_stats


def check_reading_order(
    ep: LoadedEpub,
    toc_entries: list[tuple[str, str]],
    page_order: list[str],
) -> OrderResult:
    seq, file_stats = _spine_sequence(ep)
    if toc_entries and any(k == "page" for k, _ in seq):
        res = check_heading_pages(seq, toc_entries, page_order)
    else:
        res = OrderResult()
        res.notes.append(
            "heading/page agreement skipped (no printed-TOC entries or no page markers)"
        )
    res.orphan_headings = check_orphan_headings(file_stats)
    return res
