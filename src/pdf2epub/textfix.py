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
# the optional-quote class holds OPENING marks only: a CLOSING ” after
# punctuation must get its space AFTER the quote (the dedicated
# _SPACE_CLOSEQ/_QUOTE_SPACE_SWAP patterns own that seam) — with ” in this
# class the repair inserted 'believer. ”The', manufacturing the wrong-side
# shape it took the 2026-07-10 proofread pass to hunt down
_SPACE_AFTER_PUNCT = re.compile(r'([a-z][.!?,;:])(["“’]?[A-Z“"])')
_SPACE_AFTER_QUOTE = re.compile(r'([a-z][”"])([A-Z])')
# the lowercase-before guard has one safe relaxation: bracket/paren/digit +
# comma/period + DOUBLE QUOTE + capital ('[about me],"This' / '(216),"We' /
# '86:9,"On' — gate-11 residuals) is never legitimate prose; the mandatory
# quote is what keeps initials and numerics out
_SPACE_AFTER_BRACKET = re.compile(r'([\])0-9][.,])(["“”][A-Z“"])')
# 2026-07-10 (M&R proofread pass): the comma+LOWERCASE class deferred on
# 2026-07-09 is now print-verified (38 blind readers; pp.50/60/77 renders —
# the print has every space, Creo prepress lost them), together with five
# sibling classes from the same prepress failure. All are impossible in
# legitimately-set English; transliteration apostrophes (Sana'i, wa'llah)
# make any U+2019-followed-by-lowercase pattern UNSAFE — those few seams
# stay unrepaired by doctrine.
_SPACE_COMMA_LOWER = re.compile(r"([a-z],)([a-z])")
_SPACE_PUNCT_OPENQ = re.compile(r"([a-zA-Z0-9\])][.!?,;:])([‘“])")
_SPACE_CLOSEQ = re.compile(r"(”)([A-Za-z])")
_SPACE_AFTER_CITE = re.compile(r"([\])][.,;:])([A-Za-z])")
_SPACE_BEFORE_PAREN = re.compile(r"([.!?”’])(\(\d)")
_SPACE_AFTER_STAR = re.compile(r"([.!?]\*)([A-Za-z])")
_SPACE_NUM_DOT_CAP = re.compile(r"([0-9A-Z]\.)([A-Z][a-z])")
# the single-capital variant: a note marker abutting O/A/I ('84.O you',
# '38.I\u2019ve never') — the capital must be a standalone word (space or
# apostrophe follows), so initials ('R.A.') and citations never match
_SPACE_NUM_DOT_ONECAP = re.compile("([0-9]\\.)([A-Z](?=[\\s\u2019]))")
# a semicolon directly followed by a letter is never legitimate typography;
# the lowercase-before guard of _SPACE_AFTER_PUNCT missed the digit/bracket
# contexts ('2218-51;Attar', '[20:5];His') and lowercase continuations
# ('manyness;it') — print-verified spaced (M&R pp.174/229)
_SPACE_AFTER_SEMI = re.compile(r"(;)([A-Za-z])")
# digit + comma + capital ('2.41,Shams is referring'): thousands separators
# are digit-digit and never match
_SPACE_NUM_COMMA_CAP = re.compile(r"([0-9],)([A-Z])")
# digit + comma + FOUR digits ('October 11,1244'): a thousands separator
# groups exactly three, so a four-digit year after the comma is a seam
_SPACE_NUM_COMMA_YEAR = re.compile(r"([0-9],)([0-9]{4}(?![0-9]))")
# closing quote + period + capital ('\u2026inheritor. . .\u201d.The word')
_SPACE_CLOSEQ_DOT = re.compile("(\u201d\\.)([A-Z])")
_SPACE_STAR_LETTER = re.compile(r"(\*)([A-Za-z])")
# display-type ampersands lose their surrounding spaces in extraction
# ('Me &Rumi', 'Me&Rumi' on the M&R title pages); the lowercase-before
# guard keeps 'AT&T'-style tight caps untouched
_SPACE_AMP_LEFT = re.compile(r"([a-z])(&(?=[A-Z]))")
_SPACE_AMP_RIGHT = re.compile(r"((?<=[a-z ])&)([A-Z])")
# the space landed on the WRONG SIDE of a closing quote ('way. ”Then' for
# 'way.” Then'); ‘/’ are directional in this corpus and a space before a
# CLOSING quote is never legitimate, so the swap is deterministic
_QUOTE_SPACE_SWAP = re.compile(r"([.!?,;:]) ([”’])")

