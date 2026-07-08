# Forked from idml2epub src/idml2epub/fonts.py @ 7eb7eac (adapted: the IDML package
# fonts_keep/fonts_dir driver was dropped; the subset/collection helpers and the
# embed loop are exposed as reusable functions the pdf2epub fonts stage composes)
"""Font embedding core (JP-P7): OFL-only, always from system font files.

Fonts are NEVER extracted from the source PDF (embedded subsets, unclear
licenses). Every embedded face is subset to the codepoints actually used.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# fontTools stamps head.modified at save time; pin it for reproducible builds
os.environ.setdefault("SOURCE_DATE_EPOCH", "1767225600")  # 2026-01-01T00:00:00Z

from fontTools import subset
from fontTools.ttLib import TTCollection, TTFont

from .model import Paragraph, TextRun


@dataclass(slots=True)
class EmbeddedFont:
    family: str
    style: str  # normal | italic
    file_name: str  # inside OEBPS/font/
    path: Path
    media_type: str
    script: str  # latin | cjk
    lang: str | None = None


def collect_codepoints(flow) -> dict[str, set[str]]:
    """Buckets of characters: latin-regular, latin-italic, and per-lang."""
    buckets: dict[str, set[str]] = {"latin": set(), "latin-italic": set()}

    def eat(p: Paragraph):
        for it in p.items:
            if not isinstance(it, TextRun):
                continue
            if it.fmt.lang:
                buckets.setdefault(it.fmt.lang, set()).update(it.text)
            elif it.fmt.italic:
                buckets["latin-italic"].update(it.text)
            else:
                buckets["latin"].update(it.text)

    for b in flow.blocks:
        if isinstance(b, Paragraph):
            eat(b)
    for note in flow.notes.values():
        for p in note.paragraphs:
            eat(p)
    # headings/notes labels etc. always need basic latin + digits
    basics = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                 " .,;:!?'\"()[]-–—‘’“”…↩ ")
    buckets["latin"] |= basics
    buckets["latin-italic"] |= basics
    return buckets


def subset_font(font: TTFont, chars: set[str], out_path: Path) -> None:
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.recalc_bounds = True
    subsetter = subset.Subsetter(options=opts)
    subsetter.populate(text="".join(sorted(chars)))
    subsetter.subset(font)
    font.save(out_path)


def from_collection(ttc_path: Path, family: str) -> TTFont:
    """Extract one face from a .ttc collection by family or full name."""
    coll = TTCollection(str(ttc_path), lazy=True)
    for i, font in enumerate(coll.fonts):
        name = font["name"].getDebugName(1) or ""
        full = font["name"].getDebugName(4) or ""
        if family.lower() in (name.lower(), full.lower()):
            return TTCollection(str(ttc_path), lazy=False).fonts[i]
    raise ValueError(f"family {family!r} not found in {ttc_path}")


def safe_name(family: str, style: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "", family)
    return f"{base}{'-Italic' if style == 'italic' else ''}.otf"


def embed_face(family: str, file: Path, chars: set[str], out_dir: Path, *,
               style: str = "normal", script: str = "latin", lang: str | None = None,
               do_subset: bool = True) -> EmbeddedFont:
    """Load a system font file (.ttf/.otf/.ttc), subset it to ``chars``, and
    write it into the packaging tree. Returns the EmbeddedFont record."""
    file = Path(file)
    font = (from_collection(file, family)
            if file.suffix.lower() == ".ttc" else TTFont(str(file), lazy=False))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = safe_name(family, style)
    out_path = out_dir / out_name
    if do_subset:
        subset_font(font, chars, out_path)
    else:
        font.save(out_path)
    return EmbeddedFont(family, style, out_name, out_path,
                        "application/vnd.ms-opentype", script, lang)
