"""Page renders for the agent's eyes: thumbnails of every page + full renders
of flagged pages (TOC, PUA samples, footnote samples, low-agreement, cover).

analysis/thumbs/ and analysis/pages/ are gitignored (regenerable); the agent
Reads these PNGs during structure inference and warning adjudication.
"""

from __future__ import annotations

from pathlib import Path

import fitz


def render_thumbs(pdf: Path, flagged_pages: list[int], analysis_dir: Path,
                  say=print, thumb_dpi: int = 40, full_dpi: int = 150) -> None:
    thumbs = analysis_dir / "thumbs"
    pages = analysis_dir / "pages"
    thumbs.mkdir(parents=True, exist_ok=True)
    pages.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    flagged = set(flagged_pages)
    n_pages = doc.page_count
    for page in doc:
        n = page.number + 1
        page.get_pixmap(dpi=thumb_dpi).save(thumbs / f"p{n:04d}.png")
        if n in flagged:
            page.get_pixmap(dpi=full_dpi).save(pages / f"p{n:04d}.png")
    doc.close()
    say(f"renders: {n_pages} thumbs, {len(flagged)} full renders -> {analysis_dir}/pages/")


def render_page(pdf: Path, page_no: int, out_path: Path, dpi: int = 150,
                clip_trim: bool = False) -> Path:
    """One-off render (agent adjudication, cover extraction preview)."""
    doc = fitz.open(pdf)
    page = doc[page_no - 1]
    clip = None
    if clip_trim:
        r = fitz.Rect(page.trimbox) * page.transformation_matrix
        r.normalize()
        clip = r
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.get_pixmap(dpi=dpi, clip=clip).save(out_path)
    doc.close()
    return out_path