# named so the per-rule tally (flow counts `space-rule-<name>`, corpus
# telemetry) can report WHICH rule fired where across the corpus — the
# "probe all configs" evidence for every new rule, mechanized
_INSERT_PATTERNS = (
    ("after-punct", _SPACE_AFTER_PUNCT),
    ("after-quote", _SPACE_AFTER_QUOTE),
    ("after-bracket", _SPACE_AFTER_BRACKET),
    ("comma-lower", _SPACE_COMMA_LOWER),
    ("punct-openq", _SPACE_PUNCT_OPENQ),
    ("closeq", _SPACE_CLOSEQ),
    ("after-cite", _SPACE_AFTER_CITE),
    ("before-paren", _SPACE_BEFORE_PAREN),
    ("after-star", _SPACE_AFTER_STAR),
    ("num-dot-cap", _SPACE_NUM_DOT_CAP),
    ("num-dot-onecap", _SPACE_NUM_DOT_ONECAP),
    ("after-semi", _SPACE_AFTER_SEMI),
    ("num-comma-cap", _SPACE_NUM_COMMA_CAP),
    ("num-comma-year", _SPACE_NUM_COMMA_YEAR),
    ("closeq-dot", _SPACE_CLOSEQ_DOT),
    ("star-letter", _SPACE_STAR_LETTER),
    ("amp-left", _SPACE_AMP_LEFT),
    ("amp-right", _SPACE_AMP_RIGHT),
)

_TALLY_PREFIX = "space-rule-"


def _tally(tally: dict | None, name: str, k: int) -> None:
    if tally is not None and k:
        key = _TALLY_PREFIX + name
        tally[key] = tally.get(key, 0) + k


def expand_ligatures(text: str) -> tuple[str, int]:
    n = len(_LIG_RE.findall(text))
    if n:
        text = _LIG_RE.sub(lambda m: _LIGATURES[m.group(0)], text)
    return text, n


_INRUN_HYPHEN = re.compile(r"([A-Za-zÀ-ſ])- ([a-zà-ÿ])")


def inline_dehyphenate(text: str, mode: str = "lower-only",
                       keep: "frozenset[str] | set[str]" = frozenset()
                       ) -> tuple[str, int]:
    """Some PDFs store a whole paragraph as ONE content line, with the print
    line-breaks appearing as literal 'word- word' seams (I&B introduction and
    essay). Same lower-only doctrine as the line joiner, applied in-run —
    including its per-book keep-list, matched on the same reconstructed
    'lastword-nextword'.

    NB text alone cannot tell a stored line break from a PRINTED space of the
    same shape: sufism p.125 really does set '(al- Bātin)', while Keys stores
    'non- Buddhist' for a page that prints 'non-Buddhist'. Only the glyph
    geometry separates them, so the extractor drops the layout-CANCELLED ones
    before this ever runs (extract.mupdf.repair_span_text) — leaving here only
    seams whose space the layout really gave room to. Keep this rule narrow
    for that reason: a capitalized continuation is left alone, since the only
    such seam in the corpus is one print genuinely sets."""
    if mode == "off" or not keep:
        return _INRUN_HYPHEN.subn(r"\1\2", text)
    out: list[str] = []
    n = 0
    pos = 0
    for m in _INRUN_HYPHEN.finditer(text):
        left = re.search(r"[A-Za-zÀ-ſ’']*$", text[:m.end(1)]).group(0)
        right = re.match(r"[A-Za-zÀ-ſ’']*", text[m.start(2):]).group(0)
        out.append(text[pos:m.start()])
        if f"{left}-{right}".lower() in keep:
            out.append(f"{m.group(1)}-{m.group(2)}")
        else:
            out.append(m.group(1) + m.group(2))
            n += 1
        pos = m.end()
    out.append(text[pos:])
    return "".join(out), n


