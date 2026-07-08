"""Extraction-engine seam: extract() talks to this protocol only.

The shipped engine is PyMuPDF ("mupdf"). A poppler pdftohtml-XML engine was
verified viable during design and is documented in NOTES.md as the fallback
spec — swap engines here without touching analyze/flow/emit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..pdfmodel import PdfDoc


class ExtractionEngine(Protocol):
    name: str

    def read(self, pdf: Path) -> PdfDoc: ...


def get_engine(name: str = "mupdf") -> ExtractionEngine:
    if name == "mupdf":
        from .mupdf import MuPdfEngine

        return MuPdfEngine()
    raise ValueError(f"unknown extraction engine: {name}")
