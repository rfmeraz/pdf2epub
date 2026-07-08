# Forked from idml2epub src/idml2epub/qa/navcheck.py @ 7eb7eac
"""Navigation integrity: every href resolves; page-list complete and ordered."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from .qa_epubload import LoadedEpub

_XHTML = "{http://www.w3.org/1999/xhtml}"
_EPUB = "{http://www.idpf.org/2007/ops}"
_NCX = "{http://www.daisy.org/z3986/2005/ncx/}"

_ROMAN = re.compile(r"^[ivxlcdm]+$")


@dataclass
class NavResult:
    broken_links: list[str] = field(default_factory=list)
    empty_links: int = 0
    toc_entries: int = 0
    ncx_entries: int = 0
    pagelist_labels: list[str] = field(default_factory=list)
    pagelist_issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.broken_links and not self.pagelist_issues and self.empty_links == 0


def _roman_val(s: str) -> int:
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total, prev = 0, 0
    for ch in reversed(s.lower()):
        v = vals[ch]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def _check_href(ep: LoadedEpub, base_href: str, href: str) -> str | None:
    """Returns an error string or None."""
    if href.startswith(("http:", "https:", "mailto:")):
        return None
    if not href:
        return f"{base_href}: empty href"
    if "#" in href:
        target, frag = href.split("#", 1)
    else:
        target, frag = href, None
    target = target or base_href
    doc = ep.doc(target)
    if doc is None:
        return f"{base_href}: target file missing: {href}"
    if frag and frag not in doc.ids():
        return f"{base_href}: missing fragment: {href}"
    return None


def check_nav(ep: LoadedEpub, expected_pages: int | None = None) -> NavResult:
    res = NavResult()

    # all links in all spine docs + nav
    nav = ep.nav_doc()
    docs = ep.spine_docs() + ([nav] if nav is not None else [])
    seen = set()
    for doc in docs:
        if doc.href in seen:
            continue
        seen.add(doc.href)
        for a in doc.root.iter(f"{_XHTML}a"):
            href = a.get("href")
            if href is None or href == "":
                res.empty_links += 1
                continue
            err = _check_href(ep, doc.href, href)
            if err:
                res.broken_links.append(err)

    # nav toc + page-list
    if nav is not None:
        for navel in nav.root.iter(f"{_XHTML}nav"):
            typ = navel.get(f"{_EPUB}type") or ""
            anchors = navel.findall(f".//{_XHTML}a")
            if typ == "toc":
                res.toc_entries = len(anchors)
            elif typ == "page-list":
                res.pagelist_labels = [(a.text or "").strip() for a in anchors]

    # ncx
    try:
        ncx_href = next(
            it["href"] for it in ep.manifest.values()
            if it["media_type"] == "application/x-dtbncx+xml"
        )
        ncx = etree.fromstring(ep.read(ncx_href))
        res.ncx_entries = len(ncx.findall(f".//{_NCX}navPoint"))
    except (StopIteration, KeyError):
        pass

    # page-list checks: monotone roman block then monotone arabic, no dups
    labels = res.pagelist_labels
    if labels:
        if len(set(labels)) != len(labels):
            dups = sorted({l for l in labels if labels.count(l) > 1})
            res.pagelist_issues.append(f"duplicate page labels: {dups}")
        prev_kind, prev_val = None, 0
        for l in labels:
            kind = "arabic" if l.isdigit() else ("roman" if _ROMAN.match(l) else "other")
            val = int(l) if kind == "arabic" else (_roman_val(l) if kind == "roman" else 0)
            if prev_kind == "arabic" and kind == "roman":
                res.pagelist_issues.append(f"roman label {l} after arabic block")
            elif kind == prev_kind and val <= prev_val:
                res.pagelist_issues.append(f"label {l} not increasing")
            prev_kind, prev_val = kind, val
        if expected_pages is not None and len(labels) != expected_pages:
            res.pagelist_issues.append(
                f"page-list has {len(labels)} entries, book has {expected_pages} pages"
            )
    if res.toc_entries and res.ncx_entries and res.toc_entries != res.ncx_entries:
        res.pagelist_issues.append(
            f"nav toc ({res.toc_entries}) and NCX ({res.ncx_entries}) entry counts differ"
        )
    return res