def swap_quote_sides(text: str) -> tuple[str, int]:
    """Move a space from before a closing quote to after it ('sun. ”The' ->
    'sun.” The'). Print puts the closing quote at the START of the next line
    often enough that the seam only EXISTS after the line join inserts its
    separator — so the flow re-applies this at close_para, when the joined
    text is final; per-line textfix runs too early to see it."""
    return _QUOTE_SPACE_SWAP.subn(r"\1\2 ", text)


def restore_spaces(text: str, tally: dict | None = None) -> tuple[str, int]:
    # the swap runs FIRST so 'way. ”Then' reads 'way.” Then' before the
    # insert patterns examine the seam
    text, n = _QUOTE_SPACE_SWAP.subn(r"\1\2 ", text)
    _tally(tally, "quote-swap", n)
    for name, pat in _INSERT_PATTERNS:
        text, k = pat.subn(r"\1 \2", text)
        n += k
        _tally(tally, name, k)
    return text, n


def restore_space_seam(prev: str, nxt: str,
                       tally: dict | None = None) -> tuple[str, str, int]:
    """Repair a lost space that straddles a run boundary. restore_spaces runs
    per run, so a fusion at a roman/italic seam ('believer.' + 'This', MR
    prepress) is invisible to it. Same patterns, applied to a 3+3-char window
    across the seam; only a match that straddles the boundary acts (fusions
    wholly inside one run are the per-run pass's job). The space lands at the
    pattern's split point — usually the tail of ``prev``, preserving run
    formatting. Returns (prev, nxt, insertions)."""
    # the wrong-side-of-quote swap straddles run seams too (the closing
    # quote usually opens a new run): 'copper. '+'”He', 'copper.'+' ”He',
    # 'copper. '+' ”He' (both-sided spaces would otherwise survive restore
    # and be fused into the residual '. ”' by the collapse pass), and
    # 'copper. ”'+'He'
    p_r = prev.rstrip(" ")
    n_l = nxt.lstrip(" ")
    if p_r[-1:] in ".!?,;:" and n_l[:1] in "”’" and \
            (len(p_r) != len(prev) or len(n_l) != len(nxt)):
        _tally(tally, "seam-quote", 1)
        return p_r, n_l[0] + " " + n_l[1:].lstrip(" "), 1
    if len(prev) >= 3 and prev[-1] in "”’" and prev[-2] == " " \
            and prev[-3] in ".!?,;:":
        _tally(tally, "seam-quote", 1)
        return prev[:-2] + prev[-1], " " + nxt.lstrip(" "), 1
    tail = prev[-3:]
    window = tail + nxt[:3]
    seam = len(tail)
    for name, pat in _INSERT_PATTERNS:
        for m in pat.finditer(window):
            if m.start() < seam < m.end():
                _tally(tally, "seam-" + name, 1)
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
    # MIXED-encoding runs: some glyphs inside a detected-shifted run are
    # already correct ASCII, and the uniform shift corrupts them. A real
    # 0x20 space becomes '=' (a char this corpus never prints) and a real
    # line-end hyphen becomes 'J' ('conseJ quential' — capital J between a
    # lowercase letter and a spaced lowercase word is impossible English,
    # while the genuine shifted J of 'al-Jūzjānī' is followed by letters).
    # Both damage shapes are deterministic; blind readers found ten 'J '
    # words and dozens of '=' seams in the SHIPPED artifact.
    t = re.sub(r"([a-zà-ÿ])J ([a-zà-ÿ])", r"\1\2", t)
    # a trailing 0x2D at the run END is always a real line-end hyphen (the
    # join dehyphenates it); as shifted 'J' it strands 'conJ stantly'
    # across the line seam — eight such words shipped
    if text.rstrip().endswith("-") and t.rstrip().endswith("J"):
        r = t.rstrip()
        t = r[:-1] + "-"
    if "=" in t:
        t = re.sub(r" ?= ?", " ", t)
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


