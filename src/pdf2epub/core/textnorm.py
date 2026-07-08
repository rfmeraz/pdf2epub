# Forked from idml2epub src/idml2epub/textnorm.py @ 7eb7eac
"""Text normalization shared by the page-anchor aligner and the QA text diff.

Both sides of every comparison (IDML flow text vs pdftotext output) must pass
through the same normalizer, otherwise coverage numbers measure the
normalizer, not the conversion.
"""

from __future__ import annotations

import re
import unicodedata

_QUOTE_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "­": "",  # soft hyphen
        "﻿": "",
        " ": " ",
        " ": " ",
        " ": " ",
        "　": " ",  # ideographic space
        "\t": " ",
    }
)

_WS = re.compile(r"\s+")
# a hyphen at end-of-line continuing onto the next line (PDF extraction)
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")


def normalize(text: str) -> str:
    """Canonical form used for all text alignment and coverage checks."""
    text = unicodedata.normalize("NFC", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = text.translate(_QUOTE_MAP)
    text = _WS.sub(" ", text)
    return text.strip()


_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
_ARABIC_RE = re.compile(r"^\d{1,4}$")


def is_folio_line(line: str) -> bool:
    """True if a line is nothing but a printed page number."""
    s = line.strip()
    return bool(s) and (bool(_ARABIC_RE.match(s)) or bool(_ROMAN_RE.match(s)))


def strip_page_furniture(page_text: str, furniture: set[str]) -> str:
    """Remove running heads and folio lines from one page of pdftotext output.

    ``furniture`` holds normalized head/foot strings. Furniture is only
    stripped from the *leading* lines of the page (a mid-page quotation may
    legitimately repeat a heading); folio-only lines are stripped anywhere.
    """
    kept: list[str] = []
    leading = True
    for line in page_text.splitlines():
        norm = normalize(line)
        if not norm:
            continue
        if is_folio_line(line):
            continue
        if leading and norm in furniture:
            continue
        leading = False
        kept.append(line)
    return "\n".join(kept)


def int_to_roman(n: int, lower: bool = True) -> str:
    vals = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    out = []
    for v, sym in vals:
        while n >= v:
            out.append(sym)
            n -= v
    s = "".join(out)
    return s.lower() if lower else s
