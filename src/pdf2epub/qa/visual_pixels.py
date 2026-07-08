"""Pixel-side visual QA: contact sheets, PUA glyph crop pairs, figure dHash.

Whole-page pixel diffing is deliberately absent — reflow makes it pure noise.
Pixels are only compared where the content SHOULD be visually identical:
a source glyph vs its substituted character, a shipped image vs its region
on the page. Everything else is composed for agent eyes, not scored.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_PUA_RE = re.compile("[\\ue000-\\uf8ff]")
_GUTTER = 32
_MARGIN = 16


# ------------------------------------------------------------ contact sheets

def compose_sheet(pdf_png: Path, epub_png: Path | None, out: Path,
                  max_h: int = 1400) -> Path:
    left = Image.open(pdf_png).convert("RGB")
    if epub_png is not None and Path(epub_png).exists():
        right = Image.open(epub_png).convert("RGB")
    else:
        right = Image.new("RGB", left.size, (229, 229, 229))

    def fit(img: Image.Image) -> Image.Image:
        if img.height <= max_h:
            return img
        w = round(img.width * max_h / img.height)
        return img.resize((max(w, 1), max_h))

    left, right = fit(left), fit(right)
    h = max(left.height, right.height) + 2 * _MARGIN
    w = left.width + right.width + _GUTTER + 2 * _MARGIN
    sheet = Image.new("RGB", (w, h), (255, 255, 255))
    sheet.paste(left, (_MARGIN, _MARGIN))
    sheet.paste(right, (_MARGIN + left.width + _GUTTER, _MARGIN))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


# ------------------------------------------------------------ glyph crops

def find_pua_run(doc, char: str, in_flow: list[int]):
    """First in-flow (page, run-bbox) carrying the raw PUA char."""
    for pno in in_flow:
        for ln in doc.page(pno).lines:
            for r in ln.runs:
                if char in r.text:
                    return pno, (r.x0, r.y0, r.x1, r.y1)
    return None, None


def crop_pdf_region(pdf: Path, pno: int, rect_pt, dpi: int = 300,
                    pad_pt: float = 3.0) -> Image.Image:
    """Render just the padded region (page-space pt, top-origin) via fitz."""
    import fitz

    with fitz.open(pdf) as fz:
        page = fz[pno - 1]
        clip = fitz.Rect(rect_pt[0] - pad_pt, rect_pt[1] - pad_pt,
                         rect_pt[2] + pad_pt, rect_pt[3] + pad_pt)
        clip &= page.rect
        pix = page.get_pixmap(dpi=dpi, clip=clip)
        return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _pick_font(ep_fonts: list[tuple[str, bytes]], text: str) -> bytes | None:
    """Shipped face whose cmap covers the first non-ASCII char of ``text``."""
    from fontTools.ttLib import TTFont

    probe = next((c for c in text if ord(c) > 0x7F), text[:1] if text else "")
    for _, blob in ep_fonts:
        try:
            tf = TTFont(io.BytesIO(blob), fontNumber=0, lazy=True)
            cmap = tf.getBestCmap()
        except Exception:
            continue
        if probe and ord(probe) in cmap:
            return blob
    return None


def render_reading(text: str, ep_fonts: list[tuple[str, bytes]],
                   height: int = 96) -> Image.Image:
    """The substituted reading rendered in a shipped font (pillow; complex
    shaping only with libraqm — single-codepoint ligatures are exact, long
    RTL phrases approximate; the manifest flags those)."""
    blob = _pick_font(ep_fonts, text)
    size = int(height * 0.6)
    try:
        font = ImageFont.truetype(io.BytesIO(blob), size) if blob else \
            ImageFont.load_default(size)
    except Exception:
        font = ImageFont.load_default(size)
    probe = Image.new("RGB", (8, 8))
    box = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
    w = max(box[2] - box[0] + 24, 48)
    img = Image.new("RGB", (w, height), (255, 255, 255))
    ImageDraw.Draw(img).text((12 - box[0], (height - (box[3] - box[1])) // 2
                              - box[1]), text, fill=(0, 0, 0), font=font)
    return img


def pua_crop_pairs(doc, cfg, pdf: Path, ep_fonts: list[tuple[str, bytes]],
                   in_flow: list[int], out_dir: Path) -> list[dict]:
    out: list[dict] = []
    for char, rule in sorted(cfg.pua_map.items(), key=lambda kv: kv[0]):
        hexname = f"u{ord(char):04X}"
        pno, rect = find_pua_run(doc, char, in_flow)
        entry = {"hex": f"U+{ord(char):04X}", "action": rule.action,
                 "substituted": rule.char or "", "lang": rule.lang or "",
                 "note": rule.note, "source_page": pno, "crop": None}
        if pno is None:
            entry["note"] = (entry["note"] + " (no in-flow occurrence)").strip()
            out.append(entry)
            continue
        left = crop_pdf_region(pdf, pno, rect)
        target_h = 96
        left = left.resize((max(1, round(left.width * target_h / left.height)),
                            target_h))
        panels = [left]
        if rule.action == "char" and rule.char:
            panels.append(render_reading(rule.char, ep_fonts))
        w = sum(p.width for p in panels) + _GUTTER * (len(panels) - 1) + 2 * _MARGIN
        h = target_h + 2 * _MARGIN
        sheet = Image.new("RGB", (w, h), (255, 255, 255))
        x = _MARGIN
        for i, p in enumerate(panels):
            sheet.paste(p, (x, _MARGIN))
            x += p.width
            if i < len(panels) - 1:
                ImageDraw.Draw(sheet).line(
                    [(x + _GUTTER // 2, _MARGIN), (x + _GUTTER // 2, h - _MARGIN)],
                    fill=(180, 180, 180))
                x += _GUTTER
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{hexname}.png"
        sheet.save(path)
        entry["crop"] = path.name
        if rule.char and len(rule.char) > 1 and rule.lang:
            entry["note"] = (entry["note"]
                             + " (multi-char reading: shaping approximate)").strip()
        out.append(entry)
    return out


# ------------------------------------------------------------ figure dHash

def dhash(img: Image.Image) -> int:
    g = img.convert("L").resize((9, 8))
    px = list(g.tobytes())          # mode L: raw bytes ARE the pixel values
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def figure_phashes(flow, cfg, ep, pdf: Path, out_dir: Path,
                   threshold: int = 16) -> list[dict]:
    from ..core.model import Figure

    out: list[dict] = []
    for b in flow.blocks:
        if not isinstance(b, Figure) or not b.pdf_page:
            continue
        try:
            shipped = Image.open(io.BytesIO(
                ep.read(f"image/{b.image_key}"))).convert("RGB")
        except Exception as e:
            out.append({"image_key": b.image_key, "pdf_page": b.pdf_page,
                        "distance": None, "verdict": f"unreadable: {e}"})
            continue
        region = crop_pdf_region(
            pdf, b.pdf_page,
            (b.x_pt, b.y_pt, b.x_pt + b.width_pt, b.y_pt + b.height_pt),
            dpi=150, pad_pt=0.0)
        d = hamming(dhash(shipped), dhash(region))
        entry = {"image_key": b.image_key, "pdf_page": b.pdf_page,
                 "distance": d, "verdict": "ok" if d <= threshold else "review",
                 "pair": None}
        if d > threshold:
            out_dir.mkdir(parents=True, exist_ok=True)
            pair = out_dir / f"{Path(b.image_key).stem}.png"
            target_h = 400

            def fit(img):
                return img.resize((max(1, round(img.width * target_h
                                                / img.height)), target_h))
            l, r = fit(region), fit(shipped)
            sheet = Image.new("RGB", (l.width + r.width + _GUTTER + 2 * _MARGIN,
                                      target_h + 2 * _MARGIN), (255, 255, 255))
            sheet.paste(l, (_MARGIN, _MARGIN))
            sheet.paste(r, (_MARGIN + l.width + _GUTTER, _MARGIN))
            sheet.save(pair)
            entry["pair"] = pair.name
        out.append(entry)
    return out
