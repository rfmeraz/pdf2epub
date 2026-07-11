# Forked from idml2epub src/idml2epub/nav.py @ 7eb7eac
"""Build nav.xhtml (toc + page-list + landmarks) from emitted headings.

The TOC comes from mapped heading paragraphs — never from the InDesign TOC
story (which the reference EPUB proves is unreliable). The page-list is
complete and monotone by construction (every printed page got an anchor).
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .emit_xhtml import EmitResult, OutFile

_LEVEL = {"h1": 1, "h2": 2, "h3": 3}


def _toc_entries(files: list[OutFile]) -> list[tuple[int, str, str]]:
    """(level, title, href) in document order."""
    out = []
    for f in files:
        for role, hid, text in f.headings:
            out.append((_LEVEL.get(role, 1), text, f"{f.file_name}#{hid}"))
    return out


def _nest(entries: list[tuple[int, str, str]]) -> str:
    """Render nested <ol> from (level, title, href), tolerating level jumps.

    Each heading's nesting DEPTH is its number of strictly-shallower open
    ancestors — so headings sharing the same set of shallower ancestors are
    SIBLINGS regardless of the raw level gap between them (World Wisdom
    editor's-notes chapter subheads, all h3, sit as siblings under the h1
    'EDITOR'S NOTES' even though nothing at h2 intervenes). Depth rises by at
    most one per step, keeping the nav valid: every <li> has at most one child
    <ol>, and an <ol> only ever opens right after an <li>."""
    depths: list[int] = []
    levels: list[int] = []
    for level, _title, _href in entries:
        while levels and levels[-1] >= level:
            levels.pop()
        depths.append(len(levels))
        levels.append(level)

    html: list[str] = ["<ol>"]
    cur = 0
    open_li = False
    for (level, title, href), depth in zip(entries, depths):
        depth = min(depth, cur + 1)  # never jump more than one <ol> deep
        while cur > depth:
            html.append("</li></ol>")
            cur -= 1
            open_li = True  # the parent <li> is open again after closing its <ol>
        if depth > cur:
            html.append("<ol>")  # descend one level (right after the parent <li>)
            cur += 1
            open_li = False
        elif open_li:
            html.append("</li>")
        html.append(f'<li><a href="{escape(href)}">{escape(title)}</a>')
        open_li = True
    while cur > 0:
        html.append("</li></ol>")
        cur -= 1
    if open_li:
        html.append("</li>")
    html.append("</ol>")
    return "".join(html)


def build_nav_xhtml(result: EmitResult, cfg, has_cover: bool) -> str:
    files = result.files + ([result.notes_file] if result.notes_file else [])
    entries = _toc_entries(files)

    pagelist_items = []
    for f in files:
        for label, pid in f.pagebreaks:
            pagelist_items.append(
                f'<li><a href="{f.file_name}#{pid}">{escape(label)}</a></li>'
            )

    landmarks = []
    if has_cover:
        landmarks.append('<li><a epub:type="cover" href="cover.xhtml">Cover</a></li>')
    contents = next((f for f in result.files if f.landmark == "toc"), None)
    if contents:
        landmarks.append(
            f'<li><a epub:type="toc" href="{contents.file_name}">Table of Contents</a></li>'
        )
    # bodymatter = first headed file AFTER the contents page (front matter like
    # a foreword still precedes the true body, but this beats pointing at it)
    candidates = result.files
    if contents in result.files:
        candidates = result.files[result.files.index(contents) + 1 :]
    first_body = next((f for f in candidates if f.headings), None) or next(
        (f for f in result.files if f.headings), None
    )
    if first_body:
        landmarks.append(
            f'<li><a epub:type="bodymatter" href="{first_body.file_name}">Start of Content</a></li>'
        )

    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<!DOCTYPE html>",
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'lang="{cfg.language}" xml:lang="{cfg.language}">',
        f"<head><title>{escape(cfg.title)}</title></head>",
        "<body>",
        '<nav epub:type="toc" role="doc-toc" id="toc"><h1>Contents</h1>',
        _nest(entries),
        "</nav>",
    ]
    if pagelist_items:
        parts += [
            '<nav epub:type="page-list" role="doc-pagelist" id="page-list" hidden="hidden">',
            "<h1>List of Pages</h1><ol>",
            *pagelist_items,
            "</ol></nav>",
        ]
    if landmarks:
        parts += [
            '<nav epub:type="landmarks" id="landmarks" hidden="hidden">',
            "<h1>Landmarks</h1><ol>",
            *landmarks,
            "</ol></nav>",
        ]
    parts += ["</body>", "</html>"]
    return "\n".join(parts)
