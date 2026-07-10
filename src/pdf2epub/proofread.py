"""Proofread packets: the finished EPUB re-rendered for a READER's eyes.

Deterministic packets (light markdown, page markers, [n] noterefs) from the
SHIPPED epub + a review protocol + a manifest — the desk for the
proofread-epub skill's blind reader subagents. No PDF extraction happens
here (PyMuPDF is opened only for the page count); packets are a pure
function of the EPUB bytes and book.yaml.

Also home to the `pdf2epub lines` formatter: raw extraction line indexes +
geometry per page, the key needed to write flow.overrides.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

_X = "{http://www.w3.org/1999/xhtml}"
_E = "{http://www.idpf.org/2007/ops}"
_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "li", "figcaption"}
_H_LEVEL = {"h1": "#", "h2": "##", "h3": "###", "h4": "####"}
_ESCAPE_LEADS = set("#>-{\\|")

SPLIT_OVER = 4500     # words: a spine file beyond this splits into chunks
CHUNK_TARGET = 3500   # words per chunk after splitting
WRAP = 100            # chars: keeps seams visible under Read-tool truncation

CONTEXT_OPEN = ("{context — for continuity only; do NOT report findings "
                "inside this fence}")
CONTEXT_CLOSE = "{/context}"


@dataclass(slots=True)
class Block:
    kind: str                 # "block" | "pagebreak"
    lines: list[str] = field(default_factory=list)
    words: int = 0
    label: str = ""           # pagebreak only
    k: int = -1               # pagebreak only: global anchor ordinal


# ------------------------------------------------------------ rendering

def _inline_text(el) -> str:
    """Inline content with noterefs as [n] and backlinks dropped."""
    parts = [el.text or ""]
    for child in el:
        tag = child.tag
        local = tag[len(_X):] if isinstance(tag, str) and tag.startswith(_X) \
            else ""
        cls = child.get("class") or ""
        if local == "a" and "noteref" in cls:
            marker = "".join(child.itertext()).strip()
            parts.append(f"[{marker}]")
        elif local == "a" and "backlink" in cls:
            pass                          # navigation chrome
        else:
            parts.append(_inline_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


_CHUNK_LETTERS = "bcdefghijklmnopqrstuvwxyz"


def _chunk_suffix(ci: int) -> str:
    """Suffix for chunk ci (1-based beyond the unsuffixed first): letters
    b..z, then x27, x28… — a 130-page chapter legitimately splits past the
    old 16-letter alphabet (M&R 'My Time with Mawlana': 17 chunks)."""
    return _CHUNK_LETTERS[ci - 1] if ci <= len(_CHUNK_LETTERS) else f"x{ci}"


def _escape(line: str) -> str:
    """A plain output line starting with a builder-meaningful char is book
    text — escape it so {…} and structural prefixes stay unambiguous."""
    return "\\" + line if line and line[0] in _ESCAPE_LEADS else line


def _wrap(text: str) -> list[str]:
    return textwrap.wrap(text, width=WRAP, break_long_words=False,
                         break_on_hyphens=False) or []


def _render_block(local: str, classes: set[str], in_bq: bool, text: str,
                  note_no: int | None = None) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if local in _H_LEVEL:
        return [f"{_H_LEVEL[local]} {text}"]
    if note_no is not None:
        lines = _wrap(f"{{note {note_no}}} {text}")
        return lines[:1] + ["  " + l for l in lines[1:]]
    if "listpara" in classes or local == "li":
        lines = _wrap(text)
        return [f"- {lines[0]}"] + ["  " + l for l in lines[1:]] if lines else []
    for cls, tag in (("caption", "{caption}"), ("titletext", "{titlepage}"),
                     ("toc-entry", "{toc}")):
        if cls in classes or (cls == "caption" and local == "figcaption"):
            lines = _wrap(f"{tag} {text}")
            return lines[:1] + ["  " + l for l in lines[1:]]
    if in_bq:
        return ["> " + l for l in _wrap(text)]
    return [_escape(l) for l in _wrap(text)]


def walk_doc(doc, is_notes: bool, k_start: int) -> tuple[list[Block], int]:
    """Blocks + pagebreaks of one spine doc in document order. Returns the
    blocks and the advanced global anchor ordinal."""
    blocks: list[Block] = []
    k = k_start
    body = doc.root.find(f"{_X}body")
    if body is None:
        return blocks, k
    note_no = 0
    for el in body.iter():
        tag = el.tag
        if not isinstance(tag, str) or not tag.startswith(_X):
            continue
        local = tag[len(_X):]
        if is_notes:
            if local == "li":
                note_no += 1
                text = _inline_text(el)
                lines = _render_block(local, set(), False, text,
                                      note_no=note_no)
                if lines:
                    blocks.append(Block(kind="block", lines=lines,
                                        words=len(text.split())))
            continue
        if (el.get(f"{_E}type") or "") == "pagebreak":
            blocks.append(Block(kind="pagebreak",
                                label=el.get("aria-label") or "", k=k))
            k += 1
            continue
        if local == "img":
            # a plate/figure is content the reader must know exists (a
            # facsimile letter page reads as 'missing text' otherwise)
            alt = re.sub(r"\s+", " ", el.get("alt") or "").strip()
            blocks.append(Block(kind="block",
                                lines=_wrap(f"{{figure}} {alt or '(no alt)'}"),
                                words=0))
            continue
        if local not in _BLOCK_TAGS:
            continue
        classes = set((el.get("class") or "").split())
        if local == "p" and "vs" in classes:
            # verse stanza: each line span renders as its OWN packet line —
            # '| ' base, '|    ' turn — so blind readers see the print's
            # line structure (whitespace-collapsed rendering was itself the
            # structure-loss the taxonomy names)
            vlines: list[str] = []
            words = 0
            for sp in el:
                if not (isinstance(sp.tag, str) and sp.tag == f"{_X}span"):
                    continue
                scls = set((sp.get("class") or "").split())
                if "vl" not in scls:
                    continue
                t = re.sub(r"\s+", " ", _inline_text(sp)).strip()
                if not t:
                    continue
                words += len(t.split())
                pre = "|    " if "vt" in scls else "| "
                wrapped = _wrap(t)
                vlines.append(pre + wrapped[0])
                vlines.extend("|      " + w for w in wrapped[1:])
            if vlines:
                blocks.append(Block(kind="block", lines=vlines, words=words))
            continue
        in_bq = False
        parent = el.getparent()
        while parent is not None:
            if parent.tag == f"{_X}blockquote":
                in_bq = True
                break
            parent = parent.getparent()
        text = _inline_text(el)
        lines = _render_block(local, classes, in_bq, text)
        if lines:
            blocks.append(Block(kind="block", lines=lines,
                                words=len(text.split())))
    return blocks, k


# ------------------------------------------------------------ chunking

def split_chunks(blocks: list[Block]) -> list[list[Block]]:
    total = sum(b.words for b in blocks)
    if total <= SPLIT_OVER:
        return [blocks]
    n = math.ceil(total / CHUNK_TARGET)
    target = total / n
    chunks: list[list[Block]] = []
    cur: list[Block] = []
    acc = 0
    for b in blocks:
        cur.append(b)
        acc += b.words
        if acc >= target and len(chunks) < n - 1:
            chunks.append(cur)
            cur = []
            acc = 0
    if cur:
        chunks.append(cur)
    return chunks


def _content_blocks(chunk: list[Block]) -> list[Block]:
    return [b for b in chunk if b.kind == "block"]


def render_packet(chunk: list[Block], header: dict,
                  prev_tail: list[Block], next_head: list[Block]) -> str:
    out = ["---"]
    for key in ("packet", "file", "spine", "pages", "words", "protocol"):
        out.append(f"{key}: {header[key]}")
    out.append("---")
    out.append("")

    def emit(blocks: list[Block]) -> None:
        for b in blocks:
            if b.kind == "pagebreak":
                out.append(f"{{p.{b.label}}}")
            else:
                out.extend(b.lines)
            out.append("")

    if prev_tail:
        out.append(CONTEXT_OPEN)
        emit(prev_tail)
        out.append(CONTEXT_CLOSE)
        out.append("")
    emit(chunk)
    if next_head:
        out.append(CONTEXT_OPEN)
        emit(next_head)
        out.append(CONTEXT_CLOSE)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ------------------------------------------------------------ protocol

_PROTOCOL = """\
# Proofread protocol — {title}

You are checking a PDF-to-EPUB **conversion**, not editing a book. The
author's words are sacrosanct: never flag style, argument, spelling as
printed, or old-fashioned usage. You are hunting damage a conversion can
cause: text fused, split, dropped, doubled, garbled, or glued together
wrong. Read the packet as a careful human reader would. Report ONLY what
fits the taxonomy below.

## Defect taxonomy (closed list — use these class names)

- `fused-paragraphs` — two paragraphs run together in one block, e.g. a
  quotation ends "…(Udana, 80-81)[38]" and commentary "The juxtaposition…"
  continues in the same paragraph.
- `wrong-split` — one sentence/paragraph broken in two; the second block
  starts mid-sentence with no capital.
- `seam-space` — missing or doubled space where lines/pages were joined:
  "himto", "said.Then", "the  term".
- `bad-dehyphenation` — a line-break hyphen wrongly kept or removed:
  "com- munity"; "selfevident" where print must read "self-evident".
- `garble` — characters that cannot be the book's text: "WKH MXVW", stray
  box/control characters, impossible letter salad.
- `fused-heading` — a heading carrying words of a different element:
  "Part Two Oneness: The Highest…" (part label fused onto a title), or a
  heading ending mid-sentence.
- `quote-boundary` — quoted/indented material merged into body text, body
  swallowed into a quote, or two separate quotations in one block.
