# Forked from idml2epub src/idml2epub/model.py @ 7eb7eac
"""Intermediate representation shared by all pipeline stages.

Every type is a plain dataclass that round-trips through JSON via
``block_to_dict`` / ``block_from_dict`` so any stage can be dumped with
``--dump-ir`` and inspected or diffed as a file.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Union


@dataclass(slots=True)
class RunFormat:
    italic: bool = False
    bold: bool = False
    position: str = "normal"  # normal | superscript | subscript
    smallcaps: bool = False
    point_size: float | None = None
    applied_font: str | None = None
    char_style: str | None = None
    lang: str | None = None  # filled by mapping.lang, not the parser

    def key(self) -> tuple:
        return (
            self.italic,
            self.bold,
            self.position,
            self.smallcaps,
            self.point_size,
            self.applied_font,
            self.char_style,
            self.lang,
        )


PLAIN = RunFormat()


@dataclass(slots=True)
class TextRun:
    text: str
    fmt: RunFormat = field(default_factory=RunFormat)


@dataclass(slots=True)
class NoteRef:
    note_id: str


InlineItem = Union[TextRun, NoteRef]


@dataclass(slots=True)
class SourceRef:
    story_id: str
    psr_index: int


@dataclass(slots=True)
class Paragraph:
    style: str
    items: list[InlineItem]
    src: SourceRef
    # filled by mapping.styles:
    role: str | None = None
    classes: list[str] = field(default_factory=list)

    def text(self) -> str:
        return "".join(it.text for it in self.items if isinstance(it, TextRun))


@dataclass(slots=True)
class Note:
    note_id: str
    paragraphs: list[Paragraph]


@dataclass(slots=True)
class Figure:
    image_key: str  # dedupe key: "<basename>" or "<basename>#p<pdf_page>"
    source_basename: str
    pdf_page: int | None
    page_ordinal: int  # 1-based physical page index
    y_pt: float
    x_pt: float
    width_pt: float
    height_pt: float
    role: str = "figure"  # figure | decoration | chinese-page
    alt: str = ""


@dataclass(slots=True)
class PageAnchor:
    ordinal: int  # 1-based physical page index
    label: str  # printed folio: "i".."xxxiv", "1".."118"
    approximate: bool = False


Block = Union[Paragraph, Figure, PageAnchor]


@dataclass(slots=True)
class FlowDoc:
    blocks: list[Block]
    notes: dict[str, Note]
    style_usage: Counter
    # named HyperlinkTextDestination anchors -> index into blocks
    text_dests: dict[str, int]
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Chapter:
    chapter_id: str
    title: str
    level: int
    blocks: list[Block]


# ---------------------------------------------------------------------------
# JSON (de)serialization

_BLOCK_TYPES = {
    "Paragraph": Paragraph,
    "Figure": Figure,
    "PageAnchor": PageAnchor,
}


def block_to_dict(block: Block) -> dict:
    d = asdict(block)
    d["_type"] = type(block).__name__
    return d


def _paragraph_from_dict(d: dict) -> Paragraph:
    items: list[InlineItem] = []
    for it in d["items"]:
        if "note_id" in it:
            items.append(NoteRef(note_id=it["note_id"]))
        else:
            items.append(TextRun(text=it["text"], fmt=RunFormat(**it["fmt"])))
    return Paragraph(
        style=d["style"],
        items=items,
        src=SourceRef(**d["src"]),
        role=d.get("role"),
        classes=d.get("classes", []),
    )


def block_from_dict(d: dict) -> Block:
    t = d.pop("_type")
    if t == "Paragraph":
        return _paragraph_from_dict(d)
    cls = _BLOCK_TYPES[t]
    return cls(**d)


def flowdoc_to_dict(doc: FlowDoc) -> dict:
    return {
        "blocks": [block_to_dict(b) for b in doc.blocks],
        "notes": {
            nid: [block_to_dict(p) for p in note.paragraphs] for nid, note in doc.notes.items()
        },
        "style_usage": dict(doc.style_usage),
        "text_dests": doc.text_dests,
        "warnings": doc.warnings,
    }


def flowdoc_from_dict(d: dict) -> FlowDoc:
    return FlowDoc(
        blocks=[block_from_dict(b) for b in d["blocks"]],
        notes={
            nid: Note(nid, [_paragraph_from_dict(p) for p in ps])
            for nid, ps in d["notes"].items()
        },
        style_usage=Counter(d["style_usage"]),
        text_dests=d["text_dests"],
        warnings=d.get("warnings", []),
    )