# GREEK CAPITAL LETTER ALPHA WITH MACRON standing in for Latin Ā inside a
# transliteration (BoK p.184 'ʿᾹmir' — the PDF's own ToUnicode maps a visually
# identical wrong-script codepoint; search and screen readers break). Repair
# only before a Latin lowercase so genuine Greek text keeps its Greek
# neighbours.
_WRONGSCRIPT_ALPHA = re.compile("Ᾱ(?=[a-z])")


def repair_wrong_script(text: str) -> tuple[str, int]:
    """Fix visually-identical wrong-script lookalikes the PDF's ToUnicode
    emitted (Greek Ᾱ for Latin Ā). Shared by the flow and the QA ground truth
    so coverage compares repaired-vs-repaired text, never repaired-vs-raw (a
    flow-only repair makes the witness carry a char the candidate 'lost')."""
    return _WRONGSCRIPT_ALPHA.subn("Ā", text)


# a lone ASCII grave accent (U+0060) NOT followed by a letter is a ToUnicode
# artifact in this prose corpus ('Subjectivity itself`.' — F&S p.49, invisible
# in the render). A grave FOLLOWED by a letter is a transliteration ʿayn
# stand-in (M&R 'a`a', ' `Ali', 27 of them) and MUST be preserved — the
# lookahead draws exactly that line. Shared flow/ground-truth like the above.
_STRAY_GRAVE = re.compile(r"`(?![^\W\d_])")


def strip_stray_grave(text: str) -> tuple[str, int]:
    """Drop a stray grave accent that abuts punctuation/space/end; keep ʿayn."""
    return _STRAY_GRAVE.subn("", text)


# standalone words that form permanently hyphenated compounds: a line-end
# 'self-' + lowercase continuation is 'self-evident', never 'selfevident'
# (proofread-confirmed casualties: selfevident, allembracing, selfdiscipline,
# twentytwo, 'low lying'). The word-boundary guard keeps 'follow-'/'himself-'
# out. Deliberately short — 'thought-', 'pre-', 'non-', 'love-' also END or
# START ordinary words (thought-ful, love-ly) and need a lexicon to decide.
_KEEP_HYPHEN_PREFIX = re.compile(
    r"(?:^|[^A-Za-zÀ-ſ])(?:self|all|half|well|ill|cross|low|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety|seven|just|"
    r"wa\u2019l|wa\u2019t)-$", re.I)
# the Arabic ARTICLE keeps its hyphen at a line break ('Q\u016bt al-/qul\u016bb',
# 'Mirsad al-/ibad' — 13 of 14 corpus sites), but English syllable breaks
# of 'allows'/'although'/'alchemy' must still dehyphenate ('teaching
# al-/lows', I&B p.157). The discriminator is the word BEFORE the article:
# Arabic titles put a capitalized or diacritical word there; plain
# lowercase English never does.
_ARABIC_ARTICLE = re.compile(
    "(\\S+)\\s+al-$")


