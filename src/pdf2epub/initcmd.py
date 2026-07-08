"""init: extract + analyze a PDF, write the evidence pack and a draft book.yaml.

The draft is a PROPOSAL: every judgment carries a confidence comment and
FILL-ME-IN markers where only the agent (looking at renders) can decide.
A FILL-ME-IN left in place fails the build loudly — never silently.
"""

from __future__ import annotations

import json
from pathlib import Path

from .analyze import Analysis, analysis_to_dict, analyze
from .extract import extract
from .pdfmodel import PdfDoc, pdfdoc_to_dict
from .report import write_structure_report
from .thumbs import render_thumbs


def _locate_pdf(pdf_or_folder: Path) -> Path:
    p = pdf_or_folder.expanduser().resolve()
    if p.is_file():
        return p
    if p.is_dir():
        pdfs = sorted(p.glob("*.pdf")) + sorted(p.glob("*.PDF"))
        if len(pdfs) == 1:
            return pdfs[0]
        raise SystemExit(f"{p}: expected exactly one PDF, found {len(pdfs)}")
    raise SystemExit(f"{pdf_or_folder}: not found")


def run_init(pdf_or_folder: Path, workspace: Path) -> int:
    pdf = _locate_pdf(pdf_or_folder)
    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    analysis_dir = workspace / "analysis"
    analysis_dir.mkdir(exist_ok=True)

    doc = extract(pdf)
    a = analyze(doc)
    (analysis_dir / "analysis.json").write_text(
        json.dumps({"doc": {k: v for k, v in pdfdoc_to_dict(doc).items() if k != "pages"},
                    "analysis": analysis_to_dict(a)}, ensure_ascii=False, indent=1))
    write_structure_report(doc, a, analysis_dir / "structure_report.md")
    render_thumbs(pdf, a.flagged_pages, analysis_dir)

    draft = _draft_yaml(pdf, doc, a, workspace)
    target = workspace / "book.yaml"
    if target.exists():
        target = workspace / "book.draft-new.yaml"
        print(f"book.yaml exists — draft written to {target.name} instead")
    target.write_text(draft)
    print(f"init done: {analysis_dir/'structure_report.md'}")
    print(f"draft config: {target}")
    print("next: the agent reads the report, LOOKS at analysis/pages/*.png, and "
          "finalizes every FILL-ME-IN and low-confidence judgment in book.yaml")
    return 0


def _rel_source(pdf: Path, workspace: Path) -> tuple[str, str]:
    try:
        rel = pdf.relative_to(workspace)
        parts = rel.parts
        if len(parts) > 1:
            return str(Path(*parts[:-1])), parts[-1]
        return ".", parts[-1]
    except ValueError:
        return str(pdf.parent), pdf.name


