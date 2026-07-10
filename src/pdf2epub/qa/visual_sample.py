"""Visual-QA page sampling: deterministic, stratified, phenomenon-first.

Errors in this pipeline are systematic per style cluster / phenomenon, not
random per page, so the sample covers PHENOMENA: every pstyle at least once
(rarest first — that's where misassignment hides), every first-seen special
(drop caps, PUA glyphs, figures, notes, printed TOC), pages other gates
implicated, plus a few seeded-random pages for unknown-unknowns. Seeded from
the PDF sha256: same book -> byte-identical sample set and manifest.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field

from ..core.model import Figure, NoteRef, PageAnchor, Paragraph, TextRun

_PUA_RE = re.compile("[\\ue000-\\uf8ff]")


@dataclass(slots=True)
class SampleEvidence:
    sha256: str
    n_pages: int
    in_flow: list[int]
    page_styles: dict[int, list[str]] = field(default_factory=dict)
    style_usage: dict[str, int] = field(default_factory=dict)
    dropcap_pages: list[int] = field(default_factory=list)
    verse_pages: list[int] = field(default_factory=list)
    pua_first_page: dict[str, int] = field(default_factory=dict)
    figure_pages: list[int] = field(default_factory=list)
    note_pages: list[int] = field(default_factory=list)
    toc_printed_pages: list[int] = field(default_factory=list)
    first_h1_page: int | None = None
    first_h2_page: int | None = None
    disputed_pages: list[int] = field(default_factory=list)
    low_agreement: list[tuple[float, int]] = field(default_factory=list)
    undecidable_note_pages: list[int] = field(default_factory=list)
    excluded_pages: list[int] = field(default_factory=list)


@dataclass(slots=True)
class SampledPage:
    page: int
    reasons: list[str]


def build_evidence(doc, flow, res, cfg, disputed_pages,
                   undecidable_note_pages) -> SampleEvidence:
    ev = SampleEvidence(sha256=doc.sha256, n_pages=doc.n_pages,
                        in_flow=list(cfg.in_flow_pages(doc.n_pages)))
    ev.style_usage = {s: n for s, n in sorted(flow.style_usage.items())
                      if not s.startswith("__")}
    for b in flow.blocks:
        if isinstance(b, Paragraph) and not b.style.startswith("__"):
            pg = int(b.src.story_id[1:])
            styles = ev.page_styles.setdefault(pg, [])
            if b.style not in styles:
                styles.append(b.style)
            if b.role == "h1" and ev.first_h1_page is None:
                ev.first_h1_page = pg
            if b.role == "h2" and ev.first_h2_page is None:
                ev.first_h2_page = pg
            if b.block_class == "verse":
                ev.verse_pages.append(pg)
        elif isinstance(b, Figure) and b.pdf_page:
            ev.figure_pages.append(b.pdf_page)
    for pg in ev.page_styles.values():
        pg.sort()
    ev.dropcap_pages = sorted({int(sid[1:]) for sid, _ in res.dropcap_srcs})
    ev.note_pages = sorted({int(nid[1:5]) for nid in flow.notes})
    ev.toc_printed_pages = sorted(cfg.toc_printed_pages)
    in_flow_set = set(ev.in_flow)
    for p in doc.pages:
        if p.number not in in_flow_set:
            continue
        for ln in p.lines:
            for r in ln.runs:
                for ch in _PUA_RE.findall(r.text):
                    ev.pua_first_page.setdefault(ch, p.number)
        if p.engine_agreement is not None and p.engine_agreement < 90:
            ev.low_agreement.append((p.engine_agreement, p.number))
    ev.low_agreement.sort()
    ev.disputed_pages = sorted(set(disputed_pages))
    ev.undecidable_note_pages = sorted(set(undecidable_note_pages))
    ev.excluded_pages = sorted(set(cfg.pages_exclude) | set(cfg.pages_cover))
    return ev


def sample_pages(ev: SampleEvidence, cap: int = 14) -> list[SampledPage]:
    cap = max(6, min(24, cap))
    picked: dict[int, SampledPage] = {}
    order: list[int] = []          # insertion order for truncation
    stratum_b: list[int] = []

    def take(page: int | None, reason: str) -> None:
        if page is None:
            return
        got = picked.get(page)
        if got is None:
            picked[page] = SampledPage(page=page, reasons=[reason])
            order.append(page)
        elif reason not in got.reasons:
            got.reasons.append(reason)

    # ---- stratum A: phenomena firsts (never truncated)
    take(ev.first_h1_page, "first h1")
    take(ev.first_h2_page, "first h2")
    take(min(ev.dropcap_pages, default=None), "first drop cap")
    take(min(ev.verse_pages, default=None), "first verse group")
    for ch in sorted(ev.pua_first_page):
        take(ev.pua_first_page[ch], f"pua U+{ord(ch):04X} first page")
    take(min(ev.figure_pages, default=None), "first figure page")
    take(min(ev.note_pages, default=None), "first footnote page")
    take(min(ev.toc_printed_pages, default=None), "printed TOC page")
    for pg in ev.disputed_pages[:2]:
        take(pg, "engine-disputed page")
    for score, pg in ev.low_agreement[:2]:
        take(pg, f"engine agreement {score:.0f}%")
    for pg in ev.undecidable_note_pages[:2]:
        take(pg, "note on disputed page")

    # ---- stratum B: pstyle set cover (greedy, rarest-first tiebreak)
    covered = {s for pg in picked for s in ev.page_styles.get(pg, [])}
    uncovered = set(ev.style_usage) - covered
    while uncovered and len(picked) < cap - 3:
        def gain(pg: int) -> tuple[int, int, int]:
            new = uncovered & set(ev.page_styles.get(pg, []))
            rarest = min((ev.style_usage[s] for s in new), default=1 << 30)
            return (len(new), -rarest, -pg)
        best = max((pg for pg in ev.in_flow if pg not in picked),
                   key=gain, default=None)
        if best is None or gain(best)[0] == 0:
            break
        new = sorted(uncovered & set(ev.page_styles.get(best, [])))
        take(best, "pstyle: " + ", ".join(new[:4]))
        stratum_b.append(best)
        uncovered -= set(new)

    # ---- stratum C: seeded random (unknown-unknowns)
    n_random = min(5, max(3, cap - len(picked)))
    pool = sorted(set(ev.in_flow) - set(picked))
    rng = random.Random(int(ev.sha256[:16], 16) if ev.sha256 else 0)
    for pg in sorted(rng.sample(pool, min(n_random, len(pool)))):
        take(pg, "random")

    # ---- truncation: drop stratum-B picks last-picked-first; A and the
    # randoms survive (cap is soft w.r.t. stratum A)
    while len(picked) > cap and stratum_b:
        drop = stratum_b.pop()
        if picked[drop].reasons[0].startswith("pstyle:") and \
                len(picked[drop].reasons) == 1:
            del picked[drop]
            order.remove(drop)
    return [picked[pg] for pg in sorted(picked)]


def checks_by_page(doc, flow, res, cfg, labels,
                   pages: list[int]) -> dict[int, dict]:
    """What the grading agent must verify on each sampled page — derived
    from the flow (roles applied by the caller via apply_qa_roles). PUA
    counts come from the EXTRACT doc: the flow already substituted them."""
    want = set(pages)
    out: dict[int, dict] = {pg: {
        "pstyles": Counter(), "headings": [], "dropcap": False,
        "pua": Counter(), "noterefs": 0, "figures": 0, "blockquotes": 0,
        "lang_spans": set(), "smallcaps_runs": 0,
    } for pg in pages}
    for b in flow.blocks:
        if isinstance(b, PageAnchor):
            continue
        if isinstance(b, Figure):
            if b.pdf_page in want:
                out[b.pdf_page]["figures"] += 1
            continue
        pg = int(b.src.story_id[1:])
        if pg not in want:
            continue
        c = out[pg]
        role = b.role or "p"
        c["pstyles"][b.style] += 1
        if role in ("h1", "h2", "h3"):
            c["headings"].append({"role": role, "text": b.text()[:70]})
        if role == "blockquote":
            c["blockquotes"] += 1
        if (b.src.story_id, b.src.psr_index) in res.dropcap_srcs:
            c["dropcap"] = True
        for it in b.items:
            if isinstance(it, NoteRef):
                c["noterefs"] += 1
            elif isinstance(it, TextRun):
                if it.fmt.lang:
                    c["lang_spans"].add(it.fmt.lang)
                if it.fmt.smallcaps:
                    c["smallcaps_runs"] += 1
    for pg in pages:
        if 1 <= pg <= doc.n_pages:
            for ln in doc.page(pg).lines:
                for r in ln.runs:
                    for ch in _PUA_RE.findall(r.text):
                        out[pg]["pua"][f"U+{ord(ch):04X}"] += 1
    for c in out.values():
        c["pstyles"] = dict(sorted(c["pstyles"].items()))
        c["pua"] = dict(sorted(c["pua"].items()))
        c["lang_spans"] = sorted(c["lang_spans"])
    return out
