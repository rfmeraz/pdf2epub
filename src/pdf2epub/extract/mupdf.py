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
import unicodedata
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


_DOT_BELOW = "̣"
_DOT_ABOVE = "̇"

# Alphabetic Presentation Forms: ligatures a font encodes as ONE glyph mapping
# to ONE char (textfix.expand_ligatures splits them into letters downstream)
_LIG_CHARS = frozenset("ﬀﬁﬂﬃﬄﬅﬆ")

# scripts written right-to-left (Hebrew, Arabic, Syriac, Thaana + presentation
# forms). Kept to the ranges this corpus can meet.
_RTL_RE = re.compile("[֐-׿؀-ۿ܀-ݏހ-޿"
                     "יִ-﷿ﹰ-﻿]")


def _is_rtl(c: str) -> bool:
    return bool(_RTL_RE.match(c))


def reorder_bidi_lines(pagedict: dict) -> int:
    """Repair the LOGICAL order of a line carrying an inline RTL run. Returns
    the number of glyphs moved.

    PWC sets four short Hebrew runs inside English prose ('Yod-He-Vav-He
    (יהוה), which form the supreme Divine Name' — p232 Glossary, p110, p112).
    The producer draws the RTL run right-to-left, then draws the punctuation
    that CLOSES it — ')', ',', ';', '.', the trailing space — as a separate
    jump back out to the right of the run. Those glyphs are therefore emitted
    BEFORE the Hebrew in the content stream while being drawn AFTER it, and the
    text layer reads 'Yod-He-Vav-He ( ,)יהוה' — the book's own words with their
    punctuation displaced.

    The RTL glyphs themselves need no help: the stream already holds them in
    logical order (verified against the Glossary's own gloss — 'Yod-He-Vav-He'
    = י-ה-ו-ה). Only the closing neutrals move, and the geometry says exactly
    which: they are the maximal run emitted immediately before the RTL glyphs
    yet drawn at or past the run's right edge. The opening '(' is drawn LEFT of
    the run and so never matches — it stays where print puts it.

    A whole-line visual sort would be the textbook transform and is WRONG here:
    MuPDF gives a ligature's continuation glyph a synthetic bbox that overlaps
    the next letter ('Th'+'e' -> T@77.40-88.11, h@88.11-93.45, e@88.07-92.32),
    so sorting by x reorders 'The' into 'Teh'. This moves only the neutrals it
    can prove displaced, and only on lines that carry RTL at all — the other
    seven books have ZERO RTL in their text layers (book-of-knowledge's Arabic
    is glyphs.pua_map substitution, applied at flow time), so they cannot reach
    this code.
    """
    n = 0
    for block in pagedict.get("blocks", []):
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("chars") is not None]
            if not spans:
                continue
            flat = [(si, ch) for si, s in enumerate(spans) for ch in s["chars"]]
            if not any(_is_rtl(ch["c"]) for _, ch in flat):
                continue
            out: list[int] = []
            i = 0
            moved_any = 0
            while i < len(flat):
                if not _is_rtl(flat[i][1]["c"]):
                    out.append(i)
                    i += 1
                    continue
                j = i
                while j < len(flat) and _is_rtl(flat[j][1]["c"]):
                    j += 1
                rtl_hi = max(flat[k][1]["bbox"][2] for k in range(i, j))
                moved: list[int] = []
                while out and flat[out[-1]][1]["bbox"][0] >= rtl_hi - 0.5:
                    moved.append(out.pop())
                out.extend(range(i, j))
                moved.sort(key=lambda k: flat[k][1]["bbox"][0])
                out.extend(moved)
                moved_any += len(moved)
                i = j
            if not moved_any:
                continue
            new_spans: list[dict] = []
            last_si: int | None = None
            for k in out:
                si, ch = flat[k]
                if si != last_si:
                    ns = dict(spans[si])
                    ns["chars"] = []
                    new_spans.append(ns)
                    last_si = si
                new_spans[-1]["chars"].append(ch)
            for ns in new_spans:
                ns["text"] = "".join(c["c"] for c in ns["chars"])
                bb = list(ns.get("bbox", (0.0, 0.0, 0.0, 0.0)))
                bb[0] = min(c["bbox"][0] for c in ns["chars"])
                bb[2] = max(c["bbox"][2] for c in ns["chars"])
                ns["bbox"] = tuple(bb)
            line["spans"] = new_spans
            n += moved_any
    return n


