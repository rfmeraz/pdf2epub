"""Inline cross-reference link markers over a Paragraph's run list.

A transform (an imprint, or the generic index-locator pass) marks a character
range of a paragraph as a link by setting :attr:`RunFormat.link` on the runs
covering that range. The emitter (:func:`core.emit_xhtml._run_html`) wraps any
run whose ``fmt.link`` is set in an ``<a href="{XREF|...}">`` placeholder, and
``resolve_crossref_links`` rewrites the placeholder to a real ``<file>#<id>``
href once every file's anchors are known.

``apply_link`` is the shared primitive that turns a ``[start, end)`` character
range into linked sub-run(s) WITHOUT touching the text — it only splits runs at
the boundaries and stamps ``fmt.link`` on the middle. Because total text is
preserved, successive calls with offsets computed over the ORIGINAL text stay
valid (e.g. stamp a note ref then a page ref on the same paragraph).
"""

from __future__ import annotations

from dataclasses import replace

from .model import TextRun


def apply_link(items, start: int, end: int, link: str) -> list:
    """Return ``items`` with the TextRun text over char range ``[start, end)``
    (offsets counted over TextRun text only) carrying ``fmt.link = link``.
    Splits runs at the boundaries; non-text items pass through untouched. Total
    text is unchanged, so successive calls with original offsets stay valid."""
    out: list = []
    pos = 0
    for it in items:
        if not isinstance(it, TextRun):
            out.append(it)
            continue
        t = it.text
        a, b = pos, pos + len(t)
        pos = b
        if b <= start or a >= end:
            out.append(it)
            continue
        s = max(start, a) - a
        e = min(end, b) - a
        if s > 0:
            out.append(TextRun(t[:s], it.fmt))
        out.append(TextRun(t[s:e], replace(it.fmt, link=link)))
        if e < len(t):
            out.append(TextRun(t[e:], it.fmt))
    return out
