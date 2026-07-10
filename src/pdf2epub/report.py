"""structure_report.md: the analyzer's evidence, formatted for the agent to read."""

from __future__ import annotations

from pathlib import Path

from .analyze import Analysis
from .pdfmodel import PdfDoc


def write_structure_report(doc: PdfDoc, a: Analysis, out: Path) -> None:
    L: list[str] = []
    w = L.append
    w(f"# Structure report — {Path(doc.pdf_path).name}")
    w("")
    w(f"- pages: {doc.n_pages}; producer: {doc.producer or '?'}; sha256: {doc.sha256[:16]}…")
    w(f"- outline entries: {len(doc.outline)}; internal links: {len(doc.links)}; "
      f"external URI links: {doc.uri_link_count}")
    w(f"- trim crop (poppler -x -y -W -H): {doc.trim_crop_box}")
    if doc.warnings:
        w("")
        w("## Extract warnings")
        for wmsg in doc.warnings:
            w(f"- {wmsg}")

    w("")
    w("## Font clusters (JP-P1) — proposed pstyle_map")
    w("")
    w(f"Body cluster: **{a.body_pstyle}** ({a.body_size}pt)")
    w("")
    w("| pstyle | lines | chars | pages | role (conf) | reason | sample |")
    w("|---|---|---|---|---|---|---|")
    for c in a.clusters:
        if c.n_chars < 40 and c.n_lines < 3:
            continue
        sample = (c.samples[0][:60] if c.samples else "").replace("|", "\\|")
        w(f"| `{c.pstyle}` | {c.n_lines} | {c.n_chars} | {c.n_pages} "
          f"| {c.role} ({c.confidence}) | {c.reason} | {sample} |")

    w("")
    w("## Furniture (JP-P2)")
    w(f"- proposed top_band: {a.top_band}pt")
    for r in a.repeated_lines[:15]:
        w(f"- `{r['text']}` ({r['band']}, {r['count']} pages, e.g. {r['pages'][:5]})")

    w("")
    w("## Folios vs /PageLabels (JP-P2)")
    w(f"- printed folios found on {len(a.printed_folios)} pages; "
      f"agreement with /PageLabels: {a.folio_agreement_pct}%")
    w(f"- **label_source proposal: {a.label_source_proposal}**")
    for m in a.folio_mismatches[:10]:
        w(f"  - page {m['page']}: printed `{m['printed']}` vs label `{m['label']}`")

    w("")
    w("## TOC witnesses (JP-P3)")
    w(f"- outline: {len(doc.outline)} entries | printed TOC pages: {a.toc_pages} "
      f"({len(a.toc_entries)} parsed entries) | links: {len(doc.links)}")
    w(f"- **toc.source proposal: {a.toc_source_proposal}**")
    bad = [t for t in a.toc_witness_table if not t["heading_on_target"]]
    w(f"- outline entries WITHOUT a matching heading on their target page: "
      f"{len(bad)}/{len(a.toc_witness_table)}")
    for t in bad[:10]:
        w(f"  - `{t['outline']}` -> p.{t['target']} (printed: {t['printed']!r})")
    if a.toc_entries:
        w("- printed-TOC parse sample:")
        for e in a.toc_entries[:8]:
            w(f"  - p.{e['page']}: `{e['text']}` … {e['label']} "
              f"(link target: {e['target']})")

    w("")
    w("## Footnotes (JP-P4)")
    w(f"- pages with small-font bottom regions: {len(a.footnote_pages)} "
      f"(e.g. {a.footnote_pages[:8]})")
    w(f"- marker census: {a.footnote_marker_census}")
    w(f"- **proposal: policy={a.footnote_policy_proposal}, "
      f"marker={a.footnote_marker_proposal}**")
    for s in a.footnote_samples:
        w(f"  - p.{s['page']}: {s['text'][:120]}")

    w("")
    w("## Paragraph joining (flow knobs)")
    w(f"- median leading: {a.median_leading}pt; indent histogram: {a.indent_histogram}")
    w(f"- **indent_threshold proposal: {a.indent_threshold_proposal}pt**")
    w(f"- line-end hyphens: {a.eol_hyphen_count}; lost-space hits: {a.lost_space_count} "
      f"→ **restore_spaces proposal: {a.restore_spaces_proposal}**")
    w(f"- drop-cap pages: {a.dropcap_pages[:10]}")

    w("")
    w("## Special glyphs (JP-P6) — every PUA char needs a verified pua_map entry")
    if not a.pua_census:
        w("- none found")
    for r in a.pua_census:
        w(f"- {r['hex']} ×{r['count']} from {r['families']} — LOOK at "
          f"analysis/pages/p{r['pages'][0]:04d}.png (pages {r['pages']})")

    w("")
    w("## Languages / CJK (JP-P8, JP-P4b)")
    w(f"- RTL chars: {a.rtl_chars}")
    w(f"- CJK pages: {len(a.cjk_pages)}; figure-page proposal (vertical CJK): "
      f"{_ranges(a.figure_pages_proposal)}")
    inline_cjk = [c for c in a.cjk_pages if c["page"] not in set(a.figure_pages_proposal)]
    if inline_cjk:
        w(f"- inline CJK (stays live text, needs OFL substitute font): "
          f"{[c['page'] for c in inline_cjk][:15]}")

    w("")
    w("## Block shapes (JP-P9 — blocks: judgment)")
    if a.verse_suspect_pages:
        w(f"- verse-shaped blocks on {len({v['page'] for v in a.verse_suspect_pages})} "
          f"page(s) ({len(a.verse_suspect_pages)} group(s)) — verify against "
          "renders, then record blocks.verse specs (base/turns are pt "
          "offsets from the shift-corrected column left):")
        for v in a.verse_suspect_pages[:20]:
            w(f"  - p.{v['page']} lines {v['lines'][0]}..{v['lines'][1]} "
              f"base {v['base']} turns {v['turns']}: {v['first']!r}")
        if len(a.verse_suspect_pages) > 20:
            w(f"  - … and {len(a.verse_suspect_pages) - 20} more group(s) "
              "(see analysis.json verse_suspect_pages)")
        # draft spec: aggregate contiguous page ranges sharing offsets
        by_off: dict[tuple, list[int]] = {}
        for v in a.verse_suspect_pages:
            key = (tuple(v["base"]), tuple(v["turns"]))
            by_off.setdefault(key, []).append(v["page"])
        w("  paste-ready draft (VERIFY each range on renders first):")
        w("  # blocks:")
        w("  #   verse:")
        for (base, turns), pages in sorted(by_off.items(),
                                           key=lambda kv: -len(kv[1])):
            w(f"  #     - {{pages: {sorted(set(pages))}, "
              f"base: {list(base)}, turns: {list(turns)}, "
              f"note: FILL render-verified}}")
    else:
        w("- no verse-shaped blocks detected (the build's verse-suspect "
          "witness re-checks on kept lines)")
    if a.quote_suspect_pages:
        w(f"- justified-inset (quote-shaped) blocks on "
          f"{len({q['page'] for q in a.quote_suspect_pages})} page(s) "
          f"({len(a.quote_suspect_pages)} run(s)) — verify against renders, "
          "then record blocks.quotes specs (insets are pt offsets from the "
          "page's own body edges):")
        by_inset: dict[tuple, list[int]] = {}
        for q in a.quote_suspect_pages:
            key = (round(q["left_inset"]), round(q["right_inset"]))
            by_inset.setdefault(key, []).append(q["page"])
        for (li, ri), pages in sorted(by_inset.items(),
                                      key=lambda kv: -len(kv[1]))[:8]:
            ps = sorted(set(pages))
            w(f"  - inset {li}/{ri}pt on {len(ps)} page(s) "
              f"{_ranges(ps[:40])}")
        w("  paste-ready draft (VERIFY each range on renders first):")
        w("  # blocks:")
        w("  #   quotes:")
        for (li, ri), pages in sorted(by_inset.items(),
                                      key=lambda kv: -len(kv[1]))[:4]:
            rng = _ranges(sorted(set(pages)))[1:-1]
            quoted = ", ".join(f'"{r}"' for r in rng.split(", "))
            w(f"  #     - {{pages: [{quoted}], "
              f"left_inset: {li}, right_inset: {ri}, "
              f"note: FILL render-verified}}")
    else:
        w("- no justified-inset (quote-shaped) blocks detected")
    if a.list_marker_pages:
        w(f"- marker-list shapes (>=2 marker lines at one entry stop) on "
          f"{len({m['page'] for m in a.list_marker_pages})} page(s) — "
          "verify against renders, then record blocks.lists specs (entry "
          "stops derive per spec from the marker lines themselves; hang = "
          "the turnover column's offset from the stop, measured on a "
          "wrapped item):")
        by_shape: dict[tuple, list[int]] = {}
        for m in a.list_marker_pages:
            by_shape.setdefault((m["marker"], round(m["left"])),
                                []).append(m["page"])
        for (mk, off), pages in sorted(by_shape.items(),
                                       key=lambda kv: -len(kv[1]))[:8]:
            ps = sorted(set(pages))
            w(f"  - {mk} at left {off}pt on {len(ps)} page(s) "
              f"{_ranges(ps[:40])}")
        w("  paste-ready draft (VERIFY each range on renders; measure "
          "hang from a wrapped item):")
        w("  # blocks:")
        w("  #   lists:")
        for (mk, off), pages in sorted(by_shape.items(),
                                       key=lambda kv: -len(kv[1]))[:4]:
            rng = _ranges(sorted(set(pages)))[1:-1]
            quoted = ", ".join(f'"{r}"' for r in rng.split(", "))
            w(f"  #     - {{pages: [{quoted}], marker: {mk}, "
              f"hang: FILL, note: FILL render-verified}}")
    else:
        w("- no marker-list shapes detected")

    w("")
    w("## Layout anomalies")
    w(f"- column-suspect pages: {_ranges(a.column_suspect_pages)}")
    w(f"- image-only pages: {a.image_only_pages}")
    w(f"- low engine-agreement pages (<90): "
      f"{[(x['page'], x['score']) for x in a.low_agreement_pages[:15]]}")

    w("")
    w("## Cover (JP-P5)")
    w(f"- proposal: {a.cover_proposal}")

    w("")
    w("## Agent render queue")
    w("Full renders in analysis/pages/ — LOOK at each before finalizing book.yaml:")
    w(f"- {['p%04d.png' % p for p in a.flagged_pages]}")
    if a.warnings:
        w("")
        w("## Analyzer warnings")
        for wm in a.warnings:
            w(f"- {wm}")
    out.write_text("\n".join(L) + "\n")


def _ranges(pages: list[int]) -> str:
    if not pages:
        return "[]"
    out = []
    start = prev = pages[0]
    for p in pages[1:] + [None]:
        if p is not None and p == prev + 1:
            prev = p
            continue
        out.append(f"{start}-{prev}" if prev > start else f"{start}")
        if p is not None:
            start = prev = p
    return "[" + ", ".join(out) + "]"
