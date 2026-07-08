"""QA gate suite: 12 gates, gates 1-10 must pass; 11-12 informational.

Ground truth and expectations are re-derived deterministically from
(source PDF, book.yaml) — the same inputs the build used — via an
INDEPENDENT poppler text path. Writes qa_report.md + qa.json next to the
EPUB and prints 'Overall: PASS' only when every gating check passes."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import load_config
from ..core.qa_epubcheck import run_epubcheck
from ..core.qa_epubload import load_epub
from ..core.qa_imagecheck import check_images
from ..core.qa_navcheck import check_nav
from ..core.qa_ordercheck import check_reading_order
from ..core.qa_refcompare import compare as ref_compare
from ..core.qa_textdiff import coverage
from ..core.textnorm import normalize
from ..extract import extract
from ..flowbuilder import _page_labels, build_flow
from ..pdfmodel import PdfDoc
from . import pdfchecks
from .groundtruth import build_ground_truth

_X = "{http://www.w3.org/1999/xhtml}"
COVERAGE_GATE = 0.99


def run_qa(epub: Path, config: Path, reference: Path | None = None) -> int:
    cfg = load_config(config)
    quiet = lambda m: None  # noqa: E731
    gates: list[tuple[str, bool | None, list[str]]] = []

    # ---- deterministic re-derivation of expectations
    doc: PdfDoc = extract(cfg.pdf_path(), say=quiet, agreement=False)
    res = build_flow(doc, cfg, say=quiet)
    flow = res.flow
    labels = _page_labels(doc, cfg, [])
    in_flow = cfg.in_flow_pages(doc.n_pages)

    # glyph substitutions inserted English readings; the poppler ground truth
    # has (stripped) PUA chars instead — remove readings before excision/probes
    subs = [r.char for r in cfg.pua_map.values() if r.action == "char" and r.char]

    def _unsub(text: str) -> str:
        for s in subs:
            text = text.replace(s, "")
        return text

    note_texts_by_page: dict[int, list[tuple[str, str]]] = {}
    for nid, note in flow.notes.items():
        pno = int(nid[1:5])
        note_texts_by_page.setdefault(pno, []).append(
            (res.note_markers.get(nid, ""),
             _unsub(" ".join(p.text() for p in note.paragraphs))))

    ep = load_epub(epub)
    spine = ep.spine_docs()
    # the EPUB's noteref/backlink anchor text is navigation chrome with
    # renumbered digits — not source text; drop before comparing
    for d in spine:
        for a in list(d.root.iter(f"{_X}a")):
            cls = a.get("class") or ""
            if "noteref" in cls or "backlink" in cls:
                parent = a.getparent()
                prev = a.getprevious()
                tail = a.tail or ""
                if prev is not None:
                    prev.tail = (prev.tail or "") + tail
                else:
                    parent.text = (parent.text or "") + tail
                parent.remove(a)
    notes_docs = [d for d in spine if "notes" in d.href]
    body_docs = [d for d in spine
                 if d not in notes_docs and "cover" not in d.href]
    spine_text = " ".join(d.text() for d in body_docs)
    spine_text_norm = normalize(spine_text)
    # coverage compares 'text minus honorific glyphs' on BOTH sides: the gt
    # strips PUA chars; the candidate must shed their inserted readings
    coverage_candidate = normalize(_unsub(spine_text))
    all_text_norm = normalize(spine_text + " " +
                              " ".join(d.text() for d in notes_docs))

    # ---- gate 1: epubcheck
    ok, msgs = run_epubcheck(epub)
    gates.append(("1 epubcheck", ok, msgs[-1:]))

    # ---- gate 2: text coverage vs independent ground truth
    gt = build_ground_truth(cfg.pdf_path(), cfg, doc, note_texts_by_page,
                            stripped_lines=res.furniture_texts)
    # the rebuilt hyperlinked Contents replaces the printed TOC pages; exclude
    # them like figure pages (itemized), the TOC gates cover that content
    toc_excl = 0
    for pno in cfg.toc_printed_pages:
        toc_excl += len(gt.pages.get(pno, ""))
        gt.pages[pno] = ""
    from .groundtruth import paged_coverage

    cov = paged_coverage(gt, coverage_candidate)
    lines = [f"coverage {cov.coverage*100:.2f}% (gate {COVERAGE_GATE*100:.0f}%); "
             f"note chars stripped {gt.note_chars_removed}, figure-page chars "
             f"excluded {gt.figure_chars_excluded}, printed-TOC chars excluded {toc_excl}"]
    for seg in cov.missing_segments[:12]:
        lines.append(f"MISSING: {seg[:110]}")
    if len(cov.missing_segments) > 12:
        lines.append(f"… and {len(cov.missing_segments)-12} more missing segments")
    gates.append(("2 text coverage", cov.coverage >= COVERAGE_GATE, lines))

    # ---- gate 3: footnotes present on their page. Placement is proven by the
    # probes; gt excision misses are gate-2 bookkeeping (the unexcised text
    # stays in the coverage denominator) — informational here
    fails: list[str] = []
    for nid, note in sorted(flow.notes.items()):
        pno = int(nid[1:5])
        body = normalize(_unsub(" ".join(p.text() for p in note.paragraphs)))
        raw = gt.pages_raw.get(pno, "") + " " + gt.pages_raw.get(pno + 1, "")
        # three probes: dehyphenation/space seams can break any single one
        probes = [body[-60:], body[:40],
                  body[len(body) // 2:len(body) // 2 + 40]]
        if body and not any(p and p in raw for p in probes):
            fails.append(f"{nid}: note text not found on p.{pno}")
    n_note_items = sum(len(list(d.root.iter(f"{_X}li"))) for d in notes_docs)
    lines = [f"{len(flow.notes)} notes; {n_note_items} endnote items in EPUB; "
             f"{len(fails)} placement failures; "
             f"{len(gt.note_strip_failures)} gt-excision misses (info, in coverage)"]
    lines += fails[:8]
    gates.append(("3 footnotes", not fails, lines))

    # ---- gate 4: navigation
    nav = check_nav(ep, expected_pages=len(in_flow))
    gates.append(("4 navigation", nav.ok,
                  [f"toc={nav.toc_entries} ncx={nav.ncx_entries} "
                   f"pagelist={len(nav.pagelist_labels)}"]
                  + nav.broken_links[:5] + nav.pagelist_issues[:5]))

    # ---- gate 5: images + alt
    img = check_images(ep)
    gates.append(("5 images", img.ok,
                  [f"{img.manifest_images} images, {img.referenced} referenced, "
                   f"{img.total_bytes//1024}KB"]
                  + img.unresolved_srcs[:3] + img.orphans[:3]
                  + img.empty_alt_content[:3]))

    # ---- gate 6: reading order (chosen TOC source vs printed pages)
    source_entries = _source_entries(cfg, doc, flow, labels)
    page_order = [labels.get(p, str(p)) for p in in_flow]
    order = check_reading_order(ep, source_entries, page_order)
    gates.append(("6 reading order", order.ok,
                  [f"{order.matched_entries}/{order.checked} TOC entries on their "
                   f"printed page"] + order.violations[:6]
                  + [f"info: {o}" for o in order.orphan_headings[:3]]))

    # ---- gate 7: TOC agreement (source entries present in nav)
    nav_doc = ep.nav_doc()
    nav_entries = pdfchecks.parse_nav_toc(nav_doc.root) if nav_doc else []
    agree = pdfchecks.check_toc_agreement(
        nav_entries, [t for t, _ in source_entries], cfg.nav_depth)
    gates.append(("7 toc agreement", agree.ok,
                  [f"{agree.matched}/{agree.source_total} source entries in nav "
                   f"(nav extra: {agree.nav_extra})"] + agree.missing[:6]))

    # ---- gate 8: furniture leak
    para_texts = [" ".join(p.itertext()) for d in body_docs
                  for p in d.root.iter(f"{_X}p")]
    leaks = pdfchecks.check_furniture_leak(para_texts, gt.furniture_templates)
    gates.append(("8 furniture leak", not leaks, leaks[:6]))

    # ---- gate 9: hyphen residue — measured against the ground truth's own
    # count: an author's dash style ('did not-nor does it still- sit') lives
    # in the source too; only EXCESS over the source is a join artifact
    n_hyph = pdfchecks.hyphen_residue(all_text_norm)
    gt_hyph = pdfchecks.hyphen_residue(" ".join(gt.pages_raw.values()))
    gates.append(("9 hyphen residue", n_hyph <= gt_hyph,
                  [f"'word- word': candidate {n_hyph} vs source {gt_hyph}"]))

    # ---- gate 10: PUA residue
    pua = pdfchecks.pua_residue(all_text_norm)
    gates.append(("10 pua residue", not pua, [", ".join(pua) or "none"]))

    # ---- gate 11 (info): lost spaces
    n_lost = pdfchecks.lost_space_count(all_text_norm)
    gates.append(("11 lost-space scan (info)", None, [f"residual fused patterns: {n_lost}"]))

    # ---- gate 12 (info): reference scorecard
    if reference:
        rows = ref_compare(epub, reference)
        gates.append(("12 reference scorecard (info)", None,
                      [f"{r.metric}: ours={r.ours} ref={r.reference} [{r.verdict}]"
                       for r in rows]))

    # ---- report
    overall = all(ok for _, ok, _ in gates if ok is not None)
    out_lines = [f"# QA report — {epub.name}", ""]
    for name, ok, lines in gates:
        badge = "PASS" if ok else ("FAIL" if ok is not None else "·")
        out_lines.append(f"## Gate {name}: {badge}")
        out_lines += [f"- {ln}" for ln in lines]
        out_lines.append("")
        print(f"gate {name}: {badge}" + (f" | {lines[0]}" if lines else ""))
    out_lines.append(f"Overall: {'PASS' if overall else 'FAIL'}")
    report = epub.parent / "qa_report.md"
    report.write_text("\n".join(out_lines) + "\n")
    (epub.parent / "qa.json").write_text(json.dumps(
        [{"gate": n, "ok": ok, "detail": ls} for n, ok, ls in gates], indent=1,
        ensure_ascii=False))
    print(f"report: {report}")
    print(f"Overall: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


def _source_entries(cfg, doc: PdfDoc, flow, labels) -> list[tuple[str, str]]:
    """(title, printed label) from the CHOSEN TOC source."""
    if cfg.toc_source == "outline" and doc.outline:
        skip = set(cfg.pages_cover) | set(cfg.pages_exclude) | set(cfg.toc_printed_pages)
        # print-navigation artifacts: the EPUB's cover/toc landmarks and
        # title page cover these; they produce no headings
        skip_titles = {"cover", "title", "copyright", "contents", "title page"}
        return [(o.title, labels.get(o.target_page, str(o.target_page)))
                for o in doc.outline
                if o.level <= cfg.nav_depth and o.target_page not in skip
                and o.title.strip().lower() not in skip_titles]
    entries = []
    for b in flow.blocks:
        if getattr(b, "style", "") == "__toc__":
            text = b.text()
            title, _, label = text.rpartition("\t")
            if title:
                entries.append((title, label))
    if cfg.toc_source == "links" and doc.links and not entries:
        return [(f"p.{l.target_page}", labels.get(l.target_page, ""))
                for l in doc.links]
    return entries
