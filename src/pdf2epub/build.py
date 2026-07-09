"""Deterministic build orchestrator: book.yaml -> EPUB, stage by stage.

Stages: extract -> flow -> map -> images -> xhtml -> package. --upto stops
after a stage (implies IR dumps into build/ir/). Every warning is mirrored
into build/warnings.md with page refs and ready-to-paste override snippets —
the conversion agent's adjudication queue.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .config import PdfBookConfig, load_config
from .core.model import flowdoc_to_dict

STAGES = ["extract", "flow", "map", "images", "xhtml"]


class BuildContext:
    def __init__(self, cfg: PdfBookConfig, dump_ir: bool):
        self.cfg = cfg
        self.dump = dump_ir
        self.pdf_doc = None
        self.flow = None
        self.flow_res = None
        self.image_assets: list = []
        self.embedded_fonts = None
        self.style_catalog = None
        self.lang_census: dict = {}

    def say(self, msg: str) -> None:
        print(msg, flush=True)

    def ir_dump(self, stage: str, data: dict) -> None:
        if not self.dump:
            return
        ir = self.cfg.build_dir / "ir"
        ir.mkdir(parents=True, exist_ok=True)
        (ir / f"{stage}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1))


def run_build(config_path: Path, dump_ir: bool = False, upto: str | None = None,
              epubcheck: bool = True) -> int:
    cfg = load_config(config_path)
    ctx = BuildContext(cfg, dump_ir)

    # stale-tree invariant: the packager zips a directory, so anything stale ships
    oebps = cfg.build_dir / "oebps"
    if oebps.exists():
        shutil.rmtree(oebps)
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    # ---- extract
    pdf = cfg.pdf_path()
    if not pdf.exists():
        raise SystemExit(f"source PDF not found: {pdf}")
    if cfg.sha256:
        actual = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if actual != cfg.sha256:
            raise SystemExit(
                f"source PDF sha256 mismatch: config pins {cfg.sha256[:12]}…, "
                f"file is {actual[:12]}… — re-run init or fix source.sha256")
    from .extract import extract
    from .pdfmodel import pdfdoc_to_dict

    ctx.pdf_doc = extract(pdf, say=ctx.say)
    ctx.ir_dump("extract", pdfdoc_to_dict(ctx.pdf_doc))
    if upto == "extract":
        _write_warnings(ctx)
        return 0

    # ---- flow
    from .flowbuilder import build_flow

    res = build_flow(ctx.pdf_doc, cfg, say=ctx.say)
    ctx.flow = res.flow
    ctx.flow_res = res
    ctx.say(f"flow: {len(ctx.flow.blocks)} blocks, {len(ctx.flow.notes)} notes; "
            + ", ".join(f"{k}={v}" for k, v in sorted(res.counts.items())))
    ctx.ir_dump("flow", flowdoc_to_dict(ctx.flow))
    if upto == "flow":
        _write_warnings(ctx)
        return 0

    # ---- map
    from .mapping import stage_map

    stage_map(ctx, res)
    ctx.ir_dump("map", flowdoc_to_dict(ctx.flow))
    if upto == "map":
        _write_warnings(ctx)
        return 0

    # ---- images (figures + cover)
    from .figures import stage_images

    stage_images(ctx)
    if upto == "images":
        _write_warnings(ctx)
        return 0

    # ---- xhtml
    from .core.emit_xhtml import Emitter

    geo_width = _text_width_pt(ctx)
    emitter = Emitter(cfg, ctx.flow, ctx.say, text_width_pt=geo_width)
    result = emitter.emit()
    emitter.resolve_contents_links()
    ctx.emit_warnings = emitter.warnings
    out_dir = cfg.build_dir / "oebps"
    out_dir.mkdir(parents=True, exist_ok=True)
    from .core.emit_xhtml import render_file

    all_files = result.files + ([result.notes_file] if result.notes_file else [])
    for f in all_files:
        (out_dir / f.file_name).write_text(render_file(f, cfg.language))
    ctx.say(f"emitted {len(all_files)} content files")
    if upto == "xhtml":
        _write_warnings(ctx)
        return 0

    # ---- fonts + catalog + package
    from .fonts import stage_fonts_pdf
    from .styles_synth import build_catalog

    stage_fonts_pdf(ctx)
    ctx.style_catalog = build_catalog(ctx)
    from .core.packager import stage_package

    epub_path = stage_package(ctx, result)
    _write_warnings(ctx)

    if epubcheck:
        from .core.qa_epubcheck import run_epubcheck

        ok, messages = run_epubcheck(epub_path)
        for m in messages:
            ctx.say(f"  {m}")
        if not ok:
            ctx.say("epubcheck: FAILED")
            return 1
        ctx.say("epubcheck: clean")
    return 0


def _text_width_pt(ctx) -> float:
    from .analyze import column_geometry

    geo = column_geometry(ctx.pdf_doc)
    w = geo.col_right - geo.col_left
    return w if w > 50 else 360.0


def _write_warnings(ctx) -> None:
    """Derive the structured queue (warnqueue: codes, auto-resolve,
    adjudications) and write it per-config — ``warnings.md`` for book.yaml,
    ``warnings.<stem>.md`` for variant configs (no last-run-wins collision).
    Stale adjudications are config bugs and fail the build AFTER the file
    is written (the file shows what went stale)."""
    from .warnqueue import (CONTENT_RISK, AdjWarning, apply_adjudications,
                            auto_resolve, derive_warnings, render_queue)

    cfg = ctx.cfg
    name = ("warnings.md" if cfg.path.name == "book.yaml"
            else f"warnings.{cfg.path.stem}.md")
    out = cfg.build_dir / name
    aw = derive_warnings(ctx.pdf_doc, ctx.flow_res, ctx.flow, cfg)
    for w in getattr(ctx, "emit_warnings", []) or []:
        aw.append(AdjWarning("contents-unlinked", "advisory", w))
    auto_resolve(aw, cfg)
    open_, adjudicated, stale = apply_adjudications(aw, cfg)
    open_cr = [w for w in open_ if w.severity == CONTENT_RISK]
    L = ["# Build warnings — the adjudication queue",
         "",
         "Resolve every OPEN content-risk entry: LOOK at the page render,",
         "decide, and either fix it via config (the warning disappears on",
         "rebuild) or record the decision as an `adjudications:` entry with",
         "render evidence. QA gate 22 fails while any remain open.",
         ""]
    if not aw and not stale:
        L.append("(none — clean build)")
    else:
        L += render_queue(aw, stale)
    out.write_text("\n".join(L) + "\n")
    ctx.say(f"warnings: {len(aw)} derived, {len(open_cr)} open content-risk, "
            f"{len(adjudicated)} adjudicated, {len(stale)} stale -> {out}")
    if stale:
        raise SystemExit("stale adjudications (matched no open warning): "
                         + "; ".join(stale))
