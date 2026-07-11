"""Linked index locators (a generic, opt-in map-stage transform).

Back-of-book indexes ship — via ``flow.columns`` (the usual 2-/3-column index)
or a single-column index tagged with the ``index`` role — as plain paragraphs
whose page numbers are dead text. DAISY's recommended index links every locator
to the referenced page (https://kb.daisy.org/publishing/docs/html/indexes.html).
The pipeline already emits a ``pg-<label>`` anchor for every printed page, and
the ``RunFormat.link`` -> ``{XREF|page:<label>}`` -> ``resolve_crossref_links``
chain (built for the World Wisdom imprint) turns a marked run into a real
cross-file href. This transform applies that chain to index entries and wraps
the index in a ``<section epub:type="index" role="doc-index">`` container
(signalled by ``block_class = "index"``, gathered by the emitter).

Doctrine: linking WRAPS, never rewrites — the printed numbers are untouched. The
pass is opt-in (a ``flow.columns[].index: true`` flag or the ``index`` role) and
a strict no-op otherwise, so every other book is byte-identical. A number becomes
a link only when its ``pg-<label>`` anchor actually exists, so a broken index
link is structurally impossible; numeric locators with no matching anchor
(out-of-range, roman front-matter, ``189n.4`` note suffixes) ship as plain text
and are counted in the advisory ``index-locator-unlinked`` warning.
"""

from __future__ import annotations

import re

from .core.model import InlinePageBreak, PageAnchor, Paragraph
from .core.runlinks import apply_link

_HEAD_ROLES = ("h1", "h2", "h3")

# A page-number locator: a standalone number, or a first-last range (en/em dash
# or hyphen). Guards:
#   * ``(?<![:\w.])`` — reject a number preceded by a letter/digit/``.``/``:``
#     (so ``MP3``, the ``14`` of ``3.14``, and the ``8`` of a ``35:8`` citation
#     are skipped);
#   * ``(?![:\w])`` — reject a number followed by a letter/digit/``:`` (so the
#     ``35`` of ``35:8``, ``20th``, and the ``n`` of a ``322n`` note suffix are
#     skipped).
# A locator followed by ordinary punctuation/space/end (``322,`` ``322.``
# ``322)`` ``322``) still matches. group(1) is the target label (a range links to
# its FIRST page).
_LOCATOR_RE = re.compile(r"(?<![:\w.])(\d+)(?:[–—-]\d+)?(?![:\w])")


def _page_labels(blocks) -> set[str]:
    """Every printed-page anchor label present — the valid link targets."""
    labels: set[str] = set()
    for b in blocks:
        if isinstance(b, (PageAnchor, InlinePageBreak)):
            labels.add(b.label)
        elif isinstance(b, Paragraph):
            for it in b.items:
                if isinstance(it, InlinePageBreak):
                    labels.add(it.label)
    return labels


def _page_of(p: Paragraph) -> int:
    """Physical page ordinal a paragraph started on (``SourceRef.story_id`` is
    ``p{page:04d}``); -1 if unparseable."""
    sid = p.src.story_id
    try:
        return int(sid[1:])
    except (ValueError, IndexError):
        return -1


def link_index_locators(res, cfg, say=print) -> None:
    """Link page-number locators in the book's index(es). No-op unless a
    ``flow.columns`` block is flagged ``index: true`` or a paragraph carries the
    ``index`` role."""
    blocks = res.flow.blocks

    # index page set from flagged columned blocks (physical ordinals, the space
    # flow.columns and SourceRef.story_id both use)
    idx_pages: set[int] = set()
    for cs in getattr(cfg, "flow_columns", []) or []:
        if getattr(cs, "index", False):
            idx_pages.update(cs.pages)

    # single-column index: the span from the first to the last role=='index'
    # paragraph (so interleaved letter-group heads are inside the container too)
    role_idx = [i for i, b in enumerate(blocks)
                if isinstance(b, Paragraph) and (b.role or "") == "index"]
    role_span = (role_idx[0], role_idx[-1]) if role_idx else None

    if not idx_pages and role_span is None:
        return  # opt-in: byte-identical when unused

    from .flowbuilder import _Warn  # local: flowbuilder imports this lazily

    labels = _page_labels(blocks)
    n_link = n_para = n_unlinked = 0

    for i, b in enumerate(blocks):
        if not isinstance(b, Paragraph):
            continue
        in_index = (_page_of(b) in idx_pages) or (
            role_span is not None and role_span[0] <= i <= role_span[1])
        if not in_index:
            continue
        role = b.role or "p"

        # container: tag every non-h1 index paragraph so the emitter wraps the
        # contiguous run in <section epub:type="index">. Leave the section's own
        # h1 title untagged (it splits the file; the section opens after it).
        # Don't clobber a real flow classification (verse/quote/list).
        if role != "h1" and b.block_class is None:
            b.block_class = "index"

        if role in _HEAD_ROLES:
            continue  # link locators in entry paragraphs only, not headings
        n_para += 1

        text = b.text()
        spans: list[tuple[int, int, str]] = []
        for m in _LOCATOR_RE.finditer(text):
            label = m.group(1)
            if label in labels:
                spans.append((m.start(), m.end(), label))
            else:
                n_unlinked += 1
                res.warns.append(_Warn(
                    f"index locator {text[m.start():m.end()]!r} has no matching "
                    f"page anchor — left unlinked",
                    page=_page_of(b), code="index-locator-unlinked"))
        # apply_link preserves total text length, so offsets computed over the
        # original text stay valid across successive calls
        items = b.items
        for start, end, label in spans:
            items = apply_link(items, start, end, f"page:{label}")
            n_link += 1
        b.items = items

    say(f"  index-locators: linked {n_link} locator(s) in {n_para} entry "
        f"paragraph(s)" + (f"; {n_unlinked} unlinked" if n_unlinked else ""))
