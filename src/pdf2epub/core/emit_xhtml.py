# Forked from idml2epub src/idml2epub/emit/xhtml.py @ 7eb7eac
"""Emit XHTML content documents: chapter splitting, semantic markup, notes.

Split rule: a new file starts at every block whose role is in
``split.at_roles`` (default h1), at the first toc-entry (the rebuilt in-body
Contents page), and at front-matter group boundaries (half-title/title-page).
Footnote markup copies the reference EPUB's known-compatible pattern:
noteref/doc-noteref -> notes.xhtml endnotes section with doc-backlink returns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from rapidfuzz import fuzz

from .model import (
    Figure,
    FlowDoc,
    InlinePageBreak,
    NoteRef,
    PageAnchor,
    Paragraph,
    TextRun,
)

_HEAD_ROLES = ("h1", "h2", "h3")


@dataclass
class OutFile:
    file_id: str
    file_name: str
    title: str
    body_parts: list[str] = field(default_factory=list)
    headings: list[tuple[str, str, str]] = field(default_factory=list)  # (level, id, text)
    pagebreaks: list[tuple[str, str]] = field(default_factory=list)  # (label, id)
    landmark: str | None = None


@dataclass
class EmitResult:
    files: list[OutFile]
    notes_file: OutFile | None
    noteref_count: int
    warnings: list[str] = field(default_factory=list)


def _slugify(text: str, fallback: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return (s[:40].rstrip("-")) or fallback


def _run_html(run: TextRun) -> str:
    text = escape(run.text).replace(" ", "<br/>")
    fmt = run.fmt
    if fmt.lang:
        text = f'<span lang="{fmt.lang}" xml:lang="{fmt.lang}" class="{fmt.lang}">{text}</span>'
    if fmt.smallcaps:
        text = f'<span class="smallcaps">{text}</span>'
    if fmt.position == "superscript":
        text = f"<sup>{text}</sup>"
    elif fmt.position == "subscript":
        text = f"<sub>{text}</sub>"
    if fmt.bold:
        text = f"<b>{text}</b>"
    if fmt.italic:
        text = f"<i>{text}</i>"
    return text


class Emitter:
    def __init__(self, cfg, flow: FlowDoc, say, text_width_pt: float = 360.0):
        self.cfg = cfg
        self.flow = flow
        self.say = say
        # approximate text-column width: figures are sized as a % of this
        self.text_width_pt = text_width_pt
        self.files: list[OutFile] = []
        self.cur: OutFile | None = None
        self.warnings: list[str] = []
        self._file_seq = 0
        self._head_seq = 0
        self._note_order: list[str] = []
        self._noteref_file: dict[str, str] = {}
        self.heading_index: list[tuple[str, str, str]] = []  # (text, file, hid)

    # ---------------- file management ----------------

    def _new_file(self, kind: str, title: str) -> OutFile:
        self._file_seq += 1
        slug = _slugify(title, kind)
        name = f"{self._file_seq:03d}-{slug}.xhtml"
        self.cur = OutFile(file_id=f"f{self._file_seq:03d}", file_name=name, title=title)
        self.files.append(self.cur)
        return self.cur

    def _ensure_file(self, kind: str = "front", title: str = "Front matter") -> OutFile:
        if self.cur is None:
            self._new_file(kind, title)
        return self.cur

    # ---------------- emission ----------------

    def _maybe_split_for(self, p: Paragraph, toc_done: bool) -> None:
        """Start the file that paragraph p belongs to (idempotent per block)."""
        if getattr(self, "_split_done_for", None) == id(p):
            return
        role = p.role or "p"
        if role in self.cfg.split_at_roles:
            self._new_file("chapter", p.text().replace(" ", " ").strip() or "Chapter")
            self._split_done_for = id(p)
        elif role in ("half-title", "title-page") and (
            self.cur is None or self.cur.title != "Title pages"
        ):
            self._new_file("title", "Title pages")
            self.cur.title = "Title pages"
            self._split_done_for = id(p)
        elif role == "toc-entry" and not toc_done and not getattr(self, "_contents_started", False):
            f = self._new_file("contents", "Contents")
            f.landmark = "toc"
            self._contents_started = True
            self._split_done_for = id(p)

    def _next_paragraph(self, blocks, j):
        """First Paragraph at or after j, skipping anchors/figures, drops, and
        absorbed blocks."""
        absorbed = getattr(self, "_absorbed", set())
        while j < len(blocks):
            nb = blocks[j]
            if isinstance(nb, Paragraph):
                if (nb.role or "p") == "drop" or id(nb) in absorbed:
                    j += 1
                    continue
                return nb
            if not isinstance(nb, (PageAnchor, Figure)):
                return None
            j += 1
        return None

    def _find_absorbed(self, blocks) -> set[int]:
        """A heading immediately preceding the printed-Contents entries is the
        Contents page's own title; the contents file emits its own heading, so
        the original is absorbed rather than allowed to spawn a chapter file."""
        for i, b in enumerate(blocks):
            if isinstance(b, Paragraph) and (b.role or "p") == "toc-entry":
                j = i - 1
                while j >= 0 and isinstance(blocks[j], (PageAnchor, Figure)):
                    j -= 1
                prev = blocks[j] if j >= 0 else None
                if isinstance(prev, Paragraph) and (prev.role or "") in _HEAD_ROLES:
                    return {id(prev)}
                break
        return set()

    def emit(self) -> EmitResult:
        blocks = self.flow.blocks
        self._absorbed = self._find_absorbed(blocks)
        toc_done = False
        i = 0
        while i < len(blocks):
            b = blocks[i]
            if isinstance(b, Paragraph) and id(b) in self._absorbed:
                self._rescue_inline_anchors(b)
                i += 1
                continue
            if isinstance(b, (PageAnchor, Figure)):
                # a pagebreak/figure run belongs to the file of what FOLLOWS it
                j = i
                while j < len(blocks) and isinstance(blocks[j], (PageAnchor, Figure)):
                    j += 1
                nxt = self._next_paragraph(blocks, j)
                if nxt is not None:
                    self._maybe_split_for(nxt, toc_done)
                for k in range(i, j):
                    if isinstance(blocks[k], PageAnchor):
                        self._emit_pagebreak(blocks[k])
                    else:
                        self._emit_figure(blocks[k])
                i = j
                continue
            if isinstance(b, Paragraph):
                role = b.role or "p"
                if role == "drop":
                    self._rescue_inline_anchors(b)
                    i += 1
                    continue
                if role == "toc-entry" and not toc_done:
                    # gather the whole printed-contents run IN FLOW ORDER:
                    # entries, page anchors, and interleaved centered heads
                    # ('Contents, continued', part subtitles). Stopping at
                    # the first non-entry paragraph dropped every entry after
                    # a mid-TOC subtitle to plain text (I&B: 36 of 44 entries)
                    j = i
                    run: list = []
                    while j < len(blocks):
                        nb = blocks[j]
                        if isinstance(nb, Paragraph) and \
                                (nb.role or "p") == "toc-entry":
                            run.append(nb)
                        elif isinstance(nb, (PageAnchor, Figure)):
                            run.append(nb)
                        elif isinstance(nb, Paragraph) and any(
                                isinstance(b2, Paragraph)
                                and (b2.role or "p") == "toc-entry"
                                for b2 in blocks[j + 1:j + 4]):
                            run.append(nb)  # interlude inside the Contents
                        else:
                            break
                        j += 1
                    # trailing anchors/figures belong to what FOLLOWS the
                    # contents (same doctrine as the main loop)
                    while run and not (isinstance(run[-1], Paragraph)
                                       and (run[-1].role or "p") == "toc-entry"):
                        run.pop()
                        j -= 1
                    self._emit_contents(run)
                    toc_done = True
                    i = j
                    continue
                if b.block_class == "verse":
                    # gather the consecutive verse run (stanza paragraphs +
                    # interleaved page anchors) into ONE blockquote; trailing
                    # anchors belong to what FOLLOWS the poem
                    j = i
                    vrun: list = []
                    while j < len(blocks):
                        nb = blocks[j]
                        if isinstance(nb, Paragraph) and \
                                nb.block_class == "verse" and \
                                (nb.role or "p") != "drop":
                            vrun.append(nb)
                        elif isinstance(nb, PageAnchor):
                            vrun.append(nb)
                        else:
                            break
                        j += 1
                    while vrun and isinstance(vrun[-1], PageAnchor):
                        vrun.pop()
                        j -= 1
                    self._maybe_split_for(b, toc_done)
                    self._emit_verse_group(vrun)
                    i = j
                    continue
                if b.block_class == "quote":
                    # gather the consecutive quote run (paragraphs +
                    # interleaved page anchors) into ONE blockquote; trailing
                    # anchors belong to what FOLLOWS the quotation
                    j = i
                    qrun: list = []
                    while j < len(blocks):
                        nb = blocks[j]
                        if isinstance(nb, Paragraph) and \
                                nb.block_class == "quote" and \
                                (nb.role or "p") != "drop":
                            qrun.append(nb)
                        elif isinstance(nb, PageAnchor):
                            qrun.append(nb)
                        else:
                            break
                        j += 1
                    while qrun and isinstance(qrun[-1], PageAnchor):
                        qrun.pop()
                        j -= 1
                    self._maybe_split_for(b, toc_done)
                    self._emit_quote_group(qrun)
                    i = j
                    continue
                self._maybe_split_for(b, toc_done)
                self._emit_paragraph(b)
            i += 1

        notes_file = self._emit_notes()
        # second pass: contents links can now resolve (headings known)
        return EmitResult(
            files=self.files,
            notes_file=notes_file,
            noteref_count=len(self._note_order),
            warnings=self.warnings,
        )

    def _emit_paragraph(self, p: Paragraph) -> None:
        f = self._ensure_file()
        role = p.role or "p"
        classes = " ".join(dict.fromkeys(p.classes))
        inner = self._items_html(p.items)
        if not inner.strip():
            return
        if role in _HEAD_ROLES:
            self._head_seq += 1
            hid = f"h{self._head_seq:03d}"
            text = p.text().replace(" ", " ").strip()
            f.body_parts.append(f'<{role} id="{hid}" class="{classes}">{inner}</{role}>')
            f.headings.append((role, hid, text))
            self.heading_index.append((text, f.file_name, hid))
        elif role == "blockquote":
            f.body_parts.append(f'<blockquote class="{classes}"><p>{inner}</p></blockquote>')
        elif role == "li":
            f.body_parts.append(f'<p class="listpara {classes}">{inner}</p>')
        elif role == "footnote":
            # footnote paragraphs reached outside <Footnote> shouldn't happen
            f.body_parts.append(f'<p class="{classes}">{inner}</p>')
        elif role in ("half-title", "title-page"):
            f.body_parts.append(f'<p class="titletext {classes}">{inner}</p>')
        elif role == "caption":
            f.body_parts.append(f'<p class="caption {classes}">{inner}</p>')
        else:
            f.body_parts.append(f'<p class="{classes}">{inner}</p>')

    def _items_html(self, items) -> str:
        parts = []
        for it in items:
            if isinstance(it, TextRun):
                parts.append(_run_html(it))
            elif isinstance(it, NoteRef):
                if it.note_id not in self._note_order:
                    self._note_order.append(it.note_id)
                n = self._note_order.index(it.note_id) + 1
                self._noteref_file[it.note_id] = self.cur.file_name if self.cur else ""
                parts.append(
                    f'<a id="fnref{n}" class="noteref" epub:type="noteref" '
                    f'role="doc-noteref" href="notes.xhtml#fn{n}"><sup>{n}</sup></a>'
                )
            elif isinstance(it, InlinePageBreak):
                # exact mid-paragraph page seam (EPUB-a11y inline pattern);
                # recorded in document order so the nav page-list and the
                # QA ordinal pairing keep working unchanged
                pid = f"pg-{it.label}"
                if self.cur is not None:
                    self.cur.pagebreaks.append((it.label, pid))
                parts.append(
                    f'<span id="{pid}" class="pagebreak" epub:type="pagebreak" '
                    f'role="doc-pagebreak" aria-label={quoteattr(it.label)}></span>'
                )
        return "".join(parts)

    def _verse_lines_html(self, p: Paragraph) -> str:
        """Split a stanza Paragraph's items into line segments at the U+2028
        separators the flow recorded, render each through the standard inline
        machinery (noterefs and inline pagebreaks keep their bookkeeping),
        and wrap every line <span class="vl"> (turn lines "vl vt"), joined by
        <br/> — the CSS-less fallback IS the line break."""
        segs: list[list] = [[]]
        for it in p.items:
            if isinstance(it, TextRun) and "\u2028" in it.text:
                for k, piece in enumerate(it.text.split("\u2028")):
                    if k:
                        segs.append([])
                    if piece:
                        segs[-1].append(TextRun(piece, it.fmt))
            else:
                segs[-1].append(it)
        turns = set(p.verse_turns)
        out = []
        for k, seg in enumerate(segs):
            cls = "vl vt" if k in turns else "vl"
            out.append(f'<span class="{cls}">{self._items_html(seg)}</span>')
        return "<br/>".join(out)

    def _emit_verse_group(self, run: list) -> None:
        """Consecutive verse-stanza Paragraphs emit as ONE
        <blockquote class="verse" epub:type="z3998:verse"> holding a
        <p class="vs"> per stanza (the Standard Ebooks poetry pattern: the
        1 flow-Paragraph = 1 emitted block invariant gate 17 depends on is
        kept, stanza by stanza). Interleaved page anchors emit as the
        standard pagebreak div between stanzas — page slicing is
        tag-agnostic on epub:type."""
        f = self._ensure_file()
        parts = ['<blockquote class="verse" epub:type="z3998:verse">']
        for b in run:
            if isinstance(b, PageAnchor):
                pid = f"pg-{b.label}"
                parts.append(
                    f'<div id="{pid}" class="pagebreak" epub:type="pagebreak" '
                    f'role="doc-pagebreak" aria-label={quoteattr(b.label)}>'
                    "</div>")
                f.pagebreaks.append((b.label, pid))
                continue
            inner = self._verse_lines_html(b)
            classes = " ".join(dict.fromkeys(["vs", *b.classes]))
            parts.append(f'<p class="{classes}">{inner}</p>')
        parts.append("</blockquote>")
        f.body_parts.append("".join(parts))

    def _emit_quote_group(self, run: list) -> None:
        """Consecutive quote-classified Paragraphs emit as ONE
        <blockquote class="quote"> holding a <p class="bq"> per paragraph
        (the 1 flow-Paragraph = 1 emitted block invariant gate 17 depends on
        is kept, paragraph by paragraph). Interleaved page anchors emit as
        the standard pagebreak div between paragraphs."""
        f = self._ensure_file()
        parts = ['<blockquote class="quote">']
        for b in run:
            if isinstance(b, PageAnchor):
                pid = f"pg-{b.label}"
                parts.append(
                    f'<div id="{pid}" class="pagebreak" epub:type="pagebreak" '
                    f'role="doc-pagebreak" aria-label={quoteattr(b.label)}>'
                    "</div>")
                f.pagebreaks.append((b.label, pid))
                continue
            inner = self._items_html(b.items)
            classes = " ".join(dict.fromkeys(["bq", *b.classes]))
            parts.append(f'<p class="{classes}">{inner}</p>')
        parts.append("</blockquote>")
        f.body_parts.append("".join(parts))

    def _rescue_inline_anchors(self, p: Paragraph) -> None:
        """A skipped paragraph (role=drop, absorbed heading) must not swallow
        its page anchors: re-emit them as block divs in place."""
        for it in p.items:
            if isinstance(it, InlinePageBreak):
                self._emit_pagebreak(PageAnchor(it.ordinal, it.label))

    def _emit_pagebreak(self, a: PageAnchor) -> None:
        f = self._ensure_file()
        pid = f"pg-{a.label}"
        f.body_parts.append(
            f'<div id="{pid}" class="pagebreak" epub:type="pagebreak" '
            f'role="doc-pagebreak" aria-label={quoteattr(a.label)}></div>'
        )
        f.pagebreaks.append((a.label, pid))

    def _emit_figure(self, fig: Figure) -> None:
        f = self._ensure_file()
        src = f"image/{fig.image_key}"
        alt = escape(fig.alt or "")
        if fig.role == "chinese-page":
            f.body_parts.append(
                f'<div class="chinese-page"><img src="{src}" alt="{alt}"/></div>'
            )
        elif fig.role == "decoration":
            f.body_parts.append(
                f'<div class="figure decoration"><img src="{src}" alt="" role="presentation"/></div>'
            )
        else:
            width = min(100, max(20, round(100 * fig.width_pt / self.text_width_pt)))
            f.body_parts.append(
                f'<figure class="figure" style="width:{width}%">'
                f'<img src="{src}" alt="{alt}"/></figure>'
            )

    # ---------------- contents page ----------------

    def _emit_contents(self, run: list) -> None:
        """Emit the gathered contents run (toc-entry paragraphs, anchors,
        figures, and interlude paragraphs) in flow order inside the section."""
        if self.cfg.toc_handling == "drop":
            return
        if getattr(self, "_contents_started", False) and self.cur is not None:
            f = self.cur  # pre-created when leading anchors/figures arrived
        else:
            f = self._new_file("contents", "Contents")
            f.landmark = "toc"
            self._contents_started = True
        f.body_parts.append('<section epub:type="toc" role="doc-toc">')
        f.body_parts.append('<h1 class="contents-head">Contents</h1>')
        self._contents_entries = []  # plain entry texts, TOCLINK order
        for b in run:
            if isinstance(b, PageAnchor):
                self._emit_pagebreak(b)
                continue
            if isinstance(b, Figure):
                self._emit_figure(b)
                continue
            if (b.role or "p") != "toc-entry":
                # interlude ('Contents, continued', a part subtitle): keep it
                # where the print put it, styled by its own pstyle class
                self._emit_paragraph(b)
                continue
            text = b.text()
            if self.cfg.strip_toc_page_numbers:
                text = re.sub(r"\t+[ivxlcdm0-9]+\s*$", "", text, flags=re.I)
            text = text.replace("\t", " ").replace(" ", " ").strip()
            if not text or text.lower() == "contents":
                continue
            self._contents_entries.append(text)
            f.body_parts.append(f'<p class="toc-entry">{{TOCLINK:{len(self._contents_entries)-1}}}</p>')
        f.body_parts.append("</section>")
        self._contents_file = f

    def resolve_contents_links(self) -> None:
        """Second pass: replace TOCLINK placeholders with real links."""
        if not hasattr(self, "_contents_file"):
            return
        f = self._contents_file
        unmatched = []

        def link_for(idx: int) -> str:
            text = self._contents_entries[idx]
            t = text.lower().strip()
            best, best_score = None, 0.0
            for htext, fname, hid in self.heading_index:
                h = htext.lower().strip()
                score = fuzz.ratio(t, h)
                # a TOC entry often extends the heading ("Foreword by ...")
                # or abbreviates it; treat prefix containment as a strong match
                if h and (t.startswith(h) or h.startswith(t)):
                    score = max(score, 90.0)
                if score > best_score:
                    best, best_score = (fname, hid), score
            display = escape(text)
            if best and best_score >= 85:
                return f'<a href="{best[0]}#{best[1]}">{display}</a>'
            unmatched.append(text)
            return display

        new_parts = []
        for part in f.body_parts:
            m = re.match(r'^<p class="toc-entry">\{TOCLINK:(\d+)\}</p>$', part)
            if m:
                new_parts.append(f'<p class="toc-entry">{link_for(int(m.group(1)))}</p>')
            else:
                new_parts.append(part)
        f.body_parts = new_parts
        if unmatched:
            self.warnings.append(
                f"contents entries without a matching heading (left unlinked): {unmatched}"
            )

    # ---------------- notes ----------------

    def _emit_notes(self) -> OutFile | None:
        if not self._note_order:
            return None
        f = OutFile(file_id="notes", file_name="notes.xhtml", title="Notes")
        f.body_parts.append('<section epub:type="endnotes" role="doc-endnotes">')
        f.body_parts.append('<h1 id="notes-head">Notes</h1>')
        f.body_parts.append('<ol class="notes">')
        for n, note_id in enumerate(self._note_order, 1):
            note = self.flow.notes.get(note_id)
            if note is None:
                continue
            paras = []
            for k, p in enumerate(note.paragraphs):
                inner = self._items_html_plainnotes(p.items, first=(k == 0))
                paras.append(inner)
            back_file = self._noteref_file.get(note_id, "")
            back = (
                f' <a href="{back_file}#fnref{n}" class="backlink" '
                f'epub:type="backlink" role="doc-backlink">↩</a>'
            )
            body = "</p><p>".join(paras) if paras else ""
            f.body_parts.append(
                f'<li id="fn{n}" epub:type="footnote"><p>{body}{back}</p></li>'
            )
        f.body_parts.append("</ol></section>")
        f.headings.append(("h1", "notes-head", "Notes"))
        return f

    def _items_html_plainnotes(self, items, first: bool) -> str:
        parts = []
        for j, it in enumerate(items):
            if isinstance(it, TextRun):
                run = it
                if first and j == 0:
                    run = TextRun(text=re.sub(r"^[.\s]+", "", it.text), fmt=it.fmt)
                parts.append(_run_html(run))
        return "".join(parts)


_XHTML_SHELL = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/"
      lang={lang} xml:lang={lang}>
<head>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="css/styles.css"/>
</head>
<body>
{body}
</body>
</html>
"""


