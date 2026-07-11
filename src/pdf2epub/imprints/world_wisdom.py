"""World Wisdom imprint transforms.

World Wisdom scholarly editions carry back-matter **Editor's Notes** keyed to the
book's ORIGINAL PRINT PAGE NUMBERS, with no marker in the running body text.
After EPUB reflow those page numbers are meaningless, so the apparatus becomes
unreachable. This transform relinks it against anchors the pipeline already
emits, without touching the words:

  * each note entry's leading **bold print page number** (``4:``, ``xiv:``) ->
    the ``#pg-<label>`` print-page anchor. The number carries forward across the
    entry's continuation paragraphs, exactly as it governs them in print.
  * each ``Note N:`` sub-entry — which annotates the author's footnote *N* on
    that page, using the PRINT per-chapter numbering — -> the author footnote,
    resolved ``(chapter, local N) -> global note`` from the body's noteref order
    (the EPUB renumbers footnotes globally, so chapter 2's "Note 1" is not fn1).

Links are added only as :class:`RunFormat.link` markers (``page:<label>`` /
``note:<note_id>``); the emitter's ``resolve_crossref_links`` second pass turns
them into real cross-file hrefs. Anything that cannot be confidently resolved is
left as plain text and reported to the adjudication queue (advisory — the note
still reads, just without the hyperlink). ``body_backlinks`` (injecting markers
into the body text) is parsed but not yet implemented; it stays ``off``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..core.model import InlinePageBreak, PageAnchor, Paragraph, TextRun
from ..core.runlinks import apply_link as _apply_link

# ------------------------------------------------------------------ config


@dataclass
class EditorsNotesSpec:
    heading: str            # h1 text that opens the Editor's Notes section
    link_page_refs: bool    # link "4:" / "xiv:" -> #pg-<label>
    link_footnote_refs: bool  # link "Note N" -> resolved author footnote
    body_backlinks: str     # "off" | "lemma-exact"  (lemma-exact deferred)


@dataclass
class WorldWisdomOptions:
    editors_notes: EditorsNotesSpec | None


def _as_mode(v, default: str = "off") -> str:
    # YAML parses bare ``off``/``on`` as booleans
    if isinstance(v, bool):
        return "lemma-exact" if v else "off"
    return str(v) if v is not None else default


def parse(data: dict) -> WorldWisdomOptions:
    from ..config import ConfigError, _check_keys

    _check_keys("imprint", data, {"name", "editors_notes"})
    en = data.get("editors_notes")
    ew = None
    if en is not None:
        _check_keys("imprint.editors_notes", en, {
            "heading", "link_page_refs", "link_footnote_refs", "body_backlinks"})
        mode = _as_mode(en.get("body_backlinks", "off"))
        if mode not in ("off", "lemma-exact"):
            raise ConfigError(
                "imprint.editors_notes.body_backlinks must be 'off' or "
                f"'lemma-exact', got {mode!r}")
        if mode == "lemma-exact":
            raise ConfigError(
                "imprint.editors_notes.body_backlinks: 'lemma-exact' is not "
                "implemented yet — keep it 'off'")
        ew = EditorsNotesSpec(
            heading=str(en.get("heading", "Editor's Notes")),
            link_page_refs=bool(en.get("link_page_refs", True)),
            link_footnote_refs=bool(en.get("link_footnote_refs", True)),
            body_backlinks=mode)
    return WorldWisdomOptions(editors_notes=ew)


# ------------------------------------------------------------------ helpers

_ROMAN = "ivxlcdm"
# leading print page number: an arabic run or a roman-numeral run, then ':'
_PAGE_RE = re.compile(rf"\s*(\d+|[{_ROMAN}]+)\s*:", re.IGNORECASE)
# "Note N" cross-reference to the author's per-chapter footnote N
_NOTE_RE = re.compile(r"\s*(Note\s+(\d+))")


def _norm(s: str) -> str:
    """Fold a heading for matching: drop diacritics/punctuation/case, collapse
    whitespace ('The Exo-Esoteric Symbiosis' -> 'the exoesoteric symbiosis')."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^0-9A-Za-z ]+", "", s.replace("-", "")).lower()
    return re.sub(r"\s+", " ", s).strip()


def _flat(items) -> str:
    return "".join(it.text for it in items if isinstance(it, TextRun))


def _is_bold_range(items, start: int, end: int) -> bool:
    """True iff every TextRun overlapping [start, end) is bold (corroborates a
    real bold page number vs. an accidental 'digits:' at a line start)."""
    pos = 0
    seen = False
    for it in items:
        if not isinstance(it, TextRun):
            continue
        a, b = pos, pos + len(it.text)
        pos = b
        if b <= start or a >= end:
            continue
        seen = True
        if not it.fmt.bold:
            return False
    return seen


