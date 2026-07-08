"""Extraction IR: what the PDF actually contains, engine-neutral, in PDF points.

Coordinates are top-origin page space (PyMuPDF convention): x grows right,
y grows down, units are points. Every page's lines are already clipped to the
TrimBox; what fell outside (printer slug lines) is retained in clipped_lines
as evidence, never silently discarded. JSON round-trip mirrors core/model.py
so ``--dump-ir`` snapshots are diffable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class PdfFont:
    id: int
    family: str      # subset prefix stripped: "Minion", "Bembo-SC", "Honorifics"
    raw_family: str  # as embedded: "OFQNHO+Honorifics" (provenance)
    size: float      # pt, rounded to 0.1 — (family, size) is the cluster key
    color: str       # #rrggbb


@dataclass(slots=True)
class PdfRun:
    text: str
    font_id: int
    italic: bool = False
    bold: bool = False
    superscript: bool = False
    x0: float = 0.0
    x1: float = 0.0
    y0: float = 0.0
    y1: float = 0.0


@dataclass(slots=True)
class PdfLine:
    """One grouped baseline: runs sorted by x."""
    runs: list[PdfRun]
    x0: float = 0.0
    x1: float = 0.0
    y0: float = 0.0
    y1: float = 0.0
    vertical: bool = False  # vertical writing direction (CJK columns)

    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    def dominant_font(self) -> int:
        """Font id carrying the most characters on this line."""
        weights: dict[int, int] = {}
        for r in self.runs:
            weights[r.font_id] = weights.get(r.font_id, 0) + len(r.text)
        return max(weights, key=weights.get) if weights else -1


@dataclass(slots=True)
class PdfPage:
    number: int              # 1-based physical page
    label: str | None        # /PageLabels-derived, None if absent
    width: float             # page (CropBox) width, pt
    height: float
    trim: tuple[float, float, float, float]  # TrimBox in page space (x0,y0,x1,y1)
    lines: list[PdfLine] = field(default_factory=list)          # inside trim
    clipped_lines: list[PdfLine] = field(default_factory=list)  # outside trim (slugs)
    n_chars: int = 0
    n_images: int = 0
    image_only: bool = False
    engine_agreement: float | None = None  # 0-100 similarity vs poppler pdftotext


@dataclass(slots=True)
class OutlineEntry:
    level: int        # 1-based nesting depth
    title: str        # \x00 padding and whitespace stripped
    target_page: int  # 1-based; the physical PDF page the bookmark opens


@dataclass(slots=True)
class LinkAnnot:
    page: int                                  # 1-based page carrying the link
    rect: tuple[float, float, float, float]    # page space
    target_page: int                           # 1-based destination page


@dataclass(slots=True)
class PdfDoc:
    pdf_path: str
    sha256: str
    producer: str
    n_pages: int
    pages: list[PdfPage] = field(default_factory=list)
    fonts: dict[int, PdfFont] = field(default_factory=dict)
    outline: list[OutlineEntry] = field(default_factory=list)
    links: list[LinkAnnot] = field(default_factory=list)  # internal GoTo only
    uri_link_count: int = 0                                # external links: counted + warned
    # dominant interior TrimBox as a poppler crop (-x -y -W -H, MediaBox
    # top-left origin, ints) — shared by the engine-agreement score and the
    # QA ground truth so both witnesses read the same page region
    trim_crop_box: tuple[int, int, int, int] | None = None
    warnings: list[str] = field(default_factory=list)

    def page(self, number: int) -> PdfPage:
        return self.pages[number - 1]


# ---------------------------------------------------------------- JSON dump

def pdfdoc_to_dict(doc: PdfDoc) -> dict:
    return {
        "pdf_path": doc.pdf_path,
        "sha256": doc.sha256,
        "producer": doc.producer,
        "n_pages": doc.n_pages,
        "fonts": {str(k): asdict(v) for k, v in sorted(doc.fonts.items())},
        "outline": [asdict(o) for o in doc.outline],
        "links": [asdict(a) for a in doc.links],
        "uri_link_count": doc.uri_link_count,
        "trim_crop_box": list(doc.trim_crop_box) if doc.trim_crop_box else None,
        "warnings": list(doc.warnings),
        "pages": [
            {
                "number": p.number,
                "label": p.label,
                "width": p.width,
                "height": p.height,
                "trim": list(p.trim),
                "n_chars": p.n_chars,
                "n_images": p.n_images,
                "image_only": p.image_only,
                "engine_agreement": p.engine_agreement,
                "lines": [_line_to_dict(ln) for ln in p.lines],
                "clipped_lines": [_line_to_dict(ln) for ln in p.clipped_lines],
            }
            for p in doc.pages
        ],
    }


def _line_to_dict(ln: PdfLine) -> dict:
    return {
        "bbox": [ln.x0, ln.y0, ln.x1, ln.y1],
        "vertical": ln.vertical,
        "runs": [
            {
                "text": r.text,
                "font": r.font_id,
                "italic": r.italic,
                "bold": r.bold,
                "sup": r.superscript,
                "bbox": [r.x0, r.y0, r.x1, r.y1],
            }
            for r in ln.runs
        ],
    }
