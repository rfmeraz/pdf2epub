"""Deterministic, counted text repairs — shared by flow and QA ground truth.

The pipeline never rewrites the book's words: every transform here is a
mechanical repair of a known extraction defect, applied identically to the
flow text and to the QA ground-truth text so the coverage gate measures the
conversion, not the fixer. Every change is counted; totals surface as
warnings.
"""

from __future__ import annotations

import re

# Alphabetic Presentation Forms: poppler/old ToUnicode maps emit single
# ligature codepoints that readers' fonts may lack
_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
_LIG_RE = re.compile("[" + "".join(_LIGATURES) + "]")

# lost spaces (Me and Rumi, Creo prepress, no ToUnicode):
#   say,"If  /  Erzincan.They  /  word”We
# lowercase-before guard keeps initials ("W.M.") and "op.cit." untouched
_SPACE_AFTER_PUNCT = re.compile(r'([a-z][.!?,;:])(["“”’]?[A-Z“"])')
_SPACE_AFTER_QUOTE = re.compile(r'([a-z][”"])([A-Z])')


def expand_ligatures(text: str) -> tuple[str, int]:
    n = len(_LIG_RE.findall(text))
    if n:
        text = _LIG_RE.sub(lambda m: _LIGATURES[m.group(0)], text)
    return text, n


def restore_spaces(text: str) -> tuple[str, int]:
    text, n1 = _SPACE_AFTER_PUNCT.subn(r"\1 \2", text)
    text, n2 = _SPACE_AFTER_QUOTE.subn(r"\1 \2", text)
    return text, n1 + n2


# a broken subset ToUnicode CMap shifted by -0x1D (Islam and Buddhism 2010,
# essay section: 'WKH'='the', '\x03'=space, '\x14\x14\x1b'='118'). Shifted
# runs are detectable: real text never contains these control codes.
_SHIFT_MARKERS = set("\x01\x02\x03\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17"
                     "\x18\x19\x1a\x1b\x1c\x1d")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def is_shifted_run(text: str) -> bool:
    return any(c in _SHIFT_MARKERS for c in text)


def repair_shifted_cmap(text: str, highmap: dict[str, str]) -> tuple[str, int]:
    """Undo the -0x1D CMap shift on a detected run: chars below 0x60 shift
    up by 0x1D; non-ASCII garbage maps via the per-book verified highmap;
    unknown high chars survive (counted by the caller via ctrl-strip/QA)."""
    out = []
    unknown = 0
    for ch in text:
        o = ord(ch)
        if ch in highmap:
            out.append(highmap[ch])
        elif 0x03 <= o < 0x60:
            out.append(chr(o + 0x1D))
        elif o < 0x03:
            unknown += 1
        else:
            out.append(ch)
    t = "".join(out)
    # the shifted section's original line-end hyphens arrive as 'word- word'
    # inside one run; poppler's newline form self-heals in normalize, so the
    # candidate must apply the same lower-only rejoin
    t = re.sub(r"([A-Za-zÀ-ſ])- ([a-zà-ÿ])", r"\1\2", t)
    return t, unknown


def strip_control_chars(text: str) -> tuple[str, int]:
    """XML validity is non-negotiable: C0 controls (minus tab/newline) out."""
    n = len(_CTRL_RE.findall(text))
    return (_CTRL_RE.sub("", text), n) if n else (text, 0)


def dehyphenate_join(prev: str, nxt: str, mode: str = "lower-only") -> tuple[str, str, bool]:
    """Decide the junction when ``nxt`` continues ``prev`` across a line break.

    Returns (prev_out, separator, dehyphenated). lower-only: strip the
    line-end hyphen iff the continuation starts lowercase ('tradi-/tion' ->
    'tradition'); a capital keeps it ('Kaccāyanagotta-/Sutta') — both cases
    join WITHOUT a space. Extraction spans carry trailing whitespace
    ('com- '), so the hyphen test runs on the stripped tail."""
    base = prev.rstrip()
    if mode != "off" and re.search(r"[A-Za-zÀ-ſ]-$", base):
        if nxt.lstrip()[:1].islower():
            return base[:-1], "", True
        return base, "", False
    return prev, " ", False
