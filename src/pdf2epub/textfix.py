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
