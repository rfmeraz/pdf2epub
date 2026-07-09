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
# the lowercase-before guard has one safe relaxation: bracket/paren/digit +
# comma/period + DOUBLE QUOTE + capital ('[about me],"This' / '(216),"We' /
# '86:9,"On' — gate-11 residuals) is never legitimate prose; the mandatory
# quote is what keeps initials and numerics out
_SPACE_AFTER_BRACKET = re.compile(r'([\])0-9][.,])(["“”][A-Z“"])')


def expand_ligatures(text: str) -> tuple[str, int]:
    n = len(_LIG_RE.findall(text))
    if n:
        text = _LIG_RE.sub(lambda m: _LIGATURES[m.group(0)], text)
    return text, n


_INRUN_HYPHEN = re.compile(r"([A-Za-zÀ-ſ])- ([a-zà-ÿ])")


def inline_dehyphenate(text: str) -> tuple[str, int]:
    """Some PDFs store a whole paragraph as ONE content line, with the print
    line-breaks appearing as literal 'word- word' seams (I&B introduction and
    essay). Same lower-only doctrine as the line joiner, applied in-run."""
    return _INRUN_HYPHEN.subn(r"\1\2", text)


def restore_spaces(text: str) -> tuple[str, int]:
    text, n1 = _SPACE_AFTER_PUNCT.subn(r"\1 \2", text)
    text, n2 = _SPACE_AFTER_QUOTE.subn(r"\1 \2", text)
    text, n3 = _SPACE_AFTER_BRACKET.subn(r"\1 \2", text)
    return text, n1 + n2 + n3


def restore_space_seam(prev: str, nxt: str) -> tuple[str, str, int]:
    """Repair a lost space that straddles a run boundary. restore_spaces runs
    per run, so a fusion at a roman/italic seam ('believer.' + 'This', MR
    prepress) is invisible to it. Same patterns, applied to a 3+3-char window
    across the seam; only a match that straddles the boundary acts (fusions
    wholly inside one run are the per-run pass's job). The space lands at the
    pattern's split point — usually the tail of ``prev``, preserving run
    formatting. Returns (prev, nxt, insertions)."""
    tail = prev[-3:]
    window = tail + nxt[:3]
    seam = len(tail)
    for pat in (_SPACE_AFTER_PUNCT, _SPACE_AFTER_QUOTE, _SPACE_AFTER_BRACKET):
        for m in pat.finditer(window):
            if m.start() < seam < m.end():
                cut = m.end(1)
                if cut <= seam:
                    k = len(prev) - (seam - cut)
                    return prev[:k] + " " + prev[k:], nxt, 1
                k = cut - seam
                return prev, nxt[:k] + " " + nxt[k:], 1
    return prev, nxt, 0


# a broken subset ToUnicode CMap shifted by -0x1D (Islam and Buddhism 2010,
# essay section: 'WKH'='the', '\x03'=space, '\x14\x14\x1b'='118'). Shifted
# runs are detectable: real text never contains these control codes.
_SHIFT_MARKERS = set("\x01\x02\x03\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17"
                     "\x18\x19\x1a\x1b\x1c\x1d")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


_SHIFTED_WORD_RE = re.compile(r"[\x24-\x5f]{4,}")


def is_shifted_run(text: str, highmap: dict[str, str] | None = None) -> bool:
    if any(c in _SHIFT_MARKERS for c in text):
        return True
    # single-WORD shifted lines carry no \x03 space marker ('%LEOLRJUDSK\' =
    # 'Bibliography', an I&B heading that shipped garbled): detect by shape —
    # the whole line sits in the shifted-letter range and un-shifting yields
    # a real word (leading letter, lowercase tail). Real text can't do this:
    # true capitals shift to '`'-range junk, digits to capitals.
    t = text.strip()
    if _SHIFTED_WORD_RE.fullmatch(t):
        shifted = "".join(chr(ord(c) + 0x1D) for c in t)
        return bool(re.fullmatch(r"[A-Za-z][a-z]+", shifted))
    # highmap-aware word shape: 'VDED¶' (= 'sabaʾ', I&B p.140) mixes shifted
    # letters with verified-highmap diacritics, so the fullmatch above misses
    # it. Same precision bar: >=4 in-range chars whose un-shift alone is a
    # real word, every remaining char a highmap key, >=1 of them (otherwise
    # the branch above already decides).
    if highmap and t:
        in_range = [c for c in t if "\x24" <= c <= "\x5f"]
        hm_chars = [c for c in t if c in highmap and not "\x24" <= c <= "\x5f"]
        if len(in_range) >= 4 and hm_chars and \
                len(in_range) + len(hm_chars) == len(t):
            shifted = "".join(chr(ord(c) + 0x1D) for c in in_range)
            return bool(re.fullmatch(r"[A-Za-z][a-z]+", shifted))
    return False


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


