"""Deterministic build orchestrator: book.yaml -> EPUB, stage by stage.

Stages: extract -> flow -> map -> images -> xhtml -> package. --upto stops
after a stage (implies IR dumps into build/ir/). Every warning is mirrored
into build/warnings.md with page refs and ready-to-paste override snippets —
the conversion agent's adjudication queue.
"""

from __future__ import annotations

import hashlib
import json
import os
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
    cfg = load_config(config_path, require_complete=True)
    ctx = BuildContext(cfg, dump_ir)
    if not cfg.identifier and not cfg.isbn_epub:
        ctx.say("WARNING: no metadata.identifier and no isbn_epub — the EPUB id "
                "falls back to a slug-derived UUID (not unique across unrelated "
                "books with the same slug). Add metadata.identifier.")

    # stale-tree invariant: the packager zips a directory, so anything stale ships
    oebps = cfg.build_dir / "oebps"
    if oebps.exists():
        shutil.rmtree(oebps)
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    # ---- extract
    pdf = cfg.pdf_path()
    if not pdf.exists():
        raise SystemExit(f"source PDF not found: {pdf}")
    # snapshot the INPUTS the build is about to read (book.yaml + PDF). The
    # manifest records THESE hashes — the inputs the EPUB was actually built
    # from — and they are rechecked just before promotion, so a mid-build change
    # to book.yaml or the PDF aborts rather than shipping an EPUB mislabelled
    # with the changed input's hash.
    input_book_sha = _sha256(cfg.path)
    input_pdf_path = str(pdf)
    input_pdf_sha = _sha256(pdf)
    if cfg.sha256 and input_pdf_sha != cfg.sha256:
        raise SystemExit(
            f"source PDF sha256 mismatch: config pins {cfg.sha256[:12]}…, "
            f"file is {input_pdf_sha[:12]}… — re-run init or fix source.sha256")
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
    # ---- imprint-specific structural transforms (publisher back-matter the
    # generic flow can't model, e.g. World Wisdom editor's notes). Runs after
    # roles/lang are final so it can key on headings, and adds link markers
    # only — never rewords. No-op unless book.yaml sets `imprint:`.
    if cfg.imprint is not None:
        from .imprints import apply_imprint
        apply_imprint(res, cfg, ctx.pdf_doc, ctx.say)
    # ---- linked index locators: wrap index page numbers in #pg-<label> links
    # (opt-in via flow.columns[].index or the `index` role; no-op otherwise).
    from .index_locators import link_index_locators
    link_index_locators(res, cfg, ctx.say)
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
    emitter.resolve_crossref_links()
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

    # transactional promotion: package to a temp, epubcheck it, GENERATE the
    # provenance manifest to a second temp — all before the point of no return
    # — then os.replace both onto their canonical names. The manifest is
    # generated first because that's where the failures are (hashing, tool
    # probes): if it throws, the prior EPUB is left intact. The two renames are
    # same-dir and near-atomic; `pdf2epub verify` catches the vanishingly-rare
    # torn state between them.
    from .provenance import build_manifest, dumps, manifest_path

    tmp_epub = stage_package(ctx, result)
    final_epub = cfg.build_dir / f"{cfg.slug}.epub"
    final_manifest = manifest_path(cfg)
    tmp_manifest: Path | None = None
    epubcheck_status, epubcheck_version = "skipped", None
    try:
        _write_warnings(ctx)  # may raise SystemExit (stale adjudications)
        if epubcheck:
            from .core.qa_epubcheck import run_epubcheck

            ok, messages = run_epubcheck(tmp_epub)
            for m in messages:
                ctx.say(f"  {m}")
            if not ok:
                ctx.say("epubcheck: FAILED — canonical EPUB left unchanged")
                return 1
            epubcheck_status = "passed"
            epubcheck_version = _epubcheck_version(messages)
            ctx.say("epubcheck: clean")
        # inputs must not have changed during the build, else the manifest would
        # label this EPUB with the hash of inputs it was NOT built from.
        if _sha256(cfg.path) != input_book_sha:
            raise SystemExit("book.yaml changed during the build — aborting "
                             "(the EPUB was built from the prior config; rebuild)")
        cur_pdf = cfg.pdf_path()
        if not cur_pdf.exists() or _sha256(cur_pdf) != input_pdf_sha:
            raise SystemExit("source PDF changed or vanished during the build — "
                             "aborting (the EPUB was built from the prior PDF)")

        epub_sha = _sha256(tmp_epub)
        manifest = build_manifest(cfg, epub_sha256=epub_sha,
                                  epubcheck_status=epubcheck_status,
                                  epubcheck_version=epubcheck_version,
                                  book_yaml_sha256=input_book_sha,
                                  source_pdf_path=input_pdf_path,
                                  source_pdf_sha256=input_pdf_sha)
        tmp_manifest = final_manifest.parent / f".{final_manifest.name}.tmp"
        tmp_manifest.write_text(dumps(manifest))

        # promote both staged artifacts. Back up the prior EPUB so a
        # promotion-time exception (incl. Ctrl-C) rolls back to the consistent
        # prior state; the sole residual window is a hard process-kill BETWEEN
        # the two same-dir renames, which `pdf2epub verify` still detects (the
        # new EPUB won't match the stale manifest's recorded hash).
        epub_backup = final_epub.parent / f".{final_epub.name}.prev"
        had_prev = final_epub.exists()
        if had_prev:
            os.replace(final_epub, epub_backup)
        try:
            os.replace(tmp_epub, final_epub)
            os.replace(tmp_manifest, final_manifest)
            tmp_manifest = None
        except BaseException:
            if had_prev and epub_backup.exists():
                os.replace(epub_backup, final_epub)  # roll back to the prior EPUB
            raise
        finally:
            if had_prev and epub_backup.exists():
                epub_backup.unlink()
        ctx.say(f"provenance: {final_manifest.name} (epub {epub_sha[:12]}…, "
                f"epubcheck {epubcheck_status}, "
                f"rev {manifest['git'].get('rev', '?')[:12]}"
                f"{' +dirty' if manifest['git'].get('dirty') else ''})")
    finally:
        if tmp_epub.exists():
            tmp_epub.unlink()  # stray temp from an early bail
        if tmp_manifest is not None and tmp_manifest.exists():
            tmp_manifest.unlink()
    return 0


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _epubcheck_version(messages: list[str]) -> str:
    for m in messages:
        if m.startswith("epubcheck "):
            return m.split(":", 1)[0].removeprefix("epubcheck ").strip()
    return "unknown"


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
    from .warnqueue import (
        CONTENT_RISK,
        AdjWarning,
        apply_adjudications,
        auto_resolve,
        derive_warnings,
        render_queue,
    )

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
