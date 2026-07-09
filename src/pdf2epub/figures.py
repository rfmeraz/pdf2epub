"""Images stage: figure-page rasters (JP-P4b) + the cover fallback chain.

Cover chain (JP-P5, all outcomes flagged in the handoff): cover_render (the
PDF carries its cover) -> provided assets/ file -> cover_synthesize (a
deterministic typographic cover so no build blocks on cover art).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont, ImageStat


@dataclass(slots=True)
class ImageAsset:
    out_name: str
    path: Path
    media_type: str


def stage_images(ctx) -> None:
    cfg = ctx.cfg
    cache = cfg.build_dir / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    assets: list[ImageAsset] = []

    fig_pages = {p for fp in cfg.figure_pages for p in fp.pages}
    if fig_pages or cfg.figure_regions:
        pdf = fitz.open(cfg.pdf_path())
        for pno in sorted(fig_pages):
            page = pdf[pno - 1]
            clip = fitz.Rect(page.trimbox) * page.transformation_matrix
            clip.normalize()
            pix = page.get_pixmap(dpi=cfg.raster_dpi, clip=clip)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img = _postprocess(img, cfg.max_pixels)
            out = cache / f"page-{pno:04d}.png"
            img.save(out, optimize=True)
            assets.append(ImageAsset(out.name, out, "image/png"))
        # region figures (true tables/diagrams): the config rect is recorded
        # in extract-space (top-origin page coords) — the same space
        # get_pixmap's clip reads, so no transform is needed
        for k, fr in enumerate(cfg.figure_regions):
            page = pdf[fr.page - 1]
            pix = page.get_pixmap(dpi=cfg.raster_dpi, clip=fitz.Rect(fr.rect))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img = _postprocess(img, cfg.max_pixels)
            out = cache / f"region-{fr.page:04d}-{k}.png"
            img.save(out, optimize=True)
            assets.append(ImageAsset(out.name, out, "image/png"))
        pdf.close()
        ctx.say(f"figures: rendered {len(fig_pages)} page(s) + "
                f"{len(cfg.figure_regions)} region(s) at {cfg.raster_dpi} dpi")

    # cover
    if cfg.cover:
        cover_path = cfg.resolve_workspace(cfg.cover)
        if cfg.cover_render:
            _render_cover(cfg, cover_path)
            ctx.say(f"cover: rendered PDF page {cfg.cover_render.page} -> {cfg.cover}"
                    " [flag: cover from PDF render]")
        elif cover_path.exists():
            ctx.say(f"cover: using provided {cfg.cover}")
        elif cfg.cover_synthesize:
            _synthesize_cover(cfg, cover_path, ctx.say)
            ctx.say(f"cover: SYNTHESIZED typographic cover -> {cfg.cover} "
                    "[flag: no cover art existed — a human may want to supply one]")
        else:
            ctx.say(f"  WARNING: cover file missing: {cover_path} and no "
                    "render/synthesize fallback configured")

    # visual content not otherwise handled: surface for the agent
    covered = fig_pages | set(cfg.pages_cover)
    leftover = [p.number for p in ctx.pdf_doc.pages
                if p.n_images > 0 and p.number not in covered]
    if leftover:
        msg = (f"pages with embedded images not covered by cover/figure_pages: "
               f"{leftover[:15]}{'…' if len(leftover) > 15 else ''} — review renders; "
               "decide figure_pages/decorative or accept as text-only")
        ctx.flow.warnings.append(msg)
        ctx.say(f"  WARNING: {msg}")

    ctx.image_assets = assets


def _postprocess(img: Image.Image, max_pixels: int) -> Image.Image:
    if max(img.size) > max_pixels:
        scale = max_pixels / max(img.size)
        img = img.resize((round(img.width * scale), round(img.height * scale)),
                         Image.LANCZOS)
    rgb = img.convert("RGB")
    stat = ImageStat.Stat(rgb)
    r, g, b = stat.mean
    if abs(r - g) < 4 and abs(g - b) < 4:  # neutral page -> grayscale halves size
        return rgb.convert("L")
    return rgb


def _render_cover(cfg, out_path: Path) -> None:
    cr = cfg.cover_render
    pdf = fitz.open(cfg.pdf_path())
    page = pdf[cr.page - 1]
    clip = None
    if cr.box == "trim":
        clip = fitz.Rect(page.trimbox) * page.transformation_matrix
        clip.normalize()
    pix = page.get_pixmap(dpi=cr.dpi, clip=clip)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=90)
    pdf.close()


_COVER_FONTS = [
    "/usr/share/fonts/sil-gentium-basic-fonts/GenBasR.ttf",
    "/usr/share/fonts/gentium-plus/GentiumPlus-Regular.ttf",
    "/usr/share/fonts/amiri-fonts/Amiri-Regular.ttf",
    "/usr/share/fonts/google-noto/NotoSerif-Regular.ttf",
    "/usr/share/fonts/dejavu-serif-fonts/DejaVuSerif.ttf",
]


def _synthesize_cover(cfg, out_path: Path, say) -> None:
    W, H = 1600, 2400
    img = Image.new("RGB", (W, H), (247, 243, 233))
    draw = ImageDraw.Draw(img)
    font_file = next((f for f in _COVER_FONTS if Path(f).exists()), None)

    def fnt(size):
        return (ImageFont.truetype(font_file, size) if font_file
                else ImageFont.load_default(size))

    draw.rectangle([90, 90, W - 90, H - 90], outline=(120, 100, 60), width=6)

    def center(text, y, size, fill=(40, 35, 25)):
        f = fnt(size)
        lines = _wrap(draw, text, f, W - 320)
        for line in lines:
            w = draw.textlength(line, font=f)
            draw.text(((W - w) / 2, y), line, font=f, fill=fill)
            y += size * 1.25
        return y

    y = center(cfg.title or "Untitled", 500, 110)
    if cfg.subtitle:
        y = center(cfg.subtitle, y + 60, 66, fill=(80, 70, 50))
    names = ", ".join(c.get("name", "") for c in cfg.creators if c.get("name"))
    if names:
        center(names, y + 220, 72)
    if cfg.publisher:
        center(cfg.publisher, H - 320, 56, fill=(100, 90, 70))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=90)
    if font_file:
        say(f"  synthesized cover uses {Path(font_file).name}")


def _wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines
