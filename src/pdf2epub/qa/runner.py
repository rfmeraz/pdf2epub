"""QA gate suite: 20 gates. Gates 1-10, 11b (noteref seams) and 19
(Qurʾānic citations) must pass; 11-12 informational; 13-17 (typographic
fidelity) report would-PASS/would-FAIL and gate once promoted via
typography.GATING; 18 (--visual) emits agent-graded contact sheets and is
always informational.

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

_BLOCKS = {f"{_X}{t}" for t in ("p", "h1", "h2", "h3", "h4", "li", "figcaption")}


def _doc_text(d) -> str:
    """Block-aware text: inline elements join WITHOUT spaces (itertext with
    ' '.join splits 'no-<i>dharma</i>' into a fake hyphen artifact), blocks
    join with one space."""
    body = d.root.find(f"{_X}body")
    if body is None:
        return ""
    parts = []
    for el in body.iter():
        if el.tag in _BLOCKS:
            parts.append("".join(el.itertext()))
    return " ".join(parts) if parts else " ".join(body.itertext())


def _read_css(ep) -> str:
    for item in ep.manifest.values():
        if item.get("media_type") == "text/css":
            return ep.read(item["href"]).decode("utf-8")
    return ""


def run_qa(epub: Path, config: Path, reference: Path | None = None,
           visual: bool = False, visual_pages: int = 14) -> int:
    cfg = load_config(config)
    quiet = lambda m: None  # noqa: E731
    gates: list[tuple[str, bool | None, list[str]]] = []

    # ---- deterministic re-derivation of expectations (agreement scores on:
    # engine-disputed pages cannot serve as ground truth)
    doc: PdfDoc = extract(cfg.pdf_path(), say=quiet, agreement=True)
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
    # gate 11b evidence must be gathered BEFORE the noteref strip below
    # destroys it (the anchors are removed in place)
    seam_defects = pdfchecks.noteref_seam_defects(spine)
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
    spine_text = " ".join(_doc_text(d) for d in body_docs)
    spine_text_norm = normalize(spine_text)
    # coverage compares 'text minus honorific glyphs' on BOTH sides: the gt
    # strips PUA chars; the candidate must shed their inserted readings
    coverage_candidate = normalize(_unsub(spine_text))
    all_text_norm = normalize(spine_text + " " +
                              " ".join(_doc_text(d) for d in notes_docs))

    # ---- gate 1: epubcheck
    ok, msgs = run_epubcheck(epub)
    gates.append(("1 epubcheck", ok, msgs[-1:]))

    # ---- gate 2: text coverage vs independent ground truth
    gt = build_ground_truth(cfg.pdf_path(), cfg, doc, note_texts_by_page,
                            stripped_lines=res.furniture_texts,
                            region_texts=res.region_texts)
    # the rebuilt hyperlinked Contents replaces the printed TOC pages; exclude
    # them like figure pages (itemized), the TOC gates cover that content
    toc_excl = 0
    for pno in cfg.toc_printed_pages:
        toc_excl += len(gt.pages.get(pno, ""))
        gt.pages[pno] = ""
    # engine-disputed pages: the two witnesses disagree on what the text IS
    # (broken source CMaps decode differently per engine) — neither side is
    # ground truth; these pages live in the agent's render-review queue
    disputed = gt.disputed_chars
    disputed_pages = list(gt.disputed_pages)
    for p in doc.pages:
        if p.engine_agreement is not None and p.engine_agreement < 90 \
                and gt.pages.get(p.number):
            disputed += len(gt.pages[p.number])
            disputed_pages.append(p.number)
            gt.pages[p.number] = ""
    from .groundtruth import paged_coverage

    cov = paged_coverage(gt, coverage_candidate)
    lines = [f"coverage {cov.coverage*100:.2f}% (gate {COVERAGE_GATE*100:.0f}%); "
             f"note chars stripped {gt.note_chars_removed}, figure-page chars "
             f"excluded {gt.figure_chars_excluded}, figure-region chars excluded "
             f"{gt.region_chars_excluded}, printed-TOC chars excluded {toc_excl}, "
             f"engine-disputed chars excluded {disputed} (pages {disputed_pages[:8]})"]
    for seg in cov.missing_segments[:12]:
        lines.append(f"MISSING: {seg[:110]}")
    if len(cov.missing_segments) > 12:
        lines.append(f"… and {len(cov.missing_segments)-12} more missing segments")
    gates.append(("2 text coverage", cov.coverage >= COVERAGE_GATE, lines))

    # ---- gate 3: footnotes present on their page. Placement is proven by the
    # probes; gt excision misses are gate-2 bookkeeping (the unexcised text
    # stays in the coverage denominator) — informational here
    fails: list[str] = []
    disputed_set = set(disputed_pages)
    undecidable_note_pages: list[int] = []  # visual QA samples these
    for nid, note in sorted(flow.notes.items()):
        pno = int(nid[1:5])
        if pno in disputed_set or pno + 1 in disputed_set:
            undecidable_note_pages.append(pno)  # gt can't read this page;
            continue                            # render review covers it
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
             f"{len(gt.note_strip_failures)} gt-excision misses (info, in coverage); "
             f"{len(undecidable_note_pages)} on engine-disputed pages "
             "(render review)"]
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
    # a book's own TOC is sometimes off by one page from the printed opener;
    # adjacent-label violations are the source's discrepancy, not ours
    import re as _re

    hard_viol = []
    for v in order.violations:
        m = _re.search(r"printed page '([^']+)'.*?on '([^']+)'", v)
        if m and m.group(1) in page_order and m.group(2) in page_order and \
                abs(page_order.index(m.group(1)) - page_order.index(m.group(2))) <= 1:
            order.notes.append(f"±1 TOC/print discrepancy (source's own): {v}")
        else:
            hard_viol.append(v)
    gates.append(("6 reading order", not hard_viol,
                  [f"{order.matched_entries}/{order.checked} TOC entries on their "
                   f"printed page"] + hard_viol[:6]
                  + [f"info: {n}" for n in order.notes[:2]]
                  + [f"info: {o}" for o in order.orphan_headings[:3]]))

    # ---- gate 7: TOC agreement (source entries present in nav)
    nav_doc = ep.nav_doc()
    nav_entries = pdfchecks.parse_nav_toc(nav_doc.root) if nav_doc else []
    agree = pdfchecks.check_toc_agreement(
        nav_entries, [t for t, _ in source_entries], cfg.nav_depth)
    gates.append(("7 toc agreement", agree.ok,
                  [f"{agree.matched}/{agree.source_total} source entries in nav "
                   f"(nav extra: {agree.nav_extra})"] + agree.missing[:6]))

    # ---- gate 8: furniture leak (toc-entry <p>s legitimately mirror the
    # running-head text — they ARE the heading titles)
    _skip_cls = ("toc-entry", "titletext", "contents-head")
    para_texts = ["".join(p.itertext()) for d in body_docs
                  for p in d.root.iter(f"{_X}p")
                  if not any(c in (p.get("class") or "") for c in _skip_cls)]
    leaks = pdfchecks.check_furniture_leak(para_texts, gt.furniture_templates, cfg.title)
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

    # ---- gate 11b: noteref seams (a letter/digit directly after a noteref
    # is always an artifact — lost join separator or fused paragraph)
    gates.append(("11b noteref seam", not seam_defects,
                  [f"{len(seam_defects)} letter/digit-after-noteref seams"]
                  + seam_defects[:8]))

    # ---- gate 12 (info): reference scorecard
    if reference:
        rows = ref_compare(epub, reference)
        gates.append(("12 reference scorecard (info)", None,
                      [f"{r.metric}: ours={r.ours} ref={r.reference} [{r.verdict}]"
                       for r in rows]))

    # ---- gates 13-17: typographic fidelity (informational until promoted
    # via typography.GATING after the regression-corpus matrix is clean)
    from . import typography

    for g in typography.run_typography_checks(
            doc=doc, res=res, flow=flow, cfg=cfg, labels=labels,
            in_flow=in_flow, body_docs=body_docs,
            css_text=_read_css(ep), source_entries=source_entries):
        gates.append((g.name, (g.ok if g.name in typography.GATING else None),
                      g.lines))

    # ---- gate 19: Qurʾānic citation index — validates a 'Qurʾānic verses
    # cited' apparatus against the Qurʾān's fixed structure (sura:verse
    # ranges, entry order, page labels). The columned index pages are
    # engine-disputed, so gate 2's coverage witness is blind there — this
    # is the deterministic check that catches column interleaving.
    from .quran import check_quran_index

    qres = check_quran_index(body_docs, set(nav.pagelist_labels))
    gates.append(("19 quran citations", qres.ok, qres.lines))

    # ---- gate 18 (info, --visual): sampled contact sheets for agent grading
    if visual:
        from .visual import run_visual

        vres = run_visual(epub, cfg, doc, flow, res, labels, disputed_pages,
                          undecidable_note_pages, epub.parent / "qa_visual",
                          cap=visual_pages, say=quiet)
        gates.append(("18 visual sample (info)", None, vres.gate_lines))

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
    # entries whose target pages the config excludes (index/table apparatus,
    # flagged in book.yaml) have no content to navigate to
    if entries and cfg.pages_exclude:
        excluded_labels = {labels.get(p) for p in cfg.pages_exclude}
        entries = [(t, l) for t, l in entries if l not in excluded_labels]
    if cfg.toc_source == "printed" and cfg.nav_depth == 1 and entries:
        # printed-TOC levels derive from entry indentation; depth-1 books
        # (MR: chapters are TOC-only groupings with no physical headings)
        # gate on the outdented entries only
        from ..analyze import _trailing_folio_entry

        x0_by_title: dict[str, float] = {}
        for pno in cfg.toc_printed_pages:
            for ln in doc.page(pno).lines:
                ent = _trailing_folio_entry(ln)
                if ent:
                    x0_by_title.setdefault(ent[0], ln.x0)
        if x0_by_title:
            base = min(x0_by_title.values())
            entries = [(t, l) for t, l in entries
                       if x0_by_title.get(t, base) <= base + 8]
    if cfg.toc_source == "links" and doc.links and not entries:
        return [(f"p.{l.target_page}", labels.get(l.target_page, ""))
                for l in doc.links]
    return entries