- `stray-furniture` — a running head, bare folio number, or printer slug
  inside the prose.
- `noteref-anomaly` — a [n] marker glued to the next word ("[38]The"),
  duplicated, or in an impossible position.
- `structure-loss` — verse lines, list items, or a table flattened into
  one prose paragraph.
- `duplicated-text` — the same sentence/passage appearing twice in a row.
- `truncated-text` — a sentence or apparatus that stops dead or is visibly
  incomplete (e.g. a Contents that starts at its own midpoint).

## Do NOT flag (this book's known-correct conventions)

- Archaic or formal diction, long sentences, British spellings — as printed.
- Transliteration diacritics (macrons, dots, ayn/hamza) — correct.
- Parenthesized honorific readings — these render calligraphic glyphs and
  are correct wherever they appear:
{honorifics}
- [n] endnote markers: numbering is sequential for the ebook and will NOT
  match printed note numbers. Only position/glue problems are reportable.
- Section ornaments/flourishes were deliberately dropped{ornaments}.
- {{p.N}} page markers are paragraph-granular; pagination, line breaks, and
  hyphenation naturally differ from print (the text reflows).
- Lines prefixed `| ` (turn lines `|    `) are VERSE set line-for-line as
  printed — the line structure is correct by construction. Report
  `structure-loss` only where verse appears as flowed prose WITHOUT the
  `| ` prefixes, or a `| ` line visibly fuses two verse lines in one.
- Dash and curly-quote conventions as they appear; {{toc}} entries are a
  rebuilt hyperlinked Contents (page numbers removed by design) — but a
  visibly incomplete or garbled Contents IS reportable.

## Evidence requirements — every finding

- `quote`: verbatim span from the packet, <=120 chars, unique enough to
  locate (matching is whitespace-insensitive).
- `page`: nearest preceding {{p.N}} label, or "front" if none.
- `class`: one taxonomy name.
- `expected`: one sentence — what the text should be.
- `confidence`: high | medium | low. Report low-confidence suspicions too;
  a verifier checks everything against the print page.
- `check`: one sentence telling the verifier what to look at on the print
  render.

## Output format (your ENTIRE final message)

```json
{{"packet": "NNN", "findings": [
  {{"class": "fused-paragraphs",
   "quote": "(Udana, 80-81)[38]The juxtaposition of these two scriptural",
   "page": "80",
   "expected": "new paragraph begins at 'The juxtaposition'; space after [38]",
   "confidence": "high",
   "check": "on print p.80, is 'The juxtaposition' a fresh paragraph?"}}
]}}
```

