"""Structured build-warning queue shared by build and QA (gate 22).

Warnings carry stable codes and page scopes. Content-risk codes gate QA
until a config judgment demonstrably covers them (auto_resolve) or an
explicit ``adjudications:`` entry records the decision with render
evidence; advisory codes never gate. Both build/warnings.md and QA's gate
22 derive through THIS module — zero divergence by construction. Page
lists come from doc/flow/cfg FIELDS, never from truncated display strings;
the three extract strings with no field are classified by anchored
regexes over our own emission formats (pinned by tests). A stale
adjudication — matching nothing open — is a config bug, mirroring the
flow.overrides doctrine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .core.model import Paragraph, TextRun
from .core.nav import is_numeric_nav_title

CONTENT_RISK = "content-risk"
ADVISORY = "advisory"

# code -> severity. content-risk = possible content loss, unsupported
# layout, or unreviewed risky pages; advisory = nothing at risk.
CODES: dict[str, str] = {
    "image-only-page": CONTENT_RISK,
    "engine-agreement-low": CONTENT_RISK,
    "page-rotated": CONTENT_RISK,
    "rtl-live-text": CONTENT_RISK,
    "embedded-image-uncovered": CONTENT_RISK,
    "top-band-kept": CONTENT_RISK,
    "toc-line-unparsed": CONTENT_RISK,
    "note-marker-missing": CONTENT_RISK,
    "pua-unmapped": CONTENT_RISK,
    "columns-gutter-missing": CONTENT_RISK,
    "unmapped-pstyles": CONTENT_RISK,
    "fffd-unrepaired": CONTENT_RISK,
    "verse-suspect": CONTENT_RISK,  # verse-shaped block outside/unmatched by
    #                                 blocks.verse — structure-loss risk
    "cover-missing": CONTENT_RISK,
    "flow-uncoded": CONTENT_RISK,  # fail-safe for future uncoded _Warns
    "list-marker-gap": ADVISORY,  # decimal list numbering not increasing —
    #                               a restart (fine) or a misread marker
    "uri-links": ADVISORY,
    "outline-broken-target": ADVISORY,
    "link-unresolvable": ADVISORY,
    "contents-unlinked": ADVISORY,
    "imprint-note-unlinked": ADVISORY,  # an imprint transform (e.g. World
    #   Wisdom editor's notes) could not resolve a page/footnote cross-ref to
    #   an anchor; the note text ships intact, just without the hyperlink
    "index-locator-unlinked": ADVISORY,  # an index page-number locator had no
    #   matching page anchor (out-of-range, roman front-matter, or an "n."
    #   note suffix); the number ships as plain text, just not hyperlinked
    "nav-numeric-bloat": ADVISORY,  # many bare-number headings ('1.', '19.*')
    #   would list in the nav/ncx though a printed Contents omits them — the
    #   judgment prompt gate 7 (subset-only) never raised; auto-resolves once
    #   toc.drop_numeric_nav_entries records the decision
}


@dataclass(slots=True)
class AdjWarning:
    code: str
    severity: str
    msg: str
    pages: list[int] = field(default_factory=list)
    line: int = -1
    snippet: str = ""          # ready-to-paste flow override, if any
    resolved_by: str = ""      # auto-resolve reason; "" = not auto-resolved
    adjudicated_by: str = ""   # note of the matching adjudications entry

    @property
    def open(self) -> bool:
        return not self.resolved_by and not self.adjudicated_by


AGREEMENT_BAR = 90.0

# Arabic Presentation Forms-B ends at FEFC: U+FEFF is the BOM/ZWNBSP, a
# prepress artifact, not RTL text (HU shipped two as empty title-page
# paragraphs and the old census misread them as live RTL)
_RTL_RE = re.compile("[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefc]")
# anchored on our own emission formats (extract/mupdf.py) — tests pin them
_ROTATED_RE = re.compile(r"^page (\d+) is rotated ")
_OUTLINE_RE = re.compile(r"^outline entry .* has external/broken target")
_UNRESOLV_RE = re.compile(r"^page (\d+): unresolvable link annotation")


def rtl_census(flow) -> tuple[int, int]:
    """(expected, unexpected) RTL chars in flow paragraphs. Runs the
    substitution deliberately tagged (fmt.lang set at the flow stage, e.g.
    the honorific ligature as lang=ar) are expected; RTL in untagged runs
    is live foreign text the pipeline cannot lay out yet."""
    expected = unexpected = 0
    for b in flow.blocks:
        if not isinstance(b, Paragraph):
            continue
        for it in b.items:
            if isinstance(it, TextRun):
                n = len(_RTL_RE.findall(it.text))
                if not n:
                    continue
                if it.fmt.lang and it.fmt.lang not in ("zh", "ja", "ko"):
                    expected += n
                else:
                    unexpected += n
    return expected, unexpected


def uncovered_image_pages(doc, cfg) -> list[int]:
    """Pages carrying embedded images that no cover/figure_pages judgment
    covers (the figures stage's scan, shared so QA re-derives identically)."""
    fig_pages = {p for fp in cfg.figure_pages for p in fp.pages}
    covered = fig_pages | set(cfg.pages_cover)
    return [p.number for p in doc.pages
            if p.n_images > 0 and p.number not in covered]


def derive_warnings(doc, res, flow, cfg) -> list[AdjWarning]:
    """Re-derive the full queue from (doc, flow-result, flow, cfg).
    ``res``/``flow`` may be None before the flow stage ran."""
    out: list[AdjWarning] = []

    for p in doc.pages:
        if p.image_only:
            out.append(AdjWarning(
                "image-only-page", CONTENT_RISK,
                "no usable text layer — OCR out of scope; ship as figure "
                "page only if content is verifiable from renders",
                [p.number]))
        if p.engine_agreement is not None and p.engine_agreement < AGREEMENT_BAR:
            out.append(AdjWarning(
                "engine-agreement-low", CONTENT_RISK,
                "engine agreement below 90 — review the page against its "
                "render before trusting its text", [p.number]))

    for w in getattr(doc, "warnings", []):
        m = _ROTATED_RE.match(w)
        if m:
            out.append(AdjWarning("page-rotated", CONTENT_RISK, w,
                                  [int(m.group(1))]))
            continue
        if _OUTLINE_RE.match(w):
            out.append(AdjWarning("outline-broken-target", ADVISORY, w))
            continue
        m = _UNRESOLV_RE.match(w)
        if m:
            out.append(AdjWarning("link-unresolvable", ADVISORY, w,
                                  [int(m.group(1))]))
        # image-only / agreement / URI aggregates re-derive from fields

    if getattr(doc, "uri_link_count", 0):
        out.append(AdjWarning(
            "uri-links", ADVISORY,
            f"{doc.uri_link_count} external URI link annotation(s) — "
            "not modeled (internal GoTo links only)"))

    if res is not None:
        for w in res.warns:
            code = w.code or "flow-uncoded"
            out.append(AdjWarning(code, CODES.get(code, CONTENT_RISK), w.msg,
                                  [w.page] if w.page else [], w.line,
                                  w.snippet))

    if flow is not None:
        _, n_rtl = rtl_census(flow)
        if n_rtl:
            out.append(AdjWarning(
                "rtl-live-text", CONTENT_RISK,
                f"{n_rtl} right-to-left script characters found as live "
                "text: RTL layout is NOT implemented — escalate before "
                "shipping"))
        unmapped = sorted(s for s in flow.style_usage
                          if s not in cfg.pstyle_map
                          and s not in ("__toc__", "__note__"))
        if unmapped:
            out.append(AdjWarning(
                "unmapped-pstyles", CONTENT_RISK,
                f"pstyles not in styles.pstyle_map (role "
                f"'{cfg.unmapped_role}' assumed): " + ", ".join(unmapped)))
        # numeric-only headings ('1.', '19.*') that would flood the nav/ncx —
        # the judgment prompt the nav lacked (gate 7 only checks subset, never
        # bloat). Book-level, so page-less; auto-resolves once the flag records
        # the decision. Count the flow headings that WOULD become nav entries.
        n_numeric_heads = sum(
            1 for b in flow.blocks
            if isinstance(b, Paragraph) and (b.role or "") in ("h1", "h2", "h3")
            and is_numeric_nav_title(b.text()))
        if n_numeric_heads >= 10:
            out.append(AdjWarning(
                "nav-numeric-bloat", ADVISORY,
                f"{n_numeric_heads} numeric-only headings (bare passage/appendix "
                "numbers) would list in the nav/ncx though a printed Contents "
                "omits them; set toc.drop_numeric_nav_entries: true to drop them "
                "from the TOC (they stay in the body)"))

    for pno in uncovered_image_pages(doc, cfg):
        out.append(AdjWarning(
            "embedded-image-uncovered", CONTENT_RISK,
            "embedded image(s) not covered by cover/figure_pages — review "
            "the render; decide figure_pages/decorative or accept as "
            "text-only", [pno]))

    if cfg.cover and not cfg.cover_render and not cfg.cover_synthesize \
            and not cfg.resolve_workspace(cfg.cover).exists():
        out.append(AdjWarning(
            "cover-missing", CONTENT_RISK,
            f"cover file missing: {cfg.cover} and no render/synthesize "
            "fallback configured"))
    return out


def auto_resolve(warnings: list[AdjWarning], cfg) -> int:
    """Mark warnings a config judgment demonstrably covers. Returns count."""
    fig_pages = {p for fp in cfg.figure_pages for p in fp.pages}
    region_pages = {fr.page for fr in cfg.figure_regions}
    col_pages = {p for cs in cfg.flow_columns for p in cs.pages}
    cover_excl = set(cfg.pages_cover) | set(cfg.pages_exclude)
    n = 0
    for w in warnings:
        if w.code == "nav-numeric-bloat":
            # book-level (page-less): the config flag IS the recorded judgment
            if cfg.toc_drop_numeric_nav_entries:
                w.resolved_by = "toc.drop_numeric_nav_entries set"
                n += 1
            continue
        page = w.pages[0] if w.pages else None
        if page is None:
            continue
        if w.code == "image-only-page" and page in cover_excl | fig_pages:
            w.resolved_by = ("cover/excluded page" if page in cover_excl
                             else "ships as a figure page")
        elif w.code == "engine-agreement-low" and page in (
                cover_excl | fig_pages | col_pages
                | set(cfg.toc_printed_pages)):
            w.resolved_by = ("config handles the page "
                             "(cover/exclude/figure/columns/printed-TOC)")
        elif w.code == "embedded-image-uncovered" and page in (
                set(cfg.pages_exclude) | region_pages):
            w.resolved_by = "excluded page / figure_regions covers it"
        elif w.code == "top-band-kept" and any(
                ov.page == page and ov.line == w.line
                for ov in cfg.flow_overrides):
            w.resolved_by = "flow.overrides addresses this exact line"
        if w.resolved_by:
            n += 1
    return n


def apply_adjudications(warnings: list[AdjWarning], cfg) \
        -> tuple[list[AdjWarning], list[AdjWarning], list[str]]:
    """Match cfg.adjudications against open warnings. Page-scoped entries
    match per page — every listed page must cover something open, else the
    page is stale. Returns (open, adjudicated, stale_descriptions)."""
    stale: list[str] = []
    for ad in cfg.adjudications:
        if ad.pages:
            missed = []
            for pg in ad.pages:
                hit = False
                for w in warnings:
                    if w.code == ad.warning and w.open and w.pages \
                            and w.pages[0] == pg:
                        w.adjudicated_by = ad.note
                        hit = True
                if not hit:
                    missed.append(pg)
            if missed:
                stale.append(f"adjudications: {ad.warning} pages {missed} "
                             "matched no open warning — prune")
        else:
            hit = False
            for w in warnings:
                if w.code == ad.warning and w.open:
                    w.adjudicated_by = ad.note
                    hit = True
            if not hit:
                stale.append(f"adjudications: {ad.warning} matched no open "
                             "warning — prune")
    open_ = [w for w in warnings if w.open]
    adjudicated = [w for w in warnings if w.adjudicated_by]
    return open_, adjudicated, stale


def adjudication_snippet(code: str, pages: list[int]) -> str:
    ptxt = f", pages: [{', '.join(map(str, pages))}]" if pages else ""
    return ("- {warning: " + code + ptxt
            + ', note: "<verified on render: why this is acceptable>"}')


def render_queue(warnings: list[AdjWarning], stale: list[str]) -> list[str]:
    """warnings.md body: grouped by code, page lists compacted per status."""
    L: list[str] = []
    order = sorted({w.code for w in warnings},
                   key=lambda c: (CODES.get(c, CONTENT_RISK) != CONTENT_RISK, c))
    for code in order:
        ws = [w for w in warnings if w.code == code]
        n_open = sum(1 for w in ws if w.open)
        L.append(f"## {code} [{CODES.get(code, CONTENT_RISK)}] — "
                 f"{n_open} open / {len(ws)} total")
        groups: dict[tuple[str, str], list[AdjWarning]] = {}
        for w in ws:
            status = ("OPEN" if w.open else
                      f"auto-resolved: {w.resolved_by}" if w.resolved_by
                      else f"adjudicated: {w.adjudicated_by}")
            groups.setdefault((status, w.msg), []).append(w)
        for (status, msg), members in groups.items():
            pages = sorted({p for w in members for p in w.pages})
            ptxt = (f" pages {pages}" if pages else "")
            L.append(f"- [{status}]{ptxt} {msg}")
            for w in members:
                if w.open and w.snippet:
                    L.append(f"  - override: `{w.snippet}`")
            if status == "OPEN" and CODES.get(code, CONTENT_RISK) == CONTENT_RISK:
                L.append(f"  - adjudicate: `{adjudication_snippet(code, pages)}`")
    for s in stale:
        L.append(f"- STALE: {s}")
    return L