def repair_span_text(pagedict: dict) -> tuple[int, int, int]:
    """Rebuild each span's ``text`` from its GLYPHS, repairing four things only
    the glyph geometry can see. Returns (dots composed, cancelled spaces dropped,
    ligature pads + zero-advance spaces dropped).

    1. DOT diacritics the font encodes as a bare period.

    Keys sets its Arabic/Sanskrit emphatics (Ṣaḥīḥ, Ḥajjāj, Bṛhad-Āraṇyaka-
    Upaniṣad, saṃvṛti, Śaṅkarācārya) as base glyph + a separate dot glyph
    whose ToUnicode says U+002E. The text layer therefore reads 'S.ah.īh.'
    where the page plainly prints 'Ṣaḥīḥ' — the book's own words, garbled by
    its own encoding. Both engines read that same ToUnicode, so gate 2 sees
    two agreeing witnesses and gate 20 sees no U+FFFD: only a reader (six
    flagged it) or the render can catch this.

    The discriminator is geometric and exact: the dot is drawn off the text
    baseline and INSIDE the base letter's advance, where a real period sits ON
    the baseline after it. Measured over the whole corpus it fires 28 times in
    Keys (26 below, 2 above — all on the emphatic set) and NEVER on the other
    six books' thousands of periods.

    Which side the dot falls on is the PRINT's to say, not ours: 'Śaṅkarācārya'
    takes ṅ, and p.376's 'Muṡṭafā' takes a dot-above the standard would set
    below — both ship exactly as drawn (never rewrite the book's words).

    The repair is deterministic and additive: the base keeps its own glyph and
    gains U+0323/U+0307, then NFC folds the pair to the printed character.

    The dot's advance is narrower than the base it sits under, so MuPDF may
    emit a PHANTOM SPACE for the leftover gap ('H. ajjāj' — even the garbled
    reading splits the name). It is recognizable as the dot's own: it carries
    the dot's own off-baseline box and ends within the base letter's advance,
    where a word space sits on the text baseline clear of the letter.

    Scanning is per LINE, not per span: a raised dot is far enough off the
    baseline that MuPDF gives it a span of its own ('…Śan' | '.' | 'karācārya'),
    so a per-span walk never sees it beside its base. The mark is appended to
    the BASE's span, where NFC can fold it.

    2. A space the layout CANCELLED after a hyphen (see inline).

    3. A LIGATURE-PAD space.

    Pray Without Ceasing sets its Minion body with the Th/fi/fl/ff/ffi/ft
    ligatures, and each ligature glyph carries an advance far NARROWER than its
    own ink (the 'Th' of p.4 is drawn 10.71pt wide but advances only 5.34pt).
    The producer made up the deficit with a SPACE glyph, drawn back underneath
    the ligature's ink where it occupies no room of its own. MuPDF expands the
    ligature through its ToUnicode ('Th' -> 'T','h'), keeps the pad, and the
    text layer reads 'Th e Way', 'oft en', 'fi rst', 'affi  rmation' — the
    book's own words, split by its own encoding, on nearly every page (2572
    sites). Poppler reconstructs words from glyph gaps and never sees it, so
    gate 2 measures the flow against a witness that disagrees on 2779 words.

    The discriminator is geometric and exact: the pad is drawn ENTIRELY BEFORE
    the nearest preceding non-space glyph — impossible for a real word space,
    which always follows the ink it separates. Scanning back PAST earlier pads
    is what catches the second pad of a 3-char ligature ('ffi' pads twice), and
    the alphabetic guard on that preceding glyph is what keeps BoK's 1225
    kerned TOC dot leaders ('. . . .', drawn with the same backward geometry)
    untouched. Measured over the whole corpus it fires 2572 times here — every
    site reconstructing a real word (The, first, affirmation, left) — and NEVER
    once in the other seven books.

    A ligature the font encodes as ONE glyph mapping to ONE char (U+FB01 'ﬁ' —
    the index's WorldWisdomFont, 'Cruciﬁ ed') pads the same way but leaves no
    continuation glyph for the pad to hide behind, so it overlaps the
    ligature's own ink instead and the test above cannot see it. Six such words
    shipped broken through the INDEX, where gate 2 is blind (those pages are
    engine-disputed) — only the visual sheet caught them. Same doctrine: the
    pad is contained by the ligature it pads, where a real word space is drawn
    clear of it. Nine sites here, seven in sufism (all on its cover and its
    excluded back cover), zero in the other six books.

    4. A ZERO-ADVANCE space between two LETTERS.

    The same producer also drops a space with NO advance at all inside a word:
    the next letter is drawn at the space's own origin, so print shows one word
    where the text layer reads two ('invoca tion', 'qual ity', 'antici pation',
    'en dowed' — the p.91 render shows 'invocation'). Blind readers found these;
    no gate can, since both witnesses read the same stream.

    Test 2's shape, freed of its hyphen scope. That scope exists because a
    GENERAL phantom-space rule eats BoK's 1195 kerned post-period spaces — the
    LETTER/LETTER guard is what replaces it, and it holds because a kerned space
    still ADVANCES: measured across the corpus, every true phantom sits within
    0.005pt of zero advance while the tightest real space (M&R p.154 'seek You',
    the only letter/letter candidate outside this class) advances 0.427pt. The
    0.05pt tolerance sits in that gap. It fires 9 times here, 5 in Keys ('im
    plies', 'es sence' — shipped, and its blind readers missed them), once in
    I&B, and nowhere else.
    """
    n = 0
    n_sp = 0
    n_lig = 0
    n_zero = 0
    for block in pagedict.get("blocks", []):
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("chars") is not None]
            if not spans:
                continue
            # every repair below reasons in X: a rotated line (PWC's spine,
            # dir=(0,1)) advances in Y and gives every glyph the same x-box, so
            # the zero-advance test below reads its every space as a phantom
            # ('Th e Way of the Invocation' -> 'TheWayoftheInvocation')
            horizontal = abs(line.get("dir", (1.0, 0.0))[1]) < 0.01
            flat = [(si, ch) for si, s in enumerate(spans) for ch in s["chars"]]
            out: list[list[str]] = [[] for _ in spans]
            fixed: set[int] = set()
            i = 0
            while i < len(flat):
                si, ch = flat[i]
                pi, prev = flat[i - 1] if i else (None, None)
                dy = (ch["bbox"][1] - prev["bbox"][1]) if prev is not None else 0.0
                if ch["c"] == "." and prev is not None \
                        and prev["c"].isalpha() and abs(dy) > 1.0 \
                        and ch["bbox"][0] < prev["bbox"][2] - 0.2:
                    out[pi].append(_DOT_BELOW if dy > 0 else _DOT_ABOVE)
                    fixed.add(pi)
                    n += 1
                    i += 1
                    if i < len(flat):
                        _, nxt = flat[i]
                        if not nxt["c"].strip() \
                                and abs(nxt["bbox"][1] - ch["bbox"][1]) < 0.1 \
                                and nxt["bbox"][2] <= prev["bbox"][2] + 0.3:
                            i += 1   # the dot's own leftover advance
                    continue
                # a space the LAYOUT CANCELLED after a hyphen: the next glyph
                # is drawn at (or before) the space's own start, so it took no
                # room and print shows 'non-Buddhist' though the stream stores
                # 'non- Buddhist'. Keys does this at all 12 of its in-run
                # hyphen seams (cross-religious, self-contradictory, onto-
                # cosmological, Indo-European…) — the render is unambiguous.
                # The test is the space's OWN geometry, which is the only thing
                # that separates these from a printed space at the same shape:
                # sufism p.125 really does set '(al- Bātin)', and there the
                # next glyph clears the space. Scoped to the hyphen seam on
                # purpose — a general phantom-space rule would also eat BoK's
                # 1195 kerned post-period spaces.
                if ch["c"] == " " and prev is not None and prev["c"] == "-" \
                        and i + 1 < len(flat):
                    _, nxt = flat[i + 1]
                    if nxt["c"].isalpha() \
                            and nxt["bbox"][0] <= ch["bbox"][0] + 0.5:
                        n_sp += 1
                        i += 1
                        continue
                # a LIGATURE-PAD space (see 3. above), in either of the two
                # shapes this book's fonts produce. The scan back over earlier
                # pads reaches the ligature's own glyph for a 3-char ligature.
                if ch["c"] == " ":
                    j = i - 1
                    while j >= 0 and flat[j][1]["c"] == " ":
                        j -= 1
                    if j >= 0:
                        base = flat[j][1]
                        # (a) EXPANDED ligature ('Th' -> 'T','h'): the pad is
                        # drawn entirely BEHIND the synthetic continuation
                        # glyph MuPDF split out of it
                        if base["c"].isalpha() \
                                and ch["bbox"][2] <= base["bbox"][0] + 0.01:
                            n_lig += 1
                            i += 1
                            continue
                        # (b) PRESENTATION-FORM ligature (one glyph, one char:
                        # 'Cruciﬁ ed' in the index's WorldWisdomFont): there is
                        # no continuation glyph to hide behind, so the pad
                        # simply overlaps the ligature's OWN ink, and the next
                        # letter resumes at that ink's end. Guarding on the
                        # ligature char keeps this off ordinary kerned spaces —
                        # a real word space after a ligature is drawn CLEAR of
                        # it and fails the containment test.
                        if base["c"] in _LIG_CHARS \
                                and ch["bbox"][0] >= base["bbox"][0] - 0.5 \
                                and ch["bbox"][2] <= base["bbox"][2] + 0.5:
                            n_lig += 1
                            i += 1
                            continue
                # 4. a ZERO-ADVANCE space between two letters (see 4. above).
                if ch["c"] == " " and horizontal and prev is not None \
                        and prev["c"].isalpha() and i + 1 < len(flat):
                    _, nxt = flat[i + 1]
                    if nxt["c"].isalpha() \
                            and nxt["bbox"][0] <= ch["bbox"][0] + 0.05:
                        n_zero += 1
                        i += 1
                        continue
                out[si].append(ch["c"])
                i += 1
            for si, (span, chunk) in enumerate(zip(spans, out)):
                text = "".join(chunk)
                # NFC only where a mark was actually added — a blanket
                # normalize would silently RE-ENCODE every other book (BoK
                # stores its 'ḥ' pre-decomposed as h+U+0323 and has always
                # shipped it that way). Whether the corpus should ship NFC is
                # a separate decision, not this repair's to make.
                span["text"] = (unicodedata.normalize("NFC", text)
                                if si in fixed else text)
    return n, n_sp, n_lig + n_zero


