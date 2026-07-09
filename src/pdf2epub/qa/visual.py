"""Visual QA orchestrator (gate 18, `qa --visual`).

Produces the evidence a grading agent needs: side-by-side contact sheets
(trim-cropped print page LEFT, the EPUB's anchor-sliced rendering RIGHT),
PUA glyph crop pairs, figure dHash verdicts, and a manifest (json + md)
saying exactly what to verify per sampled page. Chrome absent -> PDF panels
+ manifest still ship; the gate line says the EPUB side was skipped.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..core.model import InlinePageBreak, PageAnchor, Paragraph
from ..thumbs import render_page
from . import visual_pixels, visual_sample
from .cdp import Chrome, ChromeUnavailable, file_url
from .typography import apply_qa_roles

_X = "{http://www.w3.org/1999/xhtml}"
_E = "{http://www.idpf.org/2007/ops}"
VIEWPORT = (600, 800)
CAPTURE_SCALE = 2.0
PDF_DPI = 150
MAX_SEG_CSS_PX = 3000.0
MIN_SLICE_CSS_PX = 8.0


@dataclass(slots=True)
class VisualResult:
    gate_lines: list[str]
    manifest_json: Path | None = None
    manifest_md: Path | None = None


@dataclass(slots=True)
class SlicePlan:
    page: int
    label: str
    approximate: bool
    k: int                        # global anchor index
    href: str                     # spine file of the start anchor
    next_href: str | None         # file of the NEXT anchor (None = last)
    same_file: bool


def plan_slices(anchors: list, pagebreaks: list[tuple[str, str]],
                in_flow: list[int], pages: list[int]) -> dict[int, SlicePlan | None]:
    """Pair the k-th flow PageAnchor with the k-th spine pagebreak (ordinal
    doctrine — labels collide). Returns None for pages with no anchor
    (excluded/cover) — PDF panel only."""
    plans: dict[int, SlicePlan | None] = {}
    count_ok = len(pagebreaks) == len(anchors) == len(in_flow)
    for page in pages:
        if page not in in_flow or not count_ok:
            plans[page] = None
            continue
        k = in_flow.index(page)
        a = anchors[k]
        href = pagebreaks[k][0]
        nxt = pagebreaks[k + 1][0] if k + 1 < len(pagebreaks) else None
        plans[page] = SlicePlan(page=page, label=a.label,
                                approximate=a.approximate, k=k, href=href,
                                next_href=nxt, same_file=(nxt == href))
    return plans


def _flow_anchors(flow) -> list[PageAnchor]:
    """All page anchors in document order: block PageAnchors plus the exact
    InlinePageBreaks sitting inside continuation paragraphs (as PageAnchor
    values, approximate=False — they are exact by construction)."""
    out: list[PageAnchor] = []
    for b in flow.blocks:
        if isinstance(b, PageAnchor):
            out.append(b)
        elif isinstance(b, Paragraph):
            out.extend(PageAnchor(it.ordinal, it.label, False)
                       for it in b.items if isinstance(it, InlinePageBreak))
    return out


def _spine_pagebreaks(body_docs) -> list[tuple[str, str]]:
    out = []
    for doc in body_docs:
        body = doc.root.find(f"{_X}body")
        if body is None:
            continue
        for el in body.iter():
            if isinstance(el.tag, str) and \
                    (el.get(f"{_E}type") or "") == "pagebreak":
                out.append((doc.href, el.get("id") or ""))
    return out


def _capture_slices(chrome: Chrome, unzip_root: Path, opf_dir: str,
                    plans: dict[int, SlicePlan | None],
                    pagebreaks: list[tuple[str, str]],
                    out_dir: Path) -> dict[int, Path]:
    """One navigation per spine file; per-file anchor offsets via JS; clipped
    screenshots per sampled page."""
    by_file: dict[str, list[SlicePlan]] = {}
    for plan in plans.values():
        if plan is not None:
            by_file.setdefault(plan.href, []).append(plan)
            if not plan.same_file and plan.next_href:
                by_file.setdefault(plan.next_href, [])

    geo: dict[str, dict] = {}   # href -> {"h": px, "pb": {id: y}}
    for href in by_file:
        chrome.open(file_url(str(unzip_root / opf_dir / href)))
        got = chrome.eval(
            "JSON.stringify({h: document.documentElement.scrollHeight,"
            " pb: Object.fromEntries([...document.querySelectorAll("
            "'div.pagebreak, span.pagebreak')].map(d => [d.id,"
            " d.getBoundingClientRect().top + window.scrollY]))})")
        geo[href] = json.loads(got)

        for plan in by_file[href]:
            pid = pagebreaks[plan.k][1]
            y0 = geo[href]["pb"].get(pid)
            if y0 is None:
                continue
            if plan.same_file:
                nid = pagebreaks[plan.k + 1][1]
                y1 = geo[href]["pb"].get(nid, geo[href]["h"])
            else:
                y1 = geo[href]["h"]
            h = y1 - y0
            if h < MIN_SLICE_CSS_PX:
                # blank verso / continuation-only page: show a little context
                # so the grader can confirm the source page is really empty
                h = min(200.0, geo[href]["h"] - y0)
            h = min(h, MAX_SEG_CSS_PX)
            png = chrome.screenshot(0, y0, VIEWPORT[0], max(h, 8.0),
                                    scale=CAPTURE_SCALE)
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"p{plan.page:04d}.png").write_bytes(png)

    # cross-file continuation heads (second segment, vstacked by caller)
    for plan in plans.values():
        if plan is None or plan.same_file or not plan.next_href:
            continue
        nhref = plan.next_href
        if nhref not in geo:
            chrome.open(file_url(str(unzip_root / opf_dir / nhref)))
            got = chrome.eval(
                "JSON.stringify({h: document.documentElement.scrollHeight,"
                " pb: Object.fromEntries([...document.querySelectorAll("
                "'div.pagebreak, span.pagebreak')].map(d => [d.id,"
                " d.getBoundingClientRect().top + window.scrollY]))})")
            geo[nhref] = json.loads(got)
        else:
            chrome.open(file_url(str(unzip_root / opf_dir / nhref)))
        first_pb = min(geo[nhref]["pb"].values(), default=geo[nhref]["h"])
        h = min(max(first_pb, 8.0), MAX_SEG_CSS_PX)
        png = chrome.screenshot(0, 0, VIEWPORT[0], h, scale=CAPTURE_SCALE)
        head = out_dir / f"p{plan.page:04d}-head.png"
        head.write_bytes(png)
        tail = out_dir / f"p{plan.page:04d}.png"
        if tail.exists():
            from PIL import Image

            a = Image.open(tail).convert("RGB")
            b = Image.open(head).convert("RGB")
            stacked = Image.new("RGB", (max(a.width, b.width),
                                        a.height + 8 + b.height), (150, 150, 150))
            stacked.paste(a, (0, 0))
            stacked.paste(b, (0, a.height + 8))
            stacked.save(tail)
        head.unlink(missing_ok=True)
    return {p.page: out_dir / f"p{p.page:04d}.png"
            for p in plans.values() if p is not None
            and (out_dir / f"p{p.page:04d}.png").exists()}


def _manifest_md(pages_meta: list[dict], glyphs: list[dict],
                 figures: list[dict], out: Path) -> None:
    lines = ["# Visual QA — grading sheet", "",
             "Compare each sheet's LEFT (print) and RIGHT (EPUB slice) panel; "
             "content may start/end mid-paragraph (reflow) — grade typography "
             "and presence, not pagination.", ""]
    for m in pages_meta:
        lines.append(f"## p.{m['pdf_page']} (label {m['label']}) — "
                     f"sheets/p{m['pdf_page']:04d}.png")
        lines.append(f"why sampled: {'; '.join(m['reasons'])}")
        c = m.get("checks") or {}
        for style, n in c.get("pstyles", {}).items():
            if style == "__toc__":
                lines.append(f"- [ ] {n} rebuilt-Contents entries: "
                             "hyperlinked, indent per level")
            else:
                lines.append(f"- [ ] {n} para(s) of {style}: size/alignment "
                             "match print")
        for hd in c.get("headings", []):
            lines.append(f"- [ ] {hd['role']} \"{hd['text']}\": hierarchy and "
                         "centering match print")
        if c.get("dropcap"):
            lines.append("- [ ] drop cap renders floated, no stray letter")
        for hexname, n in c.get("pua", {}).items():
            lines.append(f"- [ ] {n}x {hexname} substitution reads correctly "
                         "in context")
        if c.get("noterefs"):
            lines.append(f"- [ ] {c['noterefs']} noteref superscript(s) "
                         "present and linked")
        if c.get("figures"):
            lines.append(f"- [ ] {c['figures']} figure(s) present, "
                         "right image")
        if c.get("blockquotes"):
            lines.append(f"- [ ] {c['blockquotes']} block quote(s) inset")
        if c.get("lang_spans"):
            lines.append(f"- [ ] lang spans render: {', '.join(c['lang_spans'])}")
        for note in m.get("notes", []):
            lines.append(f"- NOTE: {note}")
        lines.append("")
    if glyphs:
        lines.append("## Glyph pairs (glyphs/)")
        for g in glyphs:
            lines.append(f"- [ ] {g['hex']} -> {g['substituted'] or 'DROP'}"
                         + (f" [{g['lang']}]" if g["lang"] else "")
                         + (f" — {g['crop']}" if g["crop"] else " (no crop)")
                         + (f" ({g['note']})" if g.get("note") else ""))
        lines.append("")
    if figures:
        lines.append("## Figures (dHash)")
        for f in figures:
            lines.append(f"- {f['image_key']} p.{f['pdf_page']}: "
                         f"{f['verdict']} (distance {f['distance']})"
                         + (f" — review {f['pair']}" if f.get("pair") else ""))
        lines.append("")
    out.write_text("\n".join(lines) + "\n")


def run_visual(epub: Path, cfg, doc, flow, res, labels,
               disputed_pages, undecidable_note_pages,
               out_dir: Path, cap: int = 14, say=print) -> VisualResult:
    apply_qa_roles(flow, res, cfg)   # idempotent (runner ran it for gates 13-17)
    ev = visual_sample.build_evidence(doc, flow, res, cfg, disputed_pages,
                                      undecidable_note_pages)
    sample = visual_sample.sample_pages(ev, cap)
    pages = [s.page for s in sample]
    checks = visual_sample.checks_by_page(doc, flow, res, cfg, labels, pages)
    in_flow = ev.in_flow

    if out_dir.exists():
        shutil.rmtree(out_dir)
    for sub in ("pdf", "epub", "sheets", "glyphs", "figures"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    pdf = cfg.pdf_path()
    for p in pages:
        render_page(pdf, p, out_dir / "pdf" / f"p{p:04d}.png", dpi=PDF_DPI,
                    clip_trim=True)

    # ---- EPUB side: unzip + slice via Chrome
    from ..core.qa_epubload import load_epub

    ep = load_epub(epub)
    body_docs = [d for d in ep.spine_docs()
                 if "notes" not in d.href and "cover" not in d.href]
    anchors = _flow_anchors(flow)
    pagebreaks = _spine_pagebreaks(body_docs)
    plans = plan_slices(anchors, pagebreaks, in_flow, pages)
    count_ok = len(pagebreaks) == len(anchors) == len(in_flow)

    epub_pngs: dict[int, Path] = {}
    chrome_err = ""
    unzip_root = Path(tempfile.mkdtemp(prefix="pdf2epub-visual-"))
    try:
        with zipfile.ZipFile(epub) as z:
            z.extractall(unzip_root)
        opf_dir = str(ep.opf_dir)
        try:
            with Chrome(viewport=VIEWPORT) as chrome:
                epub_pngs = _capture_slices(chrome, unzip_root, opf_dir,
                                            plans, pagebreaks,
                                            out_dir / "epub")
        except ChromeUnavailable as e:
            chrome_err = str(e)
    finally:
        shutil.rmtree(unzip_root, ignore_errors=True)

    # ---- sheets + tier-3 pixels
    pages_meta: list[dict] = []
    for s in sample:
        plan = plans.get(s.page)
        notes: list[str] = []
        if plan is None:
            notes.append("no anchor for this page: excluded/cover — verify "
                         "the exclusion is right (book.yaml pages)"
                         if s.page not in in_flow else
                         "anchor pairing failed — EPUB slice unavailable")
        else:
            if plan.approximate:
                notes.append("anchor deferred (page contributed no flowable "
                             "text) — compare loosely")
            if not plan.same_file and plan.next_href:
                notes.append(f"page continues into {plan.next_href}")
        visual_pixels.compose_sheet(out_dir / "pdf" / f"p{s.page:04d}.png",
                                    epub_pngs.get(s.page),
                                    out_dir / "sheets" / f"p{s.page:04d}.png")
        pages_meta.append({
            "pdf_page": s.page, "label": labels.get(s.page, str(s.page)),
            "anchor_id": (f"pg-{plan.label}" if plan else None),
            "approximate": bool(plan and plan.approximate),
            "reasons": s.reasons, "excluded": s.page not in in_flow,
            "spine_files": ([plan.href] + ([plan.next_href]
                            if plan and not plan.same_file and plan.next_href
                            else []) if plan else []),
            "pdf_png": f"pdf/p{s.page:04d}.png",
            "epub_png": (f"epub/p{s.page:04d}.png"
                         if s.page in epub_pngs else None),
            "sheet": f"sheets/p{s.page:04d}.png",
            "checks": checks.get(s.page), "notes": notes,
        })

    ep_fonts = [(it["href"], ep.read(it["href"]))
                for it in ep.manifest.values()
                if (it.get("media_type") or "").startswith(("font/",
                    "application/font", "application/vnd.ms-opentype"))]
    glyphs = visual_pixels.pua_crop_pairs(doc, cfg, pdf, ep_fonts, in_flow,
                                          out_dir / "glyphs")
    figures = visual_pixels.figure_phashes(flow, cfg, ep, pdf,
                                           out_dir / "figures")

    manifest = {
        "schema": 1, "epub": epub.name, "pdf_sha256": doc.sha256,
        "params": {"viewport_css_px": VIEWPORT[0],
                   "capture_scale": CAPTURE_SCALE, "pdf_dpi": PDF_DPI,
                   "sample_cap": cap},
        "browser_available": not chrome_err,
        "pages": pages_meta, "glyphs": glyphs, "figures": figures,
    }
    mjson = out_dir / "manifest.json"
    mjson.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    mmd = out_dir / "manifest.md"
    _manifest_md(pages_meta, glyphs, figures, mmd)

    n_review = sum(1 for f in figures if f["verdict"] != "ok")
    line = (f"{len(pages)} pages sampled -> {out_dir.name}/manifest.md "
            f"(epub slices {len(epub_pngs)}/{len(pages)}, "
            f"glyph pairs {sum(1 for g in glyphs if g['crop'])}, "
            f"figures {len(figures) - n_review} ok/{n_review} review) — "
            "agent must Read manifest.md and grade every sheet")
    lines = [line]
    if chrome_err:
        lines.append(f"chrome unavailable: {chrome_err} — PDF renders + "
                     "manifest still written")
    if not count_ok:
        lines.append(f"anchor pairing mismatch: {len(pagebreaks)} spine "
                     f"pagebreaks vs {len(anchors)} flow anchors vs "
                     f"{len(in_flow)} in-flow pages — EPUB slices skipped")
    return VisualResult(gate_lines=lines, manifest_json=mjson, manifest_md=mmd)