def probe_text(text: str, shifted_cmap_repair: bool,
               highmap: dict[str, str]) -> str:
    """The text a furniture/folio SHAPE test should see. Furniture stripping
    runs ahead of the flow's per-run repair, so a shifted-CMap folio arrives
    as raw control bytes (I&B p.154 '129' -> '\\x14\\x15\\x1c') and never looks
    like digits — it leaks past the folio strip into the body as an unmapped
    pstyle. Repair a shifted run first so the shape test sees '129'; leave
    already-decoded text untouched."""
    if shifted_cmap_repair and is_shifted_run(text, highmap):
        return repair_shifted_cmap(text, highmap)[0]
    return text


def strip_control_chars(text: str) -> tuple[str, int]:
    """XML validity is non-negotiable: C0 controls (minus tab/newline) out."""
    n = len(_CTRL_RE.findall(text))
    return (_CTRL_RE.sub("", text), n) if n else (text, 0)


# standalone words that form permanently hyphenated compounds: a line-end
# 'self-' + lowercase continuation is 'self-evident', never 'selfevident'
# (proofread-confirmed casualties: selfevident, allembracing, selfdiscipline,
# twentytwo, 'low lying'). The word-boundary guard keeps 'follow-'/'himself-'
# out. Deliberately short — 'thought-', 'pre-', 'non-', 'love-' also END or
# START ordinary words (thought-ful, love-ly) and need a lexicon to decide.
_KEEP_HYPHEN_PREFIX = re.compile(
    r"(?:^|[^A-Za-zÀ-ſ])(?:self|all|half|well|ill|cross|low|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety)-$", re.I)


def dehyphenate_join(prev: str, nxt: str, mode: str = "lower-only") -> tuple[str, str, bool]:
    """Decide the junction when ``nxt`` continues ``prev`` across a line break.

    Returns (prev_out, separator, dehyphenated). lower-only: strip the
    line-end hyphen iff the continuation starts lowercase ('tradi-/tion' ->
    'tradition'); a capital keeps it ('Kaccāyanagotta-/Sutta'), as does a
    compound-forming prefix ('self-/evident' -> 'self-evident') — all cases
    join WITHOUT a space. Extraction spans carry trailing whitespace
    ('com- '), so the hyphen test runs on the stripped tail."""
    base = prev.rstrip()
    # a soft hyphen (U+00AD) is an EXPLICIT discretionary-break mark the
    # typesetter left at a line break ('eso­'/'terism'); drop it and join
    # closed whatever the continuation's case — never leave 'eso­ terism'.
    if mode != "off" and base.endswith("­"):
        return base[:-1], "", True
    if mode != "off" and re.search(r"[A-Za-zÀ-ſ]-$", base):
        if nxt.lstrip()[:1].islower() and not _KEEP_HYPHEN_PREFIX.search(base):
            return base[:-1], "", True
        return base, "", False
    # a CLOSED em/en-dash at the line end abuts its neighbours ('object—or',
    # '26–28'); the break must NOT inject a space ('object— or', a false
    # 'word- word' after normalize). The non-space-immediately-before guard
    # leaves spaced dashes ('word —\nword') alone — their base ends ' —'.
    if mode != "off" and re.search(r"[A-Za-zÀ-ſ0-9][—–]$", base):
        return base, "", False
    return prev, " ", False
