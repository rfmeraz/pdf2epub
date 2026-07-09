"""Pure-function QA checks unique to the PDF pipeline (gates 7-11)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ..core.textnorm import normalize

_SLUG_PATTERNS = [
    re.compile(r"\.indd\s"),
    re.compile(r"\d+/\d+/\d+\s+\d+:\d+\s*[AP]M"),
    re.compile(r"^Page [ivxlcdm\d]+$", re.I),
]
_HYPHEN_SPACE = re.compile(r"[A-Za-zÀ-ſ]- [a-z]")
_PUA = re.compile(r"[\ue000-\uf8ff]")
_LOST_SPACE = re.compile(r"[a-z][.!?][A-Z]|,\"[A-Z]|,”[A-Z]")


_GENERIC_SHORTHAND = {"foreword", "preface", "introduction", "index", "indexes",
                      "bibliography", "acknowledgments", "appendix"}


@dataclass(slots=True)
class TocAgreement:
    source_total: int = 0
    matched: int = 0
    missing: list[str] = field(default_factory=list)  # gates
    shorthand: list[str] = field(default_factory=list)  # informational
    nav_extra: int = 0  # informational: nav may be finer-grained

    @property
    def ok(self) -> bool:
        return not self.missing


def _fold(s: str) -> str:
    """Lowercase + strip diacritics + drop non-alphanumerics: PDF outlines
    are PDFDocEncoding and corrupt ʿayn/ḥāʾ to '?' ('Imam al-Shafi?i')."""
    import unicodedata

    s = unicodedata.normalize("NFD", normalize(s).lower())
    return re.sub(r"[^a-z0-9 ]+", "", "".join(c for c in s if not unicodedata.combining(c)))


def check_toc_agreement(nav_entries: list[tuple[int, str]],
                        source_entries: list[str],
                        nav_depth: int) -> TocAgreement:
    """Every chosen-source TOC title must appear in nav.xhtml within depth."""
    res = TocAgreement(source_total=len(source_entries))
    nav_texts = [_fold(t) for d, t in nav_entries if d <= nav_depth]
    all_nav = [_fold(t) for _, t in nav_entries]
    for title in source_entries:
        want = _fold(title)
        if any(fuzz.partial_ratio(want, t) >= 85 for t in nav_texts):
            res.matched += 1
        elif any(fuzz.partial_ratio(want, t) >= 85 for t in all_nav):
            res.matched += 1  # present, just deeper than nav_depth — tolerated
        elif want in _GENERIC_SHORTHAND:
            # print-navigation shorthand ('Foreword' for an essay that carries
            # its own title heading; 'Indexes' for excluded index apparatus) —
            # informational, not gating
            res.matched += 1
            res.shorthand.append(title)
        else:
            res.missing.append(title)
    res.nav_extra = max(0, len(nav_entries) - res.matched)
    return res


def check_furniture_leak(paragraph_texts: list[str],
                         furniture_templates: set[str],
                         book_title: str = "") -> list[str]:
    """Spine paragraphs that ARE furniture or printer slugs. Gates at zero.
    The book title is exempt: half-title/title pages legitimately repeat the
    exact text the running heads carry."""
    from ..analyze import furniture_template

    title_fold = _fold(book_title) if book_title else None
    leaks = []
    for t in paragraph_texts:
        ts = t.strip()
        if not ts or len(ts) > 120:
            continue
        if title_fold and _fold(ts) == title_fold:
            continue
        if furniture_template(ts) in furniture_templates:
            leaks.append(ts[:80])
            continue
        if any(p.search(ts) for p in _SLUG_PATTERNS):
            leaks.append(ts[:80])
    return leaks


def hyphen_residue(text: str) -> int:
    """'word- word' join artifacts. Gates at zero (legit compounds keep the
    hyphen with no space)."""
    return len(_HYPHEN_SPACE.findall(text))


def pua_residue(text: str) -> list[str]:
    """Private-use codepoints in shipped text. Gates at zero."""
    return sorted({f"U+{ord(c):04X}" for c in _PUA.findall(text)})


def lost_space_count(text: str) -> int:
    """Residual fused-word patterns after restore_spaces (gate 11 count)."""
    return len(lost_space_defects(text)[0])


def lost_space_defects(text: str, allow: list[str] = ()) \
        -> tuple[list[str], list[str]]:
    """Gate 11 (gating): fused-word patterns in shipped text with ±30-char
    context snippets. ``allow`` holds render-verified as-printed exceptions
    (qa.lost_space_allow, exact snippets); an entry matching nothing is
    STALE and reported — config rot is an error (flow.overrides doctrine)."""
    stale: list[str] = []
    for a in allow:
        if a in text:
            text = text.replace(a, " ")
        else:
            stale.append(f"stale qa.lost_space_allow entry (matched nothing): {a!r}")
    defects = [text[max(0, m.start() - 30):m.end() + 30]
               for m in _LOST_SPACE.finditer(text)]
    return defects, stale


_C0_AND_FFFD = "�\x00-\x08\x0b\x0c\x0e-\x1f"


def garble_residue(text: str, extra_chars: str = "") -> list[str]:
    """Gate 20 (gating): garble in SHIPPED text. U+FFFD and C0 controls are
    unconditional (the C0 set contains the shifted-CMap marker chars); the
    per-book ``extra_chars`` set (qa.garble_chars) covers configured
    shifted-CMap residue like ³´« — per-book because superscript-³ is
    legitimate elsewhere. Candidate-only by design: gate 2 normalizes both
    sides identically and cannot see corruption both witnesses share. One
    hit per garble RUN, labeled with codepoints and ±30-char context."""
    pat = re.compile("[" + _C0_AND_FFFD + re.escape(extra_chars) + "]+")
    hits = []
    for m in pat.finditer(text):
        chars = ",".join(sorted({f"U+{ord(c):04X}" for c in m.group()}))
        ctx = text[max(0, m.start() - 30):m.end() + 30].replace("\n", " ")
        hits.append(f"[{chars}] …{ctx}…")
    return hits


_SEAM_BAD = re.compile(r"[A-Za-z0-9]")
_XHTML_NS = "{http://www.w3.org/1999/xhtml}"


def noteref_seam_defects(docs) -> list[str]:
    """A letter/digit DIRECTLY after a noteref anchor is always a conversion
    artifact (a lost join separator or a fused paragraph): 'word.⁵Next'.
    Punctuation, quotes, and dashes legitimately follow markers ('…word⁵—',
    '…word⁵”.'). Must run BEFORE the runner strips noteref anchors."""
    out: list[str] = []
    for doc in docs:
        for a in doc.root.iter(f"{_XHTML_NS}a"):
            if "noteref" not in (a.get("class") or ""):
                continue
            tail = a.tail or ""
            if not tail or not _SEAM_BAD.match(tail[0]):
                continue
            prev = a.getprevious()
            parent = a.getparent()
            before = ((prev.tail if prev is not None else
                       (parent.text if parent is not None else "")) or "")
            marker = "".join(a.itertext()).strip()
            out.append(f"{doc.href}: …{before[-30:]}[{marker}]{tail[:40]}")
    return out


def parse_nav_toc(nav_root) -> list[tuple[int, str]]:
    """(depth, title) pairs from nav.xhtml's doc-toc, depth = ol nesting."""
    X = "{http://www.w3.org/1999/xhtml}"
    E = "{http://www.idpf.org/2007/ops}"
    out: list[tuple[int, str]] = []
    toc = None
    for nav in nav_root.iter(f"{X}nav"):
        if nav.get(f"{E}type") == "toc":
            toc = nav
            break
    if toc is None:
        return out

    def walk(ol, depth):
        for li in ol.findall(f"{X}li"):
            a = li.find(f"{X}a")
            if a is not None:
                out.append((depth, " ".join(a.itertext()).strip()))
            for sub in li.findall(f"{X}ol"):
                walk(sub, depth + 1)

    for ol in toc.findall(f"{X}ol"):
        walk(ol, 1)
    return out