Zero findings is a valid and common result:
`{{"packet": "NNN", "findings": []}}`.
"""


def protocol_text(cfg) -> str:
    readings: set[str] = set()
    for rule in cfg.pua_map.values():
        if rule.action == "char" and rule.char and len(rule.char.strip()) > 3:
            readings.add(rule.char.strip())
    for v in cfg.shifted_cmap_highmap.values():
        if len(v.strip()) > 3:
            readings.add(v.strip())
    for p in cfg.gt_strip_phrases:
        if len(p.strip()) > 3:
            readings.add(p.strip())
    honorifics = "\n".join(f"  - {r}" for r in sorted(readings)) or \
        "  - (none configured for this book)"
    n_drop = sum(1 for r in cfg.pua_map.values() if r.action == "drop")
    ornaments = f" ({n_drop} ornament glyph(s) per config)" if n_drop else ""
    return _PROTOCOL.format(title=cfg.title or "untitled", honorifics=honorifics,
                            ornaments=ornaments)


# ------------------------------------------------------------ build

def run_proofread(epub: Path, config: Path, say=print) -> int:
    import fitz

    from .config import load_config
    from .core.qa_epubload import load_epub

    cfg = load_config(config)
    ep = load_epub(epub)
    nav_href = ep.nav_doc().href if ep.nav_doc() else ""
    spine = [d for d in ep.spine_docs()
             if d.href != nav_href and "cover" not in d.href]
    # the generated endnotes file carries <section epub:type="endnotes">;
    # keyed on that, NOT a 'notes' filename substring, so body *sections*
    # named '…Notes' (Editor's Notes, Biographical Notes) stay in reading order
    notes_docs = [d for d in spine if d.is_endnotes()]
    body_docs = [d for d in spine if not d.is_endnotes()]

    with fitz.open(cfg.pdf_path()) as fz:
        n_pages = fz.page_count
    in_flow = cfg.in_flow_pages(n_pages)

    # walk in spine order; notes last (their packets close the book)
    per_file: list[tuple[str, list[Block]]] = []
    k = 0
    for doc in body_docs:
        blocks, k = walk_doc(doc, is_notes=False, k_start=k)
        per_file.append((doc.href, blocks))
    for doc in notes_docs:
        blocks, _ = walk_doc(doc, is_notes=True, k_start=0)
        per_file.append((doc.href, blocks))

    anchors = [{"k": b.k, "label": b.label, "physical": None}
               for _, blocks in per_file for b in blocks
               if b.kind == "pagebreak"]
    anchor_warning = ""
    if len(anchors) == len(in_flow):
        for a in anchors:
            a["physical"] = in_flow[a["k"]]
    else:
        anchor_warning = (f"{len(anchors)} pagebreak anchors vs "
                          f"{len(in_flow)} in-flow pages — physical page "
                          "mapping unavailable")
        anchors = []

    out_dir = epub.parent / "proofread"
    packets_dir = out_dir / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    for old in packets_dir.glob("*.md"):
        old.unlink()

    manifest_packets = []
    nnn = 0
    for href, blocks in per_file:
        chunks = split_chunks(blocks)
        for ci, chunk in enumerate(chunks):
            nnn += 1
            stem = Path(href).stem
            suffix = "" if ci == 0 else "-" + _chunk_suffix(ci)
            name = f"{nnn:03d}-{stem}{suffix}.md"
            labels = [b.label for b in chunk if b.kind == "pagebreak"]
            ks = [b.k for b in chunk if b.kind == "pagebreak"]
            words = sum(b.words for b in chunk)
            header = {
                "packet": f"{nnn:03d}",
                "file": f"packets/{name}",
                "spine": href + (f" (chunk {ci + 1} of {len(chunks)})"
                                 if len(chunks) > 1 else ""),
                "pages": f"{labels[0]}-{labels[-1]}" if labels else "none",
                "words": words,
                "protocol": "../PROTOCOL.md",
            }
            prev_tail = _content_blocks(chunks[ci - 1])[-2:] if ci else []
            next_head = (_content_blocks(chunks[ci + 1])[:2]
                         if ci + 1 < len(chunks) else [])
            content = render_packet(chunk, header, prev_tail, next_head)
            (packets_dir / name).write_text(content)
            manifest_packets.append({
                "id": f"{nnn:03d}", "file": f"packets/{name}", "spine": href,
                "chunk": [ci + 1, len(chunks)], "words": words,
                "anchor_k": [ks[0], ks[-1]] if ks else [],
                "first_label": labels[0] if labels else "",
                "last_label": labels[-1] if labels else "",
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            })

    (out_dir / "PROTOCOL.md").write_text(protocol_text(cfg))
    manifest = {
        "tool": "pdf2epub proofread",
        "epub": epub.name,
        "epub_sha256": hashlib.sha256(epub.read_bytes()).hexdigest(),
        "config": str(config),
        "pdf": str(cfg.pdf_path()),
        "title": cfg.title or "",
        "anchors": anchors,
        **({"anchor_warning": anchor_warning} if anchor_warning else {}),
        "packets": manifest_packets,
        "whitelist": {
            "honorific_readings": sorted(
                {r.char.strip() for r in cfg.pua_map.values()
                 if r.action == "char" and r.char and len(r.char.strip()) > 3}
                | {v.strip() for v in cfg.shifted_cmap_highmap.values()
                   if len(v.strip()) > 3}
                | {p.strip() for p in cfg.gt_strip_phrases
                   if len(p.strip()) > 3}),
            "gt_strip_phrases": list(cfg.gt_strip_phrases),
            "ornaments_dropped": sum(1 for r in cfg.pua_map.values()
                                     if r.action == "drop"),
            "endnotes_renumbered": True,
            "dehyphenate": cfg.dehyphenate,
            "restore_spaces": bool(cfg.restore_spaces),
            "toc_rebuilt": True,
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    say(f"proofread: {nnn} packets -> {out_dir}/ "
        f"({sum(p['words'] for p in manifest_packets)} words; "
        f"anchors {'ok' if not anchor_warning else 'WARN: ' + anchor_warning})")
    return 0


# ------------------------------------------------------------ lines dump

def format_page_lines(doc, geo, pno: int) -> list[str]:
    """One row per RAW extraction line index — the key flow.overrides uses."""
    from .analyze import line_pstyle

    page = doc.page(pno)
    t = page.trim
    body_f = None
    out = [f"page {pno} label {page.label!r} "
           f"trim {t[2] - t[0]:.0f}x{t[3] - t[1]:.0f}pt "
           f"col [{geo.col_left:.1f}, {geo.col_right:.1f}] "
           f"body size {geo.body_size:g}pt",
           f" idx    x0     x1      y0  pstyle{' ' * 26}text"]
    for i, ln in enumerate(page.lines):
        prev = page.lines[i - 1] if i else None
        ps = line_pstyle(ln, doc, geo, prev, page_shift=geo.shift(pno))
        text = re.sub(r"[\x00-\x1f]", "·", ln.text())[:60]
        sup = " [sup]" if all(r.superscript for r in ln.runs) and ln.runs \
            else ""
        out.append(f"{i:4d} {ln.x0:6.1f} {ln.x1:6.1f} {ln.y0:7.1f}  "
                   f"{ps:<31} {text}{sup}")
    return out


def run_lines(config: Path, pages: list[str], render: bool = False,
              dpi: int = 150, say=print) -> int:
    from .analyze import column_geometry
    from .config import load_config
    from .extract import extract

    cfg = load_config(config)
    wanted: list[int] = []
    for spec in pages:
        for part in spec.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-", 1)
                wanted.extend(range(int(lo), int(hi) + 1))
            elif part:
                wanted.append(int(part))
    doc = extract(cfg.pdf_path(), say=lambda m: None)
    geo = column_geometry(doc)
    for pno in wanted:
        if not 1 <= pno <= doc.n_pages:
            say(f"page {pno}: out of range (1..{doc.n_pages})")
            continue
        for line in format_page_lines(doc, geo, pno):
            say(line)
        if render:
            from .thumbs import render_page

            out = cfg.build_dir / "proofread" / "renders" / f"p{pno:04d}.png"
            render_page(cfg.pdf_path(), pno, out, dpi=dpi, clip_trim=True)
            say(f"render: {out}")
        say("")
    return 0
