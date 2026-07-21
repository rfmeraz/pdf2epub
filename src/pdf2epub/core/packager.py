# Forked from idml2epub src/idml2epub/packager.py @ 7eb7eac (adapted: fonts/css/catalog
# come from ctx.embedded_fonts / ctx.style_catalog; pdf2epub uuid namespace)
"""Assemble the EPUB: OPF, NCX, cover page, deterministic zip.

Hand-written packaging (chosen over the ebooklib library): ebooklib
re-parses and re-templates content documents, which risks the epub:type
semantics; writing the OPF/NCX/zip directly keeps every byte under control and
the build deterministic (fixed zip timestamps, uuid5 fallback identifier).
"""

from __future__ import annotations

import mimetypes
import os
import re
import tempfile
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from .emit_xhtml import EmitResult, OutFile
from .nav import _toc_entries, build_nav_xhtml

_FIXED_STAMP = (2026, 1, 1, 0, 0, 0)  # reproducible builds

_CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_COVER_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      lang="{lang}" xml:lang="{lang}">
<head><title>Cover</title>
<style>body{{margin:0;padding:0;text-align:center}}img{{max-width:100%;max-height:100vh}}</style>
</head>
<body epub:type="cover">
<figure id="cover-image"><img src="image/{cover}" alt="{alt}"/></figure>
</body>
</html>
"""


def _media_type(name: str) -> str:
    guess = {
        ".xhtml": "application/xhtml+xml",
        ".css": "text/css",
        ".ncx": "application/x-dtbncx+xml",
        ".otf": "application/vnd.ms-opentype",
        ".ttf": "application/vnd.ms-opentype",
    }.get(Path(name).suffix.lower())
    return guess or mimetypes.guess_type(name)[0] or "application/octet-stream"


def _identifier(cfg) -> str:
    ident = getattr(cfg, "identifier", None)
    if ident:  # explicit persistent id (a UUID, or an already-formed urn:)
        return ident if ident.startswith("urn:") else f"urn:uuid:{ident}"
    if cfg.isbn_epub:
        digits = re.sub(r"[^0-9Xx]", "", cfg.isbn_epub)
        return f"urn:isbn:{digits}"
    # last-resort slug-derived UUID: NOT unique across unrelated books with the
    # same slug — build.py warns loudly when this path is taken.
    return "urn:uuid:" + str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"pdf2epub:{cfg.slug}")
    )


def _opf(cfg, manifest: list[tuple[str, str, str, str]], spine_ids: list[str],
         has_pagelist: bool = True) -> str:
    """manifest entries: (id, href, media-type, properties)."""
    L = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<package version="3.0" xmlns="http://www.idpf.org/2007/opf" '
        'unique-identifier="bookid" xml:lang="%s">' % cfg.language,
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">',
        f'<dc:identifier id="bookid">{escape(_identifier(cfg))}</dc:identifier>',
        f'<dc:title id="title">{escape(cfg.title)}</dc:title>',
        '<meta refines="#title" property="title-type">main</meta>',
    ]
    if cfg.subtitle:
        L.append(f'<dc:title id="subtitle">{escape(cfg.subtitle)}</dc:title>')
        L.append('<meta refines="#subtitle" property="title-type">subtitle</meta>')
    for lang in [cfg.language, *cfg.additional_languages]:
        L.append(f"<dc:language>{escape(lang)}</dc:language>")
    for i, c in enumerate(cfg.creators, 1):
        cid = f"creator{i}"
        L.append(f'<dc:creator id="{cid}">{escape(c["name"])}</dc:creator>')
        if c.get("role"):
            L.append(
                f'<meta refines="#{cid}" property="role" scheme="marc:relators">'
                f'{escape(c["role"])}</meta>'
            )
    if cfg.publisher:
        L.append(f"<dc:publisher>{escape(cfg.publisher)}</dc:publisher>")
    if cfg.date:
        L.append(f"<dc:date>{escape(cfg.date)}</dc:date>")
    if cfg.isbn_print:
        digits = re.sub(r"[^0-9Xx]", "", cfg.isbn_print)
        L.append(f"<dc:source>urn:isbn:{digits}</dc:source>")
    # dcterms:modified describes the EPUB REVISION, not the print date: use the
    # explicit release epoch when set, else fall back to the print year.
    released = getattr(cfg, "released", None)
    stamp = f"{released}T00:00:00Z" if released else f"{cfg.date or '2026'}-01-01T00:00:00Z"
    L.append(f'<meta property="dcterms:modified">{stamp}</meta>')
    # accessibility
    L.append('<meta property="schema:accessMode">textual</meta>')
    L.append('<meta property="schema:accessMode">visual</meta>')
    L.append('<meta property="schema:accessModeSufficient">textual,visual</meta>')
    features = ["tableOfContents", "alternativeText"]
    if has_pagelist:  # only claim page navigation when a print PDF gave us anchors
        features += ["pageNavigation", "pageBreakMarkers", "printPageNumbers"]
    for feat in features:
        L.append(f'<meta property="schema:accessibilityFeature">{feat}</meta>')
    if has_pagelist:
        # pagination source (EPUB a11y / Ace epub-pagesource): identify the
        # print edition the page breaks came from — the print ISBN when known,
        # else the book's own identifier.
        pbsrc = (f"urn:isbn:{re.sub(r'[^0-9Xx]', '', cfg.isbn_print)}"
                 if cfg.isbn_print else _identifier(cfg))
        L.append(f'<meta property="pageBreakSource">{escape(pbsrc)}</meta>')
    L.append('<meta property="schema:accessibilityHazard">none</meta>')
    if cfg.accessibility_summary:
        L.append(
            '<meta property="schema:accessibilitySummary">'
            f"{escape(' '.join(cfg.accessibility_summary.split()))}</meta>"
        )
    if any(props == "cover-image" for _, _, _, props in manifest):
        cover_id = next(i for i, _, _, p in manifest if p == "cover-image")
        L.append(f'<meta name="cover" content="{cover_id}"/>')
    L.append("</metadata>")

    L.append("<manifest>")
    for mid, href, mt, props in manifest:
        prop_attr = f' properties="{props}"' if props else ""
        L.append(f'<item id="{mid}" href="{escape(href)}" media-type="{mt}"{prop_attr}/>')
    L.append("</manifest>")

    L.append(f'<spine{" toc=\"ncx\"" if cfg.include_ncx else ""}>')
    for sid in spine_ids:
        linear = ' linear="no"' if sid == "coverpage" else ""
        L.append(f'<itemref idref="{sid}"{linear}/>')
    L.append("</spine>")
    L.append("</package>")
    return "\n".join(L)


def _ncx(cfg, result: EmitResult) -> str:
    files = result.files + ([result.notes_file] if result.notes_file else [])
    entries = _toc_entries(files, drop_numeric=cfg.toc_drop_numeric_nav_entries)
    L = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">',
        "<head>",
        f'<meta name="dtb:uid" content="{escape(_identifier(cfg))}"/>',
        '<meta name="dtb:depth" content="3"/>',
        '<meta name="dtb:totalPageCount" content="0"/>',
        '<meta name="dtb:maxPageNumber" content="0"/>',
        "</head>",
        f"<docTitle><text>{escape(cfg.title)}</text></docTitle>",
        "<navMap>",
    ]
    play = 0
    stack: list[int] = []
    for level, title, href in entries:
        play += 1
        level = max(1, min(level, (stack[-1] if stack else 0) + 1))
        while stack and stack[-1] >= level:
            L.append("</navPoint>")
            stack.pop()
        L.append(
            f'<navPoint id="np{play}" playOrder="{play}">'
            f"<navLabel><text>{escape(title)}</text></navLabel>"
            f'<content src="{escape(href)}"/>'
        )
        stack.append(level)
    while stack:
        L.append("</navPoint>")
        stack.pop()
    L.append("</navMap></ncx>")
    return "\n".join(L)


def stage_package(ctx, result: EmitResult) -> Path:
    cfg = ctx.cfg
    oebps = cfg.build_dir / "oebps"

    from .emit_css import generate_css

    fonts = getattr(ctx, "embedded_fonts", None)
    if fonts is None:
        raise RuntimeError("stage_package: ctx.embedded_fonts not set — run the fonts stage first")
    catalog = getattr(ctx, "style_catalog", None)
    if catalog is None:
        raise RuntimeError("stage_package: ctx.style_catalog not set — run styles_synth first")
    fontfaces = [
        {"family": f.family, "style": f.style, "file": f.file_name,
         "script": f.script, "lang": f.lang}
        for f in fonts
    ]
    used_styles = set(ctx.flow.style_usage)
    css_dir = oebps / "css"
    css_dir.mkdir(parents=True, exist_ok=True)
    (css_dir / "styles.css").write_text(generate_css(cfg, catalog, used_styles, fontfaces))

    # cover
    cover_asset = None
    if cfg.cover:
        cover_src = cfg.resolve_workspace(cfg.cover)
        if cover_src.exists():
            suffix = cover_src.suffix.lower()
            cover_name = f"cover{suffix}"
            (oebps / "image").mkdir(parents=True, exist_ok=True)
            (oebps / "image" / cover_name).write_bytes(cover_src.read_bytes())
            (oebps / "cover.xhtml").write_text(
                _COVER_XHTML.format(
                    lang=cfg.language, cover=cover_name,
                    alt=escape(f"Front cover of {cfg.title}"),
                )
            )
            cover_asset = cover_name
        else:
            ctx.say(f"  cover file missing: {cover_src}")

    # copy image assets from the build cache into the packaging tree
    img_dir = oebps / "image"
    img_dir.mkdir(parents=True, exist_ok=True)
    for asset in getattr(ctx, "image_assets", []):
        (img_dir / asset.out_name).write_bytes(asset.path.read_bytes())

    # nav
    (oebps / "nav.xhtml").write_text(build_nav_xhtml(result, cfg, has_cover=bool(cover_asset)))
    # legacy NCX: opt-out via output.include_ncx. Remove any stale toc.ncx when
    # disabled — stage_package zips ALL of oebps, so a leftover would ship
    # despite the manifest/spine omitting it.
    ncx_path = oebps / "toc.ncx"
    if cfg.include_ncx:
        ncx_path.write_text(_ncx(cfg, result))
    elif ncx_path.exists():
        ncx_path.unlink()

    # manifest + spine
    manifest: list[tuple[str, str, str, str]] = [
        ("nav", "nav.xhtml", "application/xhtml+xml", "nav"),
        ("css", "css/styles.css", "text/css", ""),
    ]
    if cfg.include_ncx:
        manifest.insert(1, ("ncx", "toc.ncx", "application/x-dtbncx+xml", ""))
    spine: list[str] = []
    if cover_asset:
        manifest.append(("coverimg", f"image/{cover_asset}", _media_type(cover_asset), "cover-image"))
        manifest.append(("coverpage", "cover.xhtml", "application/xhtml+xml", ""))
        spine.append("coverpage")
    all_files: list[OutFile] = result.files + ([result.notes_file] if result.notes_file else [])
    for f in all_files:
        manifest.append((f.file_id, f.file_name, "application/xhtml+xml", ""))
        spine.append(f.file_id)
    for i, asset in enumerate(getattr(ctx, "image_assets", []), 1):
        manifest.append((f"img{i:03d}", f"image/{asset.out_name}", asset.media_type, ""))
    for i, f in enumerate(fonts, 1):
        manifest.append((f"font{i}", f"font/{f.file_name}", f.media_type, ""))

    has_pagelist = any(f.pagebreaks for f in all_files)
    (oebps / "content.opf").write_text(_opf(cfg, manifest, spine, has_pagelist))

    # zip into a UNIQUE temp in build_dir (same filesystem, so run_build can
    # os.replace() it onto the canonical name atomically only after epubcheck
    # passes — a fixed .part name would let concurrent builds clobber it).
    # keep the .epub extension so epubcheck accepts it; the leading "." + the
    # .gitignore hidden-epub rule keep the temp out of version control.
    fd, tmp = tempfile.mkstemp(dir=cfg.build_dir, prefix=f".{cfg.slug}.",
                               suffix=".epub")
    os.close(fd)
    epub_path = Path(tmp)
    with zipfile.ZipFile(epub_path, "w") as zf:
        info = zipfile.ZipInfo("mimetype", date_time=_FIXED_STAMP)
        zf.writestr(info, "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        info = zipfile.ZipInfo("META-INF/container.xml", date_time=_FIXED_STAMP)
        zf.writestr(info, _CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        for path in sorted(oebps.rglob("*")):
            if path.is_dir() or path.name.startswith("tmp-render-"):
                continue
            arc = f"OEBPS/{path.relative_to(oebps)}"
            info = zipfile.ZipInfo(arc, date_time=_FIXED_STAMP)
            zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    size_mb = epub_path.stat().st_size / 1e6
    ctx.say(f"packaged {cfg.slug}.epub ({size_mb:.1f} MB, {len(manifest)} manifest "
            f"items; staged, pending epubcheck)")
    return epub_path