def trim_in_text_space(page) -> tuple[float, float, float, float]:
    """The TrimBox in the SAME top-origin space as this page's text.

    ``transformation_matrix`` is MediaBox-referenced, but the text coordinates
    the trim has to bound live in ``page.rect`` — the CROPBOX normalized to
    origin 0. The two spaces coincide only while CropBox == MediaBox. A PDF
    that puts its CropBox elsewhere slides the trim off its own text by the
    difference: Keys (calibre) writes CropBox y0=9 ABOVE MediaBox y0=24, and
    the 24pt slide pushed every chapter-opening DROP FOLIO out of the bottom
    folio band. Unstripped, that 10pt folio then sat below the 9pt note region
    and broke the region walk on its first line — so all 12 chapter openings
    shipped their footnotes as body prose, with a bare folio and an unlinked
    marker. No gate saw it (coverage is recall-only); every blind reader did.

    Re-anchor on the CropBox: a no-op for a conventional PDF.
    """
    trim_rect = fitz.Rect(page.trimbox) * page.transformation_matrix
    trim_rect.normalize()
    crop_dev = fitz.Rect(page.cropbox) * page.transformation_matrix
    crop_dev.normalize()
    dx, dy = page.rect.x0 - crop_dev.x0, page.rect.y0 - crop_dev.y0
    trim_rect = trim_rect + (dx, dy, dx, dy)
    return (round(trim_rect.x0, 2), round(trim_rect.y0, 2),
            round(trim_rect.x1, 2), round(trim_rect.y1, 2))


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
        n_dots = 0
        n_spaces = 0
        n_ligpads = 0
        n_bidi = 0

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
            trim_pdf = fitz.Rect(page.trimbox)
            trim = trim_in_text_space(page)
            # poppler-crop vote: TrimBox in MediaBox top-left coordinates
            media = fitz.Rect(page.mediabox)
            vote = (round(trim_pdf.x0 - media.x0), round(media.y1 - trim_pdf.y1),
                    round(trim_pdf.width), round(trim_pdf.height))
            crop_votes[vote] = crop_votes.get(vote, 0) + 1

            # rawdict (glyph-level) so the dot-below repair can see the
            # geometry; span text is rebuilt identically when nothing fires
            # (verified span-for-span across the corpus)
            pagedict = page.get_text("rawdict")
            # bidi BEFORE the span repair: it reorders the raw glyphs, which
            # the repair then reads to rebuild each span's text
            n_bidi += reorder_bidi_lines(pagedict)
            d_n, s_n, l_n = repair_span_text(pagedict)
            n_dots += d_n
            n_spaces += s_n
            n_ligpads += l_n
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
        out.subscript_dots = n_dots
        out.cancelled_spaces = n_spaces
        out.ligature_pads = n_ligpads
        out.bidi_moved = n_bidi
        doc.close()
        return out