def render_file(f: OutFile, lang: str) -> str:
    return _XHTML_SHELL.format(
        lang=quoteattr(lang), title=escape(f.title), body="\n".join(f.body_parts)
    )


def stage_emit(ctx) -> EmitResult:
    # text column ≈ 80% of the page width (measured from this book's spreads;
    # close enough for relative figure sizing on any trade book)
    page_w = ctx.idml_doc.pages[0].rect.width if ctx.idml_doc.pages else 450.0
    emitter = Emitter(ctx.cfg, ctx.flow, ctx.say, text_width_pt=page_w * 0.8)
    result = emitter.emit()
    emitter.resolve_contents_links()
    out_dir = ctx.cfg.build_dir / "oebps"
    out_dir.mkdir(parents=True, exist_ok=True)
    all_files = result.files + ([result.notes_file] if result.notes_file else [])
    for f in all_files:
        (out_dir / f.file_name).write_text(render_file(f, ctx.cfg.language))
    big = [f.file_name for f in all_files if len("\n".join(f.body_parts)) > 250_000]
    ctx.say(
        f"emitted {len(all_files)} XHTML files, {result.noteref_count} noterefs"
        + (f"; oversized: {big}" if big else "")
    )
    if len(all_files) > ctx.cfg.warn_over_files:
        ctx.say(f"  warning: {len(all_files)} files exceeds warn_over_files")
    for w in result.warnings:
        ctx.say(f"  warning: {w}")
    ctx.emit_result = result
    return result
