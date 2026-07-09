"""QA ground truth: an INDEPENDENT poppler extraction of what the book says.

pdftotext (not PyMuPDF — different glyph decoder), cropped to the trim box,
furniture-stripped and textfixed with the same deterministic chain the flow
used, then note bodies removed per page (they move to endnotes in the EPUB;
in-place they'd count as huge mid-page 'missing' segments — I&B's notes are
~8.4% of its text). Gate 3 guards the circularity: every removed note body
must ALSO appear in the page's RAW ground truth."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..analyze import detect_furniture, furniture_template
from ..config import PdfBookConfig

_PUA_RE = re.compile(r"[\ue000-\uf8ff]")
from ..core.textnorm import is_folio_line, normalize
from ..extract import poppler_page_texts
from ..pdfmodel import PdfDoc
from ..textfix import expand_ligatures, restore_spaces


@dataclass(slots=True)
class GroundTruth:
    pages_raw: dict[int, str] = field(default_factory=dict)       # normalized, unstripped
    pages: dict[int, str] = field(default_factory=dict)           # stripped + fixed
    furniture_templates: set[str] = field(default_factory=set)
    note_chars_removed: int = 0
    figure_chars_excluded: int = 0
    region_chars_excluded: int = 0
    phrase_chars_removed: int = 0
    disputed_chars: int = 0
    disputed_pages: list[int] = field(default_factory=list)
    note_strip_failures: list[str] = field(default_factory=list)

    def joined(self) -> str:
        return "\n".join(self.pages[p] for p in sorted(self.pages))


def build_ground_truth(pdf: Path, cfg: PdfBookConfig, doc: PdfDoc,
                       note_texts_by_page: dict[int, list[tuple[str, str]]],
                       stripped_lines: dict[int, list[str]] | None = None,
                       region_texts: dict[int, list[str]] | None = None) -> GroundTruth:
    gt = GroundTruth()
    raw_pages = poppler_page_texts(pdf, crop=doc.trim_crop_box)
    in_flow = set(cfg.in_flow_pages(doc.n_pages))
    fig_pages = {p for fp in cfg.figure_pages for p in fp.pages}
    gt.furniture_templates = {
        r["text"] for r in detect_furniture(
            doc, [p for p in doc.pages if p.number in in_flow and p.lines],
            cfg.repeat_min_pages)}
    gt.furniture_templates |= {furniture_template(t) for t in cfg.furniture_extra}
    gt.furniture_templates -= {furniture_template(t) for t in cfg.furniture_keep}
    # MuPDF merges folio+head into one line ('#book of knowledge | chapter #');
    # poppler splits them, so its head templates lack the edge '#'. Match on
    # the edge-#-insensitive canonical form.
    canon = {t.strip("#").strip() for t in gt.furniture_templates}

    for pno in sorted(in_flow):
        if pno - 1 >= len(raw_pages):
            break
        raw = raw_pages[pno - 1]
        lines = [ln for ln in raw.split("\n") if ln.strip()]
        kept = []
        # the flow's exact stripped lines for this page (fused MuPDF forms
        # like '14book of knowledge'; poppler splits folio and head, so also
        # match on the digit/roman-stripped remainder)
        page_stripped = set()
        for s in (stripped_lines or {}).get(pno, []):
            page_stripped.add(s)
            page_stripped.add(re.sub(r"^[\divxlcdm]+\s*|\s*[\divxlcdm]+$", "", s,
                                     flags=re.I).strip())
        # figure_regions text ships as a raster: excise poppler lines that
        # match a region line or one of its runs, ANYWHERE on the page
        # (regions are mid-page, unlike furniture). Poppler may fuse two
        # cells MuPDF kept apart, so also match run-CONCATENATIONS loosely:
        # a poppler line every one of whose space-split tokens appears in
        # the region token set is region text.
        page_regions = set((region_texts or {}).get(pno, []))
        region_tokens = {t for s in page_regions for t in s.split()}
        from ..textfix import probe_text
        for i, ln in enumerate(lines):
            n = normalize(ln)
            if page_regions:
                if n in page_regions or (
                        len(n) >= 3 and region_tokens
                        and all(t in region_tokens for t in n.split())):
                    gt.region_chars_excluded += len(n)
                    continue
            first_or_last = i <= 1 or i >= len(lines) - 2
            if first_or_last:
                # symmetric with the flow's furniture strip: a shifted-CMap
                # folio ('129' -> control bytes) is repaired before the shape
                # test, so poppler's garbled folio is excised here too
                if is_folio_line(normalize(probe_text(
                        ln, cfg.shifted_cmap_repair, cfg.shifted_cmap_highmap))):
                    continue
                if furniture_template(ln).strip("#").strip() in canon:
                    continue
                if n in page_stripped or n.strip("0123456789ivxlcdmIVXLCDM ") in \
                        {p.strip("0123456789ivxlcdmIVXLCDM ") for p in page_stripped}:
                    continue
            kept.append(ln)
        text = "\n".join(kept)
        if cfg.shifted_cmap_repair:
            from ..textfix import is_shifted_run, repair_shifted_cmap
            text = "\n".join(
                (repair_shifted_cmap(l, cfg.shifted_cmap_highmap)[0]
                 if is_shifted_run(l, cfg.shifted_cmap_highmap) else l)
                for l in text.split("\n"))
        from ..textfix import strip_control_chars
        text, _ = strip_control_chars(text)
        if cfg.fffd_repairs and "�" in text:
            # same chain both sides — a no-op when poppler decoded the
            # glyphs the candidate's extractor could not
            fd = next((f for f in cfg.fffd_repairs if pno in f.pages), None)
            if fd is not None:
                text = text.replace("�", fd.replace)
        text, _ = expand_ligatures(text)
        if cfg.restore_spaces:
            text, _ = restore_spaces(text)
        # private-use glyphs are unrepresentable extraction artifacts — they
        # are policed on the CANDIDATE side by gate 10, and must not count as
        # 'source text' the EPUB failed to carry
        norm = normalize(_PUA_RE.sub("", text))
        gt.pages_raw[pno] = norm

        if pno in fig_pages:
            gt.figure_chars_excluded += len(norm)
            gt.pages[pno] = ""
            continue

        # poppler's OWN garble of the broken-CMap section ('=word=word=' —
        # spaces decoded as '='): the witnesses disagree, so this page's gt
        # cannot arbitrate; itemized as engine-disputed
        if cfg.shifted_cmap_repair and re.search(r"=\w+=\w+=\w+", norm):
            gt.disputed_chars += len(norm)
            gt.disputed_pages.append(pno)
            gt.pages_raw[pno] = norm
            gt.pages[pno] = ""
            continue

        # strip this page's note bodies (verified against raw by the caller)
        fails_before = len(gt.note_strip_failures)
        markers: list[str] = []
        for marker, note_text in note_texts_by_page.get(pno, []):
            if marker:
                markers.append(marker)
            # search on the note BODY (drop the fragment's own leading marker):
            # the caller's marker pass then strips BOTH copies (note-side + the
            # in-body ref) exactly, not over-running count=2 into a stray digit
            body = normalize(note_text)
            if marker:
                body = re.sub(r"^\s*" + re.escape(marker) + r"[.)]?\s*", "",
                              body, count=1)
            if len(body) < 15:
                continue
            out = _excise_note(norm, body, marker)
            if out is not None:
                norm, removed = out
                gt.note_chars_removed += removed
            else:
                gt.note_strip_failures.append(f"p.{pno}: {body[:60]}…")
        # excision fallback: notes sit at the page bottom starting with their
        # marker ('9. ') — when text-matching failed, cut from the first
        # still-present marker-prefixed line to the page end
        if len(gt.note_strip_failures) > fails_before and markers:
            for marker in markers:
                if marker == "*":
                    continue
                m = re.search(rf"(?:^|\s){re.escape(marker)}\.\s", norm)
                if m:
                    cut = len(norm) - m.start()
                    gt.note_chars_removed += cut
                    norm = norm[:m.start()]
                    break
        # remove the printed marker digits: they appear superscript in the
        # body AND again before the note body; the EPUB renumbers its
        # noterefs (whose anchor text the runner strips from the candidate)
        for marker in markers:
            if marker == "*":
                norm = re.sub(r"[*†‡]", " ", norm, count=2)
            else:
                norm = re.sub(rf"(?<!\d){re.escape(marker)}(?!\d)", " ", norm, count=2)
        # agent-verified poppler glyph readings (JP-P6): poppler's ToUnicode
        # expands symbol ligatures to whole phrases ('May God be pleased with
        # her') that the EPUB legitimately renders as the glyph char
        for phrase in cfg.gt_strip_phrases:
            n = normalize(phrase)
            while n and n in norm:
                norm = norm.replace(n, " ", 1)
                gt.phrase_chars_removed += len(n)
        gt.pages[pno] = re.sub(r"\s{2,}", " ", norm)
    return gt


def paged_coverage(gt: GroundTruth, candidate: str):
    """Coverage computed page-by-page with a sliding cursor over the candidate
    text. One whole-book SequenceMatcher is quadratic and takes minutes on a
    338-page book; page-sized comparisons with a bounded window are near-linear
    and order-preserving (both sides are in reading order)."""
    from difflib import SequenceMatcher

    from ..core.qa_textdiff import CoverageResult

    total = 0
    matched = 0
    missing: list[str] = []
    cursor = 0
    for pno in sorted(gt.pages):
        page = gt.pages[pno]
        if not page:
            continue
        total += len(page)
        # anchor the window by FINDING the page's opening snippet — a cursor
        # that drifts once otherwise cascades misalignment over every
        # following page (observed: 56% on a build whose text was fine)
        # candidate windows to try: the cursor, plus one anchored per probe
        # (a single probe can false-match a similar passage elsewhere — keep
        # whichever window matches BEST; order violations are gate 6's job)
        starts = [cursor]
        for probe_at in (0, len(page) // 4, len(page) // 2, (3 * len(page)) // 4):
            snippet = page[probe_at:probe_at + 32]
            if len(snippet) < 12:
                continue
            hit = candidate.find(snippet)
            while hit >= 0 and len(starts) < 8:
                starts.append(max(0, hit - probe_at - 200))
                hit = candidate.find(snippet, hit + 1)
        best = (0, cursor, [])
        for ws_ in dict.fromkeys(starts):
            window = candidate[ws_:min(len(candidate), ws_ + len(page) * 2 + 4000)]
            sm = SequenceMatcher(None, page, window, autojunk=False)
            blocks = sm.get_matching_blocks()
            m = sum(b.size for b in blocks)
            if m > best[0]:
                best = (m, ws_, blocks)
            if m >= len(page) * 0.98:
                break
        page_matched, window_start, blocks = best
        matched += page_matched
        # unmatched runs of the page >= 20 chars are reportable segments
        pos = 0
        last_b_end = 0
        for b in blocks:
            if b.a - pos >= 20:
                missing.append(f"p.{pno}: {page[pos:b.a][:120]}")
            pos = b.a + b.size
            if b.size:
                last_b_end = b.b + b.size
        if len(page) - pos >= 20:
            missing.append(f"p.{pno}: {page[pos:][:120]}")
        if page_matched > len(page) * 0.3 and last_b_end:
            cursor = window_start + last_b_end
    return CoverageResult(pdf_chars=total, matched_chars=matched,
                          missing_segments=missing)


_SQUEEZE_CHARS = "-­‐‑–— \t\n"


def _squeeze(s: str) -> tuple[str, list[int]]:
    out: list[str] = []
    pos: list[int] = []
    for i, ch in enumerate(s):
        if ch in _SQUEEZE_CHARS:
            continue
        out.append(ch)
        pos.append(i)
    return "".join(out), pos


def _find_fuzzyish(hay: str, needle: str) -> tuple[int, int] | None:
    """Locate ``needle`` in ``hay``; return (start, end) in hay coordinates.
    Falls back through a distinctive-midsection probe and, last, a hyphen- and
    space-insensitive squeeze match: the flow dehyphenates a note's line breaks
    ('mercantile') while poppler keeps them ('mer- cantile'), so an exact find
    misses even though the words are identical."""
    idx = hay.find(needle)
    if idx >= 0:
        return idx, idx + len(needle)
    if len(needle) > 60:
        mid = needle[10:50]
        j = hay.find(mid)
        if j >= 0:
            k = hay.find(needle[-30:], j)
            if k >= 0:
                return max(0, j - 10), k + 30
    sn, _ = _squeeze(needle)
    if len(sn) >= 12:
        sh, pos = _squeeze(hay)
        p = sh.find(sn)
        if p >= 0:
            return pos[p], pos[p + len(sn) - 1] + 1
    return None


def _excise_note(norm: str, body: str, marker: str) -> tuple[str, int] | None:
    """Locate a note ``body`` (its leading marker already dropped) in ``norm``
    and remove it, PLUS the printed delimiter/space the marker left immediately
    in front of it — otherwise a '1. body' note orphans a stray '.' once the
    marker digit alone is stripped. The marker glyphs themselves are removed by
    the caller's global pass. Returns (new_norm, chars_removed) or None."""
    span = _find_fuzzyish(norm, body)
    if span is None:
        # tolerate marker-prefix differences: try without the first token
        span = _find_fuzzyish(norm, body.split(" ", 1)[-1])
    if span is None:
        return None
    s, e = span
    if marker:
        s = re.search(r"[.)]?\s*$", norm[:s]).start()
    return norm[:s] + " " + norm[e:], e - s