def _draft_yaml(pdf: Path, doc: PdfDoc, a: Analysis, workspace: Path) -> str:
    folder, name = _rel_source(pdf, workspace)
    q = json.dumps  # JSON string quoting is valid YAML

    body_first = next((n for n, f in sorted(a.printed_folios.items()) if f == "1"), None)
    cover_pages = [1] if a.cover_proposal.get("mode") == "render" else []
    front_first = (cover_pages[-1] + 1) if cover_pages else 1
    front_last = (body_first - 1) if body_first else front_first
    body_last = doc.n_pages

    L: list[str] = []
    w = L.append
    w(f"# pdf2epub book.yaml — DRAFT written by init; every judgment below is a")
    w(f"# proposal traced to analysis/structure_report.md. FILL-ME-IN markers fail")
    w(f"# the build until the agent decides them (by LOOKING at analysis/pages/).")
    w("")
    w("source:")
    w(f"  folder: {q(folder)}")
    w(f"  pdf: {q(name)}")
    w(f"  sha256: {q(doc.sha256)}")
    w("")
    w("metadata:                     # JP-P5 — read title/copyright page renders")
    w("  title: FILL-ME-IN")
    w("  creators: []                # [{name: ..., role: aut|trl|edt|...}]")
    w("  publisher: \"\"               # from the copyright page; no default")
    w("  language: en")
    w("  additional_languages: []")
    w("  isbn_epub:                  # never invented; empty -> urn:uuid (flagged)")
    w("  isbn_print:")
    w("  date:")
    if a.cover_proposal.get("mode") == "render":
        w("  cover: assets/cover.jpg     # produced by cover_render at build time")
        w("  cover_render: {page: 1, box: trim, dpi: 300}")
        w(f"  # cover evidence: {a.cover_proposal.get('reason', '')}")
    else:
        w("  cover: assets/cover.jpg     # produced by cover_synthesize at build time")
        w("  cover_synthesize: true      # no cover in the PDF — flagged in handoff")
        w(f"  # cover evidence: {a.cover_proposal.get('reason', '')}")
    w("")
    w("pages:                        # JP-P2 — confirm against thumbs")
    w(f"  cover: {cover_pages}")
    if body_first:
        w(f"  front: {{first: {front_first}, last: {front_last}}}   # roman folios")
        w(f"  body:  {{first: {body_first}, last: {body_last}}}   # printed folio '1' seen on p.{body_first}")
    else:
        w(f"  front: {{first: {front_first}, last: {front_first}}}   # FILL-ME-IN: no arabic folio '1' found")
        w(f"  body:  {{first: {front_first + 1}, last: {body_last}}}   # FILL-ME-IN")
    w("  exclude: []")
    w(f"  label_source: {a.label_source_proposal}   # folio-vs-label agreement: {a.folio_agreement_pct}%")
    w("  label_overrides: {}")
    w("  role_overrides: []          # e.g. {page: 3, role: title-page}")
    w("")
    w("furniture:")
    w(f"  top_band: {a.top_band}")
    w(f"  repeat_min_pages: 3")
    w("  extra: []")
    w("  keep: []")
    for r in a.repeated_lines[:8]:
        w(f"  # repeated ({r['band']}, {r['count']}p): {r['text']!r}")
    w("")
    w("styles:                       # JP-P1 — review every non-high confidence row")
    w(f"  body_pstyle: {q(a.body_pstyle)}")
    w("  pstyle_map:")
    for c in a.clusters:
        if c.n_chars < 40 and c.n_lines < 3:
            continue
        cls = ""
        w(f"    {q(c.pstyle)}: {{role: {c.role}}}{cls}   # {c.confidence}: {c.reason}")
    w("  charstyles: {}              # font-level flags, e.g. Bembo-SC: {smallcaps: true}")
    w("  unmapped_role: p")
    w("  fail_on_unmapped: false     # set true once the map is reviewed")
    w("")
    w("flow:")
    w(f"  indent_threshold: {a.indent_threshold_proposal}")
    w(f"  gap_factor: 1.6             # median leading measured: {a.median_leading}pt")
    w("  dehyphenate: lower-only")
    w(f"  restore_spaces: {str(a.restore_spaces_proposal).lower()}       # lost-space hits: {a.lost_space_count}")
    w("  join_center_lines: true")
    w("  reattach_dropcaps: true")
    w("  overrides: []               # {page, line(RAW extract idx), action, note}")
    w("")
    w("footnotes:                    # JP-P4")
    w(f"  policy: {a.footnote_policy_proposal}   # regions on {len(a.footnote_pages)} pages; census {a.footnote_marker_census}")
    w(f"  marker: {a.footnote_marker_proposal}")
    w("")
    w("toc:                          # JP-P3 — three witnesses, see report")
    w(f"  source: {a.toc_source_proposal}   # outline={len(doc.outline)} printed={len(a.toc_entries)} links={len(doc.links)}")
    w(f"  printed_pages: {a.toc_pages}")
    w("  handling: rebuild")
    w("  strip_page_numbers: true")
    w("  nav_depth: 2")
    w("")
    w("glyphs:                       # JP-P6 — verify EACH on its render, then set action")
    if a.pua_census:
        w("  pua_map:")
        for r in a.pua_census:
            w(f"    \"\\u{ord(r['char']):04X}\": {{action: FILL-ME-IN, note: "
              f"\"{r['hex']} x{r['count']} from {'/'.join(r['families'])} — "
              f"LOOK at analysis/pages/p{r['pages'][0]:04d}.png\"}}")
        w("  fail_on_unmapped_pua: true")
    else:
        w("  pua_map: {}")
        w("  fail_on_unmapped_pua: true")
    w("")
    w("fonts:                        # JP-P7 — OFL only, from system files, never from the PDF")
    w("  embed: []")
    if a.pua_census:
        w("  # honorific/symbol glyphs likely need: {family: Amiri, file: /usr/share/fonts/amiri-fonts/Amiri-Regular.ttf, script: cjk, lang: ar}")
    if a.cjk_pages:
        w("  # live CJK needs: {family: \"Noto Serif CJK SC\", file: /usr/share/fonts/google-noto-serif-cjk-fonts/NotoSerifCJK-Regular.ttc, script: cjk, lang: zh}")
    w("  subset: true")
    w("")
    w("languages: {cjk_han_only: zh, overrides: []}   # JP-P8")
    w("")
    w("split: {at_roles: [h1], warn_over_files: 90}")
    w("")
    w("images:                       # JP-P4b")
    w(f"  raster_dpi: 300")
    w(f"  max_pixels: 1600")
    w("  alt: {}")
    w("  decorative: []")
    if a.figure_pages_proposal:
        w(f"  figure_pages:")
        w(f"    - {{pages: {a.figure_pages_proposal}, alt_template: \"FILL-ME-IN describing page {{label}}\", lang: zh}}")
    else:
        w("  figure_pages: []")
    w("")
    w(f"output: {{slug: {workspace.name}, include_ncx: true}}")
    w("")
    return "\n".join(L)