def dehyphenate_join(prev: str, nxt: str, mode: str = "lower-only",
                     keep: "frozenset[str] | set[str]" = frozenset()) -> tuple[str, str, bool]:
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
        # a compound CHAIN keeps its hyphen — but only closed-set
        # CONNECTORS mark one: continuation starting 'and-'/'to-'/'by-'
        # ('so-/and-so', 'such-/and-such') or a fragment whose tail after
        # its last hyphen is such a connector ('face-to-/face'). A bare
        # interior hyphen is NOT enough: ordinary breaks of hyphenated
        # compounds ('know-noth-/ing', 'bro-/ken-head', 'One-col-/ored')
        # must still dehyphenate (round-2 proofread findings).
        last_word = re.split(r"[^A-Za-zÀ-ſ\-’']", base[:-1])[-1]
        next_word = re.split(r"[^A-Za-zÀ-ſ\-’']", nxt.lstrip(), maxsplit=1)[0]
        _conn = ("and", "to", "by", "the", "in", "of")
        chain = (next_word.split("-", 1)[0] in _conn and "-" in next_word) \
            or ("-" in last_word and last_word.rsplit("-", 1)[1] in _conn)
        art = _ARABIC_ARTICLE.search(base)
        arabic_article = art is not None and (
            art.group(1)[:1].isupper()
            or any(ord(c) > 0x7f for c in art.group(1))
            # the conjunction 'wa' before the article is Arabic context too
            # ('Kitāb al-milal wa al-/nihal', I&B bibliography)
            or art.group(1).lower() in ("wa", "wal"))
        # a per-book render-verified keep-list preserves a real compound whose
        # hyphen happens to fall at a line break ('religion-/quintessence' —
        # lower-only would strip it, but print keeps it); matched on the
        # reconstructed 'lastword-nextword', case-insensitive
        if keep and f"{last_word}-{next_word}".lower() in keep:
            return base, "", False
        if nxt.lstrip()[:1].islower() and not chain \
                and not arabic_article \
                and not _KEEP_HYPHEN_PREFIX.search(base):
            return base[:-1], "", True
        return base, "", False
    # a NUMBER RANGE broken at its own hyphen ('pp. 8-' + '18', 'Luria (1534-'
    # + '72)', an index locator '119-' + '120'): the hyphen belongs to the
    # range, so the join must CLOSE it — the letter-hyphen rule above never
    # sees these, and the default join spaced them ('pp. 8- 18'). PWC's blind
    # readers found ~20 in its index and acknowledgments alone.
    # BOTH sides must be digits: sufism's columned index puts a NEW entry on
    # the next line ('92, 162, 166-' + 'ʿabd, 86'), which must not close.
    if mode != "off" and re.search(r"\d-$", base) \
            and nxt.lstrip()[:1].isdigit():
        return base, "", False
    # a URL or slash-compound broken at the line end joins WITHOUT a space
    # ('www.' + 'acommonword.com'; 'Dhamma/' + 'Nirvana/Shunya' — a slash
    # never ends a line before a spaced word in this corpus)
    if mode != "off" and (base.endswith("www.") or base.endswith("/")):
        return base, "", False
    # a CLOSED em/en-dash at the line end abuts its neighbours ('object—or',
    # '26–28'); the break must NOT inject a space ('object— or', a false
    # 'word- word' after normalize). The dash frequently arrives as its OWN
    # run (an italic word then a roman em-dash: '<i>Vajrayâna</i>—'), so the
    # base is a bare '—' with the letter one run back; a closing quote can
    # also precede it ('salvation”—in'). Fire on ANY dash not immediately
    # preceded by a space — that guard still leaves spaced dashes
    # ('word —\nword', base ' —') alone.
    if mode != "off" and re.search(r"(?<!\s)[—–]$", base):
        return base, "", False
    # CJK sets no inter-word spaces: a Chinese title wrapping across a print
    # line rejoins CLOSED ('天方至/圣实录' -> 天方至圣实录, not 天方至 圣实录 —
    # ~25 HU foreword seams reader-flagged), as does a CJK char meeting a
    # bracket at the seam ('([' + '天方…', '一斋' + ')'). Latin↔CJK seams keep
    # their space.
    if mode != "off" and base:
        nx = nxt.lstrip()[:1]
        if nx and _cjk_seam(base[-1], nx):
            return base, "", False
    return prev, " ", False


def _is_cjk(c: str) -> bool:
    o = ord(c)
    return (0x3000 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF
            or 0xFF00 <= o <= 0xFFEF)


def _cjk_seam(a: str, b: str) -> bool:
    ca, cb = _is_cjk(a), _is_cjk(b)
    if ca and cb:
        return True
    if ca and b in ")]":
        return True
    if a in "([" and cb:
        return True
    return False
