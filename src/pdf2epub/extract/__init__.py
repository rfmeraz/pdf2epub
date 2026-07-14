"""extract(pdf) -> PdfDoc, plus the per-page engine-agreement score.

Dual-engine doctrine: poppler pdftotext independently re-extracts every page
and a normalized fuzzy similarity is recorded on PdfPage.engine_agreement.
The two engines share no glyph-decoding code, so disagreement is an
extraction-confidence flag (low pages go to the agent's render-review queue).
Engines only ever FLAG divergence — nothing merges text.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from rapidfuzz import fuzz

from ..core.textnorm import normalize
from ..pdfmodel import PdfDoc
from .engine import get_engine

AGREEMENT_WARN_BELOW = 90.0
_MIN_CHARS_FOR_SCORE = 40  # pages with less text score noisily; skip them


def poppler_page_texts(pdf: Path,
                       crop: tuple[int, int, int, int] | None = None) -> list[str]:
    """Whole-document pdftotext, split on form feeds. The independent witness.

    ``crop`` is (-x, -y, -W, -H) in MediaBox top-left points (PdfDoc.trim_crop_box):
    poppler reads the MediaBox, so without it printer slug lines outside the trim
    leak in (verified on Book of Knowledge / Me and Rumi)."""
    cmd = ["pdftotext"]
    if crop:
        x, y, w, h = crop
        cmd += ["-x", str(x), "-y", str(y), "-W", str(w), "-H", str(h)]
    cmd += [str(pdf), "-"]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    pages = proc.stdout.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def score_agreement(doc: PdfDoc, poppler_pages: list[str]) -> list[int]:
    """Fill PdfPage.engine_agreement; return page numbers scoring below the bar."""
    low: list[int] = []
    for page in doc.pages:
        idx = page.number - 1
        if idx >= len(poppler_pages):
            break
        ours = normalize(" ".join(ln.text() for ln in page.lines))
        theirs = normalize(poppler_pages[idx])
        if len(ours) < _MIN_CHARS_FOR_SCORE and len(theirs) < _MIN_CHARS_FOR_SCORE:
            continue
        score = fuzz.ratio(ours, theirs)
        page.engine_agreement = round(score, 1)
        if score < AGREEMENT_WARN_BELOW:
            low.append(page.number)
    return low


def extract(pdf: Path, say=print, engine_name: str = "mupdf",
            agreement: bool = True) -> PdfDoc:
    engine = get_engine(engine_name)
    doc = engine.read(pdf)

    n_clipped = sum(len(p.clipped_lines) for p in doc.pages)
    image_only = [p.number for p in doc.pages if p.image_only]
    say(f"extract[{engine.name}]: {doc.n_pages} pages, {len(doc.fonts)} font clusters, "
        f"{len(doc.outline)} outline entries, {len(doc.links)} internal links, "
        f"{n_clipped} lines clipped outside trim"
        + (f", {doc.subscript_dots} dot diacritic(s) recomposed"
           if doc.subscript_dots else "")
        + (f", {doc.cancelled_spaces} layout-cancelled space(s) dropped"
           if doc.cancelled_spaces else ""))
    if image_only:
        msg = (f"{len(image_only)} image-only page(s) (no usable text layer): "
               f"{image_only[:10]}{'…' if len(image_only) > 10 else ''} — OCR is out of "
               "scope; ship as figure pages only if content is verifiable from renders")
        doc.warnings.append(msg)
        say(f"  WARNING: {msg}")

    if agreement:
        low = score_agreement(doc, poppler_page_texts(pdf, crop=doc.trim_crop_box))
        if low:
            msg = (f"engine agreement below {AGREEMENT_WARN_BELOW:.0f} on "
                   f"{len(low)} page(s): {low[:15]}{'…' if len(low) > 15 else ''} — "
                   "review these pages against renders before trusting their text")
            doc.warnings.append(msg)
            say(f"  WARNING: {msg}")
    return doc
