"""PyMuPDF extraction engine: spans -> PdfLines, all metadata in one pass.

Span flags carry real superscript/italic/bold bits (no position heuristics).
Lines are re-grouped by baseline (MuPDF sometimes splits one visual line into
several blocks, e.g. a right-aligned folio next to a heading) and clipped to
the per-page TrimBox; clipped lines are kept as evidence. Fonts are interned
into a document-wide table keyed by (family, size, color) with subset
prefixes stripped.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import fitz  # PyMuPDF

from ..pdfmodel import (
    LinkAnnot,
    OutlineEntry,
    PdfDoc,
    PdfFont,
    PdfLine,
    PdfPage,
    PdfRun,
)

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")

# span flag bits (PyMuPDF docs)
_F_SUPERSCRIPT = 1
_F_ITALIC = 2
_F_BOLD = 16

_BASELINE_TOL = 2.0  # pt: lines whose tops are this close share a baseline


class _FontTable:
    def __init__(self):
        self.by_key: dict[tuple[str, float, str], int] = {}
        self.fonts: dict[int, PdfFont] = {}

    def intern(self, raw_family: str, size: float, color: str) -> int:
        family = _SUBSET_PREFIX.sub("", raw_family)
        # quantize to 0.5pt: InDesign optical sizing scatters one body style
        # across 10.8/10.9/11.0/11.1pt (verified on Book of Knowledge)
        size = round(size * 2) / 2
        key = (family, size, color)
        fid = self.by_key.get(key)
        if fid is None:
            fid = len(self.fonts)
            self.by_key[key] = fid
            self.fonts[fid] = PdfFont(id=fid, family=family, raw_family=raw_family,
                                      size=size, color=color)
        return fid


def _color_hex(color_int: int) -> str:
    return f"#{color_int & 0xFFFFFF:06x}"


def _link_target_page(link: dict) -> int | None:
    """1-based target page of an internal link, else None.

    LINK_GOTO carries a 0-based int; LINK_NAMED (InDesign's named destinations,
    what all four test books use) carries a 1-based page NUMBER AS A STRING
    (verified against pypdf ground truth: Me and Rumi 'Foreword' -> '10')."""
    kind = link.get("kind")
    if kind == fitz.LINK_GOTO:
        p = link.get("page", -1)
        return p + 1 if isinstance(p, int) and p >= 0 else None
    if kind == fitz.LINK_NAMED:
        p = link.get("page")
        if isinstance(p, str) and p.isdigit():
            return int(p)
        if isinstance(p, int) and p >= 0:
            return p + 1
    return None


_HEX_STRING = re.compile(r"<([0-9A-Fa-f]+)>")


def _decode_label(label: str | None) -> str | None:
    """PyMuPDF returns /PageLabels prefixes stored as UTF-16 PDF hex strings
    undecoded ('<FFFE5300...>23', Islam and Buddhism's 'Sec1:23')."""
    if not label:
        return label

    def _sub(m: re.Match) -> str:
        try:
            return bytes.fromhex(m.group(1)).decode("utf-16")
        except (ValueError, UnicodeDecodeError):
            return m.group(0)

    return _HEX_STRING.sub(_sub, label)


def parse_page_dict(pagedict: dict, trim: tuple[float, float, float, float],
                    table: _FontTable) -> tuple[list[PdfLine], list[PdfLine]]:
    """Raw get_text('dict') -> (lines inside trim, clipped lines), baseline-grouped.

    Pure function of its inputs so tests can drive it with synthetic dicts.
    """
    raw_lines: list[PdfLine] = []
    for block in pagedict.get("blocks", []):
        if block.get("type") != 0:  # not a text block
            continue
        for line in block.get("lines", []):
            d = line.get("dir", (1.0, 0.0))
            vertical = abs(d[1]) > abs(d[0])
            runs: list[PdfRun] = []
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text:
                    continue
                flags = span.get("flags", 0)
                bx = span.get("bbox", (0, 0, 0, 0))
                fid = table.intern(span.get("font", "?"), span.get("size", 0.0),
                                   _color_hex(span.get("color", 0)))
                runs.append(PdfRun(
                    text=text, font_id=fid,
                    italic=bool(flags & _F_ITALIC),
                    bold=bool(flags & _F_BOLD),
                    superscript=bool(flags & _F_SUPERSCRIPT),
                    x0=round(bx[0], 2), y0=round(bx[1], 2),
                    x1=round(bx[2], 2), y1=round(bx[3], 2),
                ))
            if not runs:
                continue
            raw_lines.append(_mk_line(runs, vertical))

    # group same-baseline fragments (horizontal lines only)
    raw_lines.sort(key=lambda ln: (round(ln.y0, 1), ln.x0))
    grouped: list[PdfLine] = []
    for ln in raw_lines:
        prev = grouped[-1] if grouped else None
        if (prev is not None and not ln.vertical and not prev.vertical
                and abs(ln.y0 - prev.y0) <= _BASELINE_TOL):
            prev.runs.extend(ln.runs)
            prev.runs.sort(key=lambda r: r.x0)
            _refresh_bbox(prev)
        else:
            grouped.append(ln)

    inside: list[PdfLine] = []
    clipped: list[PdfLine] = []
    tx0, ty0, tx1, ty1 = trim
    for ln in grouped:
        cx = (ln.x0 + ln.x1) / 2
        cy = (ln.y0 + ln.y1) / 2
        (inside if (tx0 <= cx <= tx1 and ty0 <= cy <= ty1) else clipped).append(ln)
    return inside, clipped


def _mk_line(runs: list[PdfRun], vertical: bool) -> PdfLine:
    ln = PdfLine(runs=runs, vertical=vertical)
    _refresh_bbox(ln)
    return ln


def _refresh_bbox(ln: PdfLine) -> None:
    ln.x0 = min(r.x0 for r in ln.runs)
    ln.y0 = min(r.y0 for r in ln.runs)
    ln.x1 = max(r.x1 for r in ln.runs)
    ln.y1 = max(r.y1 for r in ln.runs)


class MuPdfEngine:
    name = "mupdf"

    def read(self, pdf: Path) -> PdfDoc:
        raw = pdf.read_bytes()
        doc = fitz.open(stream=raw, filetype="pdf")
        if doc.needs_pass:
            raise SystemExit(
                f"{pdf.name} is encrypted — decrypt first (qpdf --decrypt in.pdf out.pdf)"
            )
        out = PdfDoc(
            pdf_path=str(pdf),
            sha256=hashlib.sha256(raw).hexdigest(),
            producer=(doc.metadata or {}).get("producer", ""),
            n_pages=doc.page_count,
        )
        table = _FontTable()
        crop_votes: dict[tuple[int, int, int, int], int] = {}

        # outline (\x00 padding seen in the wild: BoK InDesign CS6)
        for level, title, page_no in doc.get_toc(simple=True):
            title = (title or "").replace("\x00", "").strip()
            if page_no < 1:
                out.warnings.append(f"outline entry {title!r} has external/broken target; skipped")
                continue
            out.outline.append(OutlineEntry(level=level, title=title, target_page=page_no))

        for page in doc:
            number = page.number + 1
            if page.rotation:
                out.warnings.append(f"page {number} is rotated {page.rotation}° — review renders")
            # TrimBox -> top-origin page space
            trim_pdf = fitz.Rect(page.trimbox)
            trim_rect = trim_pdf * page.transformation_matrix
            trim_rect.normalize()
            trim = (round(trim_rect.x0, 2), round(trim_rect.y0, 2),
                    round(trim_rect.x1, 2), round(trim_rect.y1, 2))
            # poppler-crop vote: TrimBox in MediaBox top-left coordinates
            media = fitz.Rect(page.mediabox)
            vote = (round(trim_pdf.x0 - media.x0), round(media.y1 - trim_pdf.y1),
                    round(trim_pdf.width), round(trim_pdf.height))
            crop_votes[vote] = crop_votes.get(vote, 0) + 1

            pagedict = page.get_text("dict")
            lines, clipped = parse_page_dict(pagedict, trim, table)
            n_chars = sum(len(ln.text()) for ln in lines)
            n_images = len(page.get_images(full=False))
            pp = PdfPage(
                number=number,
                label=_decode_label(page.get_label() or None),
                width=round(page.rect.width, 2),
                height=round(page.rect.height, 2),
                trim=trim,
                lines=lines,
                clipped_lines=clipped,
                n_chars=n_chars,
                n_images=n_images,
                image_only=(n_chars < 20 and n_images > 0),
            )
            out.pages.append(pp)

            for link in page.get_links():
                target = _link_target_page(link)
                if target is not None:
                    r = link.get("from")
                    out.links.append(LinkAnnot(
                        page=number,
                        rect=(round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)),
                        target_page=target,
                    ))
                elif link.get("kind") == fitz.LINK_URI:
                    out.uri_link_count += 1
                else:
                    out.warnings.append(
                        f"page {number}: unresolvable link annotation (kind "
                        f"{link.get('kind')}, {link.get('name') or link.get('page')!r})"
                    )

        if out.uri_link_count:
            out.warnings.append(
                f"{out.uri_link_count} external URI link annotation(s) present — "
                "not modeled (internal GoTo links only)"
            )
        out.fonts = table.fonts
        if crop_votes:
            out.trim_crop_box = max(crop_votes, key=crop_votes.get)
        doc.close()
        return out