def _footnote_map(blocks) -> tuple[dict[tuple[str, int], str], set[str]]:
    """Walk the whole flow once. Return
      * ``(norm_chapter, local_k) -> note_id`` — the k-th footnote reference in
        body chapter (h1) C, matching the print per-chapter numbering; and
      * the set of every page-anchor label present (link targets).
    """
    from ..core.model import NoteRef  # local: avoid unused import at module top

    fnmap: dict[tuple[str, int], str] = {}
    labels: set[str] = set()
    chapter = ""
    local = 0
    for b in blocks:
        if isinstance(b, (PageAnchor, InlinePageBreak)):
            labels.add(b.label)
            continue
        if not isinstance(b, Paragraph):
            continue
        if (b.role or "p") == "h1":
            chapter = _norm(b.text())
            local = 0
        for it in b.items:
            if isinstance(it, NoteRef):
                local += 1
                fnmap[(chapter, local)] = it.note_id
            elif isinstance(it, InlinePageBreak):
                labels.add(it.label)
    return fnmap, labels


def _section_bounds(blocks, heading: str) -> tuple[int, int] | None:
    """[start, end) block indices of the Editor's Notes section: the h1 whose
    normalized text matches ``heading``, up to the next h1 (or end)."""
    want = _norm(heading)
    start = None
    for i, b in enumerate(blocks):
        if isinstance(b, Paragraph) and (b.role or "p") == "h1" \
                and _norm(b.text()) == want:
            start = i
            break
    if start is None:
        return None
    end = len(blocks)
    for j in range(start + 1, len(blocks)):
        b = blocks[j]
        if isinstance(b, Paragraph) and (b.role or "p") == "h1":
            end = j
            break
    return start, end


# ------------------------------------------------------------------ apply


def apply(res, cfg, doc, say=print) -> None:
    opts: WorldWisdomOptions = cfg.imprint.options
    if opts.editors_notes is None:
        return
    _link_editors_notes(res, opts.editors_notes, say)


def _link_editors_notes(res, spec: EditorsNotesSpec, say) -> None:
    from ..flowbuilder import _Warn  # local: flowbuilder imports imprints lazily

    blocks = res.flow.blocks
    bounds = _section_bounds(blocks, spec.heading)
    if bounds is None:
        res.warns.append(_Warn(
            f"World Wisdom imprint: no Editor's Notes section found "
            f"(no h1 matching {spec.heading!r}); nothing linked",
            code="imprint-note-unlinked"))
        say(f"  imprint(world-wisdom): Editor's Notes heading "
            f"{spec.heading!r} not found — no links added")
        return

    fnmap, labels = _footnote_map(blocks)
    start, end = bounds
    chapter = ""            # current editor's-notes chapter subhead (h3/h2)
    page_label: str | None = None  # carried-forward print page
    n_page = n_note = n_warn = 0

    for b in blocks[start + 1:end]:
        if not isinstance(b, Paragraph):
            continue
        role = b.role or "p"
        if role in ("h1", "h2", "h3"):
            chapter = _norm(b.text())
            page_label = None
            continue

        flat = _flat(b.items)
        page_span = None
        rest_at = 0

        m_pg = _PAGE_RE.match(flat)
        if m_pg and _is_bold_range(b.items, m_pg.start(1), m_pg.end(1)):
            raw = m_pg.group(1)
            label = raw if raw in labels else raw.lower()
            page_label = label
            rest_at = m_pg.end()
            if spec.link_page_refs:
                if label in labels:
                    page_span = (m_pg.start(1), m_pg.end(1), f"page:{label}")
                else:
                    n_warn += 1
                    res.warns.append(_Warn(
                        f"World Wisdom editor's note references print page "
                        f"{raw!r} but no page anchor exists — left unlinked",
                        code="imprint-note-unlinked"))

        note_span = None
        if spec.link_footnote_refs:
            m_nt = _NOTE_RE.match(flat, rest_at)
            if m_nt:
                local = int(m_nt.group(2))
                note_id = fnmap.get((chapter, local))
                if note_id is not None:
                    note_span = (m_nt.start(1), m_nt.end(1), f"note:{note_id}")
                elif chapter:
                    n_warn += 1
                    res.warns.append(_Warn(
                        f"World Wisdom editor's note 'Note {local}' under "
                        f"chapter {chapter!r} (page {page_label}) has no "
                        "matching author footnote — left unlinked",
                        code="imprint-note-unlinked"))

        # apply markers; offsets are stable because _apply_link preserves text
        items = b.items
        if note_span:
            items = _apply_link(items, *note_span)
            n_note += 1
        if page_span:
            items = _apply_link(items, *page_span)
            n_page += 1
        b.items = items

    say(f"  imprint(world-wisdom): linked {n_page} page ref(s), "
        f"{n_note} footnote ref(s) in Editor's Notes"
        + (f"; {n_warn} unresolved" if n_warn else ""))
